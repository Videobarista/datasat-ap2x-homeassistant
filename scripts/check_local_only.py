"""Check that the Datasat AP20/AP25 integration only talks to its own processor.

Runs with the Python standard library only (no installs), on Python 3.10+.
It reads the integration's manifest and source code and fails when it finds
anything that could send data elsewhere:

1. Manifest: IoT class local_polling, no dependencies, no requirements and no
   discovery (the processor is added by its address only).
2. Imports: only the modules on the allowlist below. A new library or network
   module fails the check until it has been reviewed and added on purpose.
3. No listeners or subprocesses: nothing opens a server, webhook, HTTP view or
   UDP socket, and nothing starts another program.
4. One way out: only api.py opens connections, only with asyncio's
   open_connection(), and only to the configured address and port
   (self.host, self.port). No HTTP client sessions anywhere.
5. Service calls: only the optional power switch, see the exception below.
6. No hard-coded internet addresses: no URLs with a host, public host names
   or IP addresses in the code; every address comes from the configuration.

What it does not cover: Home Assistant itself. The runtime side (all traffic
goes to the configured address and port) is checked by tests/test_local_only.py.

Usage: python3 scripts/check_local_only.py [path/to/custom_components/datasat_ap2x]
"""

from __future__ import annotations

import ast
import ipaddress
import json
from pathlib import Path
import re
import sys

# ---------------------------------------------------------------------------
# Settings for this integration
# ---------------------------------------------------------------------------
# The processor speaks a plain-text protocol over one TCP connection (TN-H413,
# port 14500 by default). No HTTP, no UDP, no SNMP, no device library.

# The IoT class the manifest must declare.
IOT_CLASS = "local_polling"
# The only file that may open connections, the only call it may use for that,
# and the only target that call may be given: the address and port from the
# configuration, stored on the client object.
CONNECTION_FILES = {"api.py"}
ALLOWED_CONNECT_CALLS = {"open_connection"}
CONNECTION_TARGET = ("self.host", "self.port")
# Python requirements and manifest dependencies that are allowed: none. The
# TCP client is part of the integration itself (api.py).
ALLOWED_REQUIREMENTS: set[str] = set()
ALLOWED_DEPENDENCIES: set[str] = set()
# Imports that are allowed. Everything the integration uses today, nothing more.
ALLOWED_IMPORTS = {
    "__future__",
    "asyncio",
    "collections.abc",
    "dataclasses",
    "datetime",
    "logging",
    "math",
    "typing",
    "voluptuous",
}
ALLOWED_IMPORT_PREFIXES = ("homeassistant.",)
# Literal addresses that are allowed in the code (none needed here).
ALLOWED_ADDRESSES: set[str] = set()

# Exception: the optional external power switch. The processor cannot switch
# itself off completely, so media_player.py can forward turn_on/turn_off to a
# switch the user picked in the options (a smart plug or relay). That goes
# through Home Assistant's own service registry, to an entity in Home Assistant,
# not over the network from this integration. Only this file may call services,
# and the entity's domain is checked at runtime against POWER_SWITCH_DOMAINS in
# const.py, which must stay within these domains:
SERVICE_CALL_FILES = {"media_player.py"}
ALLOWED_SERVICE_DOMAINS = {"switch", "input_boolean", "light"}
SERVICE_DOMAIN_CONSTANT = ("const.py", "POWER_SWITCH_DOMAINS")

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
# Manifest keys for discovery: Home Assistant would listen or broadcast for the
# device on the integration's behalf.
FORBIDDEN_MANIFEST_KEYS = {"bluetooth", "dhcp", "homekit", "mqtt", "ssdp", "usb", "zeroconf"}
# Home Assistant modules that serve, reach the cloud or make HTTP requests.
# They start with "homeassistant." and would otherwise pass the allowlist.
FORBIDDEN_MODULES = {
    "homeassistant.components.cloud",
    "homeassistant.components.http",
    "homeassistant.components.mqtt",
    "homeassistant.components.ssdp",
    "homeassistant.components.webhook",
    "homeassistant.components.zeroconf",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.httpx_client",
    "homeassistant.helpers.network",
}
# Calls that listen for incoming connections.
LISTEN_CALLS = {
    "create_datagram_endpoint",
    "create_server",
    "create_unix_server",
    "register_view",
    "sock_accept",
    "start_server",
    "start_unix_server",
}
# Calls that open outgoing connections or look up addresses.
CONNECT_CALLS = {
    "create_connection",
    "getaddrinfo",
    "gethostbyname",
    "open_connection",
    "open_unix_connection",
    "sock_connect",
    "ws_connect",
}
# Calls that start another program (which could make its own connections).
SPAWN_CALLS = {"create_subprocess_exec", "create_subprocess_shell"}
SESSION_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "request"}
SESSION_FACTORIES = {"async_create_clientsession", "async_get_clientsession"}
SERVICE_CALLS = {"async_call", "call"}

_URL = re.compile(r"\b(?:https?|wss?|ftp|mqtts?|tcp|udp|telnet)://([^\s/'\"{}]+)", re.IGNORECASE)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])", re.IGNORECASE)
_TLDS = "com|net|org|io|dev|app|cloud|ai|co|eu|nl|de|be|uk|fr|info|biz|me|tv|us"
_HOSTNAME = re.compile(rf"(?:[a-z0-9-]+\.)+(?:{_TLDS})", re.IGNORECASE)
# Example and loopback addresses never leave the machine or the documentation.
_HARMLESS_NETWORKS = [
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",
        "127.0.0.0/8",
        "192.0.2.0/24",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "::1/128",
        "2001:db8::/32",
    )
]


def _harmless_ip(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return True  # Not an address (a version number or a time, for instance).
    return any(address in network for network in _HARMLESS_NETWORKS)


def _call_name(node: ast.Call) -> tuple[str, str]:
    """Return (attribute or function name, name of the object it is called on)."""
    func = node.func
    if isinstance(func, ast.Attribute):
        owner = func.value
        if isinstance(owner, ast.Attribute):
            return func.attr, owner.attr
        if isinstance(owner, ast.Name):
            return func.attr, owner.id
        return func.attr, ""
    if isinstance(func, ast.Name):
        return func.id, ""
    return "", ""


def _connection_target(node: ast.Call) -> tuple[str, str]:
    """Return the host and port expressions given to a connect call, as source text."""
    arguments = [ast.unparse(arg) for arg in node.args[:2]]
    keywords = {kw.arg: ast.unparse(kw.value) for kw in node.keywords if kw.arg}
    host = arguments[0] if arguments else keywords.get("host", "")
    port = arguments[1] if len(arguments) > 1 else keywords.get("port", "")
    return host, port


def _is_allowed_import(module: str) -> bool:
    return module in ALLOWED_IMPORTS or module.startswith(ALLOWED_IMPORT_PREFIXES)


def check_manifest(integration: Path) -> list[str]:
    """Check the manifest for cloud use, discovery, dependencies and requirements."""
    manifest = json.loads((integration / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    iot_class = str(manifest.get("iot_class", ""))
    if iot_class != IOT_CLASS:
        problems.append(f"manifest.json: iot_class is {iot_class!r}, expected {IOT_CLASS!r}")
    dependencies = set(manifest.get("dependencies", [])) | set(
        manifest.get("after_dependencies", [])
    )
    for dependency in sorted(dependencies - ALLOWED_DEPENDENCIES):
        problems.append(f"manifest.json: depends on {dependency!r}")
    for key in sorted(FORBIDDEN_MANIFEST_KEYS & set(manifest)):
        problems.append(f"manifest.json: declares discovery via {key!r}")
    for requirement in manifest.get("requirements", []):
        name = re.split(r"[<>=!~\[; @]", requirement, maxsplit=1)[0].lower()
        if name not in {r.lower() for r in ALLOWED_REQUIREMENTS}:
            problems.append(f"manifest.json: requirement {requirement!r} is not allowed")
    return problems


def _check_import(node: ast.Import | ast.ImportFrom, where: str) -> list[str]:
    problems = []
    if isinstance(node, ast.Import):
        modules = [alias.name for alias in node.names]
        names = modules
    elif node.level:
        return []  # A module of the integration itself.
    else:
        modules = [node.module or ""]
        names = modules + [f"{node.module}.{alias.name}" for alias in node.names if node.module]
    for module in modules:
        if not _is_allowed_import(module):
            problems.append(f"{where}: imports {module}, which is not on the allowlist")
    for name in names:
        if any(name == m or name.startswith(f"{m}.") for m in FORBIDDEN_MODULES):
            problems.append(f"{where}: imports {name}")
    return problems


def _check_call(node: ast.Call, path: Path, where: str) -> list[str]:
    name, owner = _call_name(node)
    if name in LISTEN_CALLS:
        return [f"{where}: {name}() listens for connections"]
    if name in SPAWN_CALLS:
        return [f"{where}: {name}() starts another program"]
    if name in CONNECT_CALLS:
        if path.name not in CONNECTION_FILES:
            return [f"{where}: {name}() outside {sorted(CONNECTION_FILES)}"]
        if name not in ALLOWED_CONNECT_CALLS:
            return [f"{where}: {name}() is not one of {sorted(ALLOWED_CONNECT_CALLS)}"]
        if _connection_target(node) != CONNECTION_TARGET:
            host, port = _connection_target(node)
            return [
                f"{where}: {name}({host}, {port}) does not use the configured host and port "
                f"({', '.join(CONNECTION_TARGET)})"
            ]
        return []
    if name in SESSION_FACTORIES:
        return [f"{where}: {name}() creates an HTTP session; this integration uses none"]
    if name in SESSION_METHODS and "session" in owner.lower():
        return [f"{where}: {owner}.{name}() makes an HTTP request; this integration uses none"]
    if name in SERVICE_CALLS and owner == "services":
        if path.name not in SERVICE_CALL_FILES:
            return [f"{where}: services.{name}() outside {sorted(SERVICE_CALL_FILES)}"]
        domain = node.args[0] if node.args else None
        if (
            isinstance(domain, ast.Constant)
            and isinstance(domain.value, str)
            and domain.value not in ALLOWED_SERVICE_DOMAINS
        ):
            return [f"{where}: services.{name}() to {domain.value!r}, not a power switch domain"]
    return []


def _check_constant(text: str, where: str) -> list[str]:
    if text in ALLOWED_ADDRESSES:
        return []
    problems = [f"{where}: hard-coded address {match.group(0)!r}" for match in _URL.finditer(text)]
    for pattern in (_IPV4, _IPV6):
        for match in pattern.finditer(text):
            if not _harmless_ip(match.group(0)):
                problems.append(f"{where}: hard-coded IP address {match.group(0)!r}")
    if _HOSTNAME.fullmatch(text.strip()):
        problems.append(f"{where}: hard-coded host name {text!r}")
    return problems


def check_source(path: Path, relative: str) -> list[str]:
    """Check one Python file of the integration."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    problems = []
    for node in ast.walk(tree):
        where = f"{relative}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            problems += _check_import(node, where)
        elif isinstance(node, ast.Call):
            problems += _check_call(node, path, where)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            problems += _check_constant(node.value, where)
    return problems


def check_service_domains(integration: Path) -> list[str]:
    """Check that the power switch exception stays as narrow as documented above."""
    file_name, constant = SERVICE_DOMAIN_CONSTANT
    tree = ast.parse((integration / file_name).read_text(encoding="utf-8"))
    domains: set[str] | None = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == constant for t in node.targets)
            and isinstance(node.value, (ast.Tuple, ast.List, ast.Set))
        ):
            domains = {
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    if domains is None:
        return [f"{file_name}: {constant} is missing or not a literal tuple of domains"]
    problems = [
        f"{file_name}: {constant} allows {domain!r}, which is not a power switch domain"
        for domain in sorted(domains - ALLOWED_SERVICE_DOMAINS)
    ]
    for service_file in sorted(SERVICE_CALL_FILES):
        uses_guard = any(
            isinstance(node, ast.Name) and node.id == constant
            for node in ast.walk(ast.parse((integration / service_file).read_text("utf-8")))
        )
        if not uses_guard:
            problems.append(f"{service_file}: service calls are not checked against {constant}")
    return problems


def collect_problems(integration: Path) -> tuple[list[str], int]:
    """Run every check; return the problems and the number of Python files read."""
    problems = check_manifest(integration) + check_service_domains(integration)
    files = sorted(integration.rglob("*.py"))
    for path in files:
        problems += check_source(path, str(path.relative_to(integration.parent)))
    return problems, len(files)


def find_integration(argv: list[str]) -> Path:
    """Return the integration folder (argument, or the only one in custom_components)."""
    if len(argv) > 1:
        return Path(argv[1])
    root = Path(__file__).resolve().parents[1] / "custom_components"
    folders = [p for p in root.iterdir() if (p / "manifest.json").is_file()]
    if len(folders) != 1:
        raise SystemExit(f"Expected one integration in {root}, found {len(folders)}")
    return folders[0]


def main(argv: list[str]) -> int:
    """Run all checks and report."""
    integration = find_integration(argv)
    problems, file_count = collect_problems(integration)

    print(f"Local-only check of {integration.name}: {file_count} Python files")
    if problems:
        for problem in problems:
            print(f"  FAIL {problem}")
        return 1
    print(f"  OK   manifest: {IOT_CLASS}, no dependencies, requirements or discovery")
    print("  OK   imports: only the standard library modules, voluptuous and Home Assistant")
    print("       modules on the allowlist")
    print("  OK   no listeners, webhooks, HTTP views, HTTP sessions or subprocesses")
    print(
        f"  OK   connections only from {', '.join(sorted(CONNECTION_FILES))}, with "
        f"{', '.join(sorted(ALLOWED_CONNECT_CALLS))}({', '.join(CONNECTION_TARGET)})"
    )
    domains = ", ".join(sorted(ALLOWED_SERVICE_DOMAINS))
    print(f"  OK   service calls only to a power switch ({domains})")
    print("  OK   no hard-coded internet addresses")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
