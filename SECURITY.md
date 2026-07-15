# Security Policy

## Supported Versions

Device Sentinel is pre-release. Only the latest release receives fixes of any
kind, including security fixes. If you are running an older version, update
first; the issue may already be gone.

| Version        | Supported          |
| -------------- | ------------------ |
| Latest release | :white_check_mark: |
| Anything older | :x:                |

## Reporting a Vulnerability

Report privately through GitHub: the Security tab of this repository, then
"Report a vulnerability." Private vulnerability reporting is enabled. Do not
open a public issue for a security problem.

You can expect an acknowledgment within a few days. If the report is valid,
the fix ships in the next release and the advisory is published after it; if
it is declined, you will get the reasoning, not silence.

Scope worth knowing: Device Sentinel runs entirely inside Home Assistant,
takes no input from the network, and exposes no services to the outside
world. Its attack surface is what Home Assistant grants any integration.
