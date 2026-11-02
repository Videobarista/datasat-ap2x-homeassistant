# Security Policy

## Supported versions

Only the latest released version of this integration receives fixes.

| Version | Supported |
| ------- | --------- |
| 1.6.x   | Yes       |
| < 1.6   | No        |

## Reporting a vulnerability

Please report security issues privately through GitHub's
[Report a vulnerability](https://github.com/Videobarista/datasat-ap2x-homeassistant/security/advisories/new)
form rather than in a public issue. Include the integration version, your Home
Assistant version and the steps needed to reproduce the problem. Leave out IP
addresses, serial numbers and passwords; diagnostics downloaded from Home
Assistant already have them removed.

You can expect a first response within 14 days. Confirmed issues are fixed in a
new release, with credit in the release notes unless you prefer otherwise.

## What the integration does

- **Input checks.** Format names, macro names and the password are checked
  before they are sent: printable ASCII only, no control characters, and no `@`
  in names. A format can only be selected from the unit's own list. No value
  from Home Assistant can add a second command to the line.
- **Untrusted replies.** Replies are limited to 8 KiB and must belong to the
  command that was sent; anything else closes the connection. Numbers outside
  their documented range, and values that are not finite numbers, are treated
  as unknown. Lists of formats and macros are capped at 64 names.
- **Least privilege.** The integration only needs operator commands. Use the
  NetCmd password; logging in with the Setup password raises a repair issue.
  The GPIO pulse action is off by default and limited to administrators and
  automations.
- **Secrets and privacy.** The password is never written to the log, not even at
  debug level. The debug log leaves out the replies that identify the unit, and
  diagnostics redact the password, address, MAC address, serial number and site
  names.
- **No open ports.** The integration listens on nothing and only connects out
  to the configured processor. It has no Python dependencies of its own and
  sends no telemetry.

## What the integration cannot do

The remote command API (TN-H413) is unencrypted. Commands, replies and the
`@AUTH` password travel over plain TCP on port 14500, and anyone on the same
network can connect to that port, or to the processor's VNC server, directly.
The password is stored in the Home Assistant config entry like any other
integration credential, so it is also part of Home Assistant backups. Only the
network can protect against eavesdropping and impersonation:

| From | To the processor | |
| --- | --- | --- |
| Home Assistant | TCP 14500 (control) | allow |
| Other controllers (e.g. Bitfocus Companion) | TCP 14500 | allow |
| One management computer | VNC (TCP 5900 by default) | allow |
| Everything else | anything | block |
| The processor | the internet and other networks | block |

Put the processor in a separate VLAN, give it a fixed address, set both a
NetCmd and a Setup password on the unit, and keep Home Assistant backups
encrypted. Network firmware updates contact Datasat's servers; allow that only
during an update, or update from USB.

Issues in Home Assistant itself belong at
[home-assistant/core](https://github.com/home-assistant/core/security/policy);
issues in the processor's firmware belong with Datasat/ATI.
