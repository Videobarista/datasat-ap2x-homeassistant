"""The integration only talks to the configured processor.

The runtime half of the "local only" badge: the real client runs against a
scripted processor (tests/fake_ap20.py) through the config flow, setup,
polling, commands, an options reload and unload. Every connection and every
command line is recorded with the address and port it went to, and all of
them must go to the host and port entered in the config flow. Real network
access is blocked in the tests anyway, so anything else would fail. The only
other thing the integration may reach is the optional power switch entity,
through a Home Assistant action; that is checked here too.

The static half is scripts/check_local_only.py, which is tested here as well.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import shutil
from typing import Any
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

import custom_components.datasat_ap2x as integration
from custom_components.datasat_ap2x.const import (
    CONF_ENABLE_PULSE,
    CONF_POWER_SWITCH,
    DOMAIN,
    SERVICE_PULSE,
)
from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.const import (
    ATTR_DOMAIN,
    ATTR_ENTITY_ID,
    ATTR_SERVICE,
    ATTR_SERVICE_DATA,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    EVENT_CALL_SERVICE,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .fake_ap20 import HOST, MAC, FakeAP20, SentLine, connected_to

ROOT = Path(__file__).resolve().parents[1]
PORT = 14600  # not the default port, so a client that ignores the setting fails
POWER_SWITCH = "input_boolean.rack_power"


def _load_checker() -> Any:
    spec = importlib.util.spec_from_file_location(
        "check_local_only", ROOT / "scripts" / "check_local_only.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Phases:
    """Split what the fake processor recorded into named phases of the test."""

    def __init__(self, device: FakeAP20) -> None:
        self._device = device
        self._starts: list[tuple[str, int, int]] = []

    def start(self, name: str) -> None:
        self._starts.append((name, len(self._device.targets), len(self._device.sent_lines)))

    def connections(self, name: str) -> list[tuple[str, int]]:
        first, last = self._bounds(name, 1)
        return self._device.targets[first:last]

    def lines(self, name: str) -> list[SentLine]:
        first, last = self._bounds(name, 2)
        return self._device.sent_lines[first:last]

    def commands(self, name: str) -> list[str]:
        return [sent.line for sent in self.lines(name)]

    def _bounds(self, name: str, field: int) -> tuple[int, int | None]:
        names = [start[0] for start in self._starts]
        index = names.index(name)
        first = self._starts[index][field]
        last = self._starts[index + 1][field] if index + 1 < len(self._starts) else None
        return first, last


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{MAC}_{key}")
    assert entity_id is not None, f"no {platform} entity with key {key}"
    return entity_id


async def test_all_traffic_goes_to_the_processor(hass: HomeAssistant) -> None:
    """Config flow, setup, polling, commands, reload and unload only reach the processor."""
    device = FakeAP20()
    phases = _Phases(device)
    service_calls: list[tuple[str, str, Any]] = []

    @callback
    def _record_service_call(event: Event) -> None:
        data = event.data.get(ATTR_SERVICE_DATA) or {}
        service_calls.append(
            (event.data[ATTR_DOMAIN], event.data[ATTR_SERVICE], data.get(ATTR_ENTITY_ID))
        )

    hass.bus.async_listen(EVENT_CALL_SERVICE, _record_service_call)
    power_switch_calls = async_mock_service(hass, "input_boolean", "turn_on")

    # Mark where the config flow ends and the real setup begins.
    setup_entry = integration.async_setup_entry

    async def _setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        phases.start("setup")
        return await setup_entry(hass, entry)

    async def _call(domain: str, service: str, entity_id: str, **data: Any) -> None:
        await hass.services.async_call(
            domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
        )
        await hass.async_block_till_done()

    with connected_to(device):
        phases.start("config flow")
        with patch.object(integration, "async_setup_entry", _setup_entry):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_HOST: HOST, CONF_PORT: PORT, CONF_PASSWORD: ""}
            )
            await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
        entry = result["result"]

        phases.start("polling")
        for seconds in (11, 22, 33, 61):
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
            await hass.async_block_till_done()

        phases.start("commands")
        player = _entity_id(hass, "media_player", "media_player")
        commands: list[Callable[[], Awaitable[None]]] = [
            lambda: _call("media_player", "select_source", player, source="Nonsync"),
            lambda: _call("media_player", "volume_up", player),
            lambda: _call("media_player", "volume_mute", player, is_volume_muted=True),
            lambda: _call("number", "set_value", _entity_id(hass, "number", "fader"), value=5.5),
            lambda: _call("switch", "turn_on", _entity_id(hass, "switch", "monitor_mute")),
            lambda: _call("button", "press", _entity_id(hass, "button", "macro_format_1")),
            lambda: _call("media_player", "turn_off", player),
        ]
        for command in commands:
            await command()

        phases.start("reload")
        hass.config_entries.async_update_entry(
            entry, options={CONF_ENABLE_PULSE: True, CONF_POWER_SWITCH: POWER_SWITCH}
        )
        await hass.async_block_till_done()
        await _call(DOMAIN, SERVICE_PULSE, player, gpio=3)
        await _call("media_player", "turn_on", player)

        phases.start("unload")
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    # Every connection and every command line went to the configured host and port.
    assert device.connections >= 2, "the test opened too few connections"
    assert set(device.targets) == {(HOST, PORT)}
    assert {(sent.host, sent.port) for sent in device.sent_lines} == {(HOST, PORT)}

    # Each phase really talked to the processor, so none of them went unchecked.
    expected = {
        "config flow": ["@SYSTEM", "@SERIALNO"],
        "setup": ["@SYSTEM", "@POWER", "@FORMATNAMES", "@MACRONAMES", "@FADER"],
        "polling": ["@POWER", "@FADER", "@MUTED", "@FORMAT", "@MONITORLEVEL"],
        "commands": [
            "@FORMAT Nonsync",
            "@FADER 71",
            "@MUTED 1",
            "@FADER 55",
            "@MONITORMUTE 1",
            "@RUNMACRO FORMAT_1",
            "@POWER 0",
        ],
        "reload": ["@SYSTEM", "@PULSE 3", "@POWER 1"],
    }
    for name, lines in expected.items():
        sent = phases.commands(name)
        assert sent, f"nothing was sent during {name}"
        for line in lines:
            assert line in sent, f"{line} was not sent during {name}"
    assert phases.connections("config flow"), "the config flow opened no connection"
    assert phases.connections("setup"), "setup opened no connection"
    assert phases.connections("unload") == [], "unloading opened a connection"

    # Besides the processor, the integration only switched the configured power switch.
    own_entities = {
        registry_entry.entity_id
        for registry_entry in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    from_integration = [call for call in service_calls if call[2] not in own_entities]
    assert from_integration == [("input_boolean", "turn_on", POWER_SWITCH)]
    assert [call.data[ATTR_ENTITY_ID] for call in power_switch_calls] == [POWER_SWITCH]


def test_static_check_passes() -> None:
    """The integration passes scripts/check_local_only.py."""
    checker = _load_checker()
    assert checker.main(["check_local_only.py"]) == 0


def test_static_check_catches_leaks(tmp_path: Path) -> None:
    """The check fails on an integration that could send data elsewhere."""
    checker = _load_checker()
    leaky = tmp_path / "leaky"
    shutil.copytree(
        ROOT / "custom_components" / DOMAIN,
        leaky,
        ignore=shutil.ignore_patterns("__pycache__"),
    )

    manifest = json.loads((leaky / "manifest.json").read_text())
    manifest.update(
        iot_class="cloud_polling",
        requirements=["phonehome==1.0"],
        dependencies=["cloud"],
        zeroconf=["_datasat._tcp.local."],
    )
    (leaky / "manifest.json").write_text(json.dumps(manifest))

    # The real connection, pointed somewhere other than the configured host.
    api = leaky / "api.py"
    original = "asyncio.open_connection(self.host, self.port"
    source = api.read_text()
    assert original in source
    api.write_text(source.replace(original, "asyncio.open_connection('192.0.2.99', self.port"))

    # The power switch exception, widened to a domain that sends messages out.
    const = leaky / "const.py"
    allowed = 'POWER_SWITCH_DOMAINS = ("switch", "input_boolean", "light")'
    source = const.read_text()
    assert allowed in source
    const.write_text(
        source.replace(
            allowed, 'POWER_SWITCH_DOMAINS = ("switch", "input_boolean", "light", "notify")'
        )
    )
    with (leaky / "media_player.py").open("a") as player:
        player.write(
            "\n\nasync def notify_vendor(hass):\n"
            "    await hass.services.async_call('notify', 'send_message', {})\n"
        )

    (leaky / "telemetry.py").write_text(
        "import asyncio\n"
        "import requests\n"
        "import pycurl\n"
        "from homeassistant.helpers.aiohttp_client import async_get_clientsession\n\n\n"
        "async def leak(hass):\n"
        "    session = async_get_clientsession(hass)\n"
        "    await session.post('https://telemetry.example.com/collect')\n"
        "    await asyncio.start_server(None, '0.0.0.0', 8080)\n"
        "    await asyncio.open_connection('8.8.8.8', 53)\n"
        "    await asyncio.create_subprocess_exec('curl', 'http://198.51.100.7')\n"
        "    await hass.services.async_call('notify', 'send_message', {})\n"
        "    return 'analytics.vendor.io'\n"
    )

    problems, _ = checker.collect_problems(leaky)
    text = "\n".join(problems)
    for expected in (
        "iot_class is 'cloud_polling'",
        "requirement 'phonehome==1.0' is not allowed",
        "depends on 'cloud'",
        "declares discovery via 'zeroconf'",
        "imports requests, which is not on the allowlist",
        "imports pycurl, which is not on the allowlist",
        "imports homeassistant.helpers.aiohttp_client",
        "async_get_clientsession() creates an HTTP session",
        "session.post() makes an HTTP request",
        "start_server() listens for connections",
        "telemetry.py:11: open_connection() outside ['api.py']",
        "open_connection('192.0.2.99', self.port) does not use the configured host and port",
        "create_subprocess_exec() starts another program",
        "services.async_call() outside ['media_player.py']",
        "services.async_call() to 'notify', not a power switch domain",
        "POWER_SWITCH_DOMAINS allows 'notify'",
        "hard-coded address 'https://telemetry.example.com'",
        "hard-coded IP address '8.8.8.8'",
        "hard-coded host name 'analytics.vendor.io'",
    ):
        assert expected in text, f"{expected!r} not reported in:\n{text}"
    assert checker.main(["check_local_only.py", str(leaky)]) == 1
