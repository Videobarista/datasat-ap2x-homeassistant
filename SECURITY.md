# Security Policy

## Supported versions

Only the latest released version of this integration receives fixes.

| Version | Supported |
| ------- | --------- |
| 1.1.x   | Yes       |
| < 1.1   | No        |

## Reporting a vulnerability

Please report security issues privately through GitHub's
[Report a vulnerability](https://github.com/Videobarista/datasat-ap2x-homeassistant/security/advisories/new)
form rather than in a public issue. Include the integration version, your Home
Assistant version and the steps needed to reproduce the problem.

You can expect a first response within 14 days. Confirmed issues are fixed in a
new release, with credit in the release notes unless you prefer otherwise.

## Scope and known limitations

This integration talks to a Datasat AP20/AP25 over its documented remote command
API (TN-H413). A few properties of that protocol are worth knowing:

- **The protocol is unencrypted.** Commands, responses and the `@AUTH` password
  travel over plain TCP on port 14500. Keep the processor on a trusted or
  isolated network segment; do not expose port 14500 to the internet.
- **Password storage.** The optional NetCmd/Setup password is stored in the Home
  Assistant config entry, like any other integration credential. Anyone with
  access to your Home Assistant configuration can read it.
- **No authorisation levels.** Once authenticated, the connection can issue every
  operator-level command for as long as it stays open.
- **Local network only.** The integration makes no outbound connections other
  than to the configured processor, and sends no telemetry.

Issues in Home Assistant itself belong at
[home-assistant/core](https://github.com/home-assistant/core/security/policy);
issues in the processor's firmware belong with Datasat/ATI.
