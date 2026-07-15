# Contributing to Device Sentinel

Thanks for the interest. A few things worth knowing before you open an issue or a pull request.

## The state of the project

Device Sentinel is pre-release and built in strict, ordered steps: observe, learn, detect, notify. Each step is proven on a live system before the next begins. The design document rules the build; decisions recorded there are not re-litigated in issues, though new evidence is always welcome.

## Bug reports

Evidence beats description. The bug report form asks for the diagnostics download (Settings, Devices and Services, Device Sentinel, three-dot menu, Download diagnostics) because it answers most questions before they are asked. Reports with diagnostics get fixed; reports without them get a request for diagnostics.

## Feature requests

Welcome, especially the real-situation kind: what happened in your home that this would have caught? Ideas that fit the design land in the queue. Detection accuracy comes first, everything else after.

## Pull requests

Held until 1.0. The pre-release build follows a single design under active development, and outside code, however good, would collide with steps already in motion. After 1.0 this section changes.

## Code standards, for later

Docstrings carry the decision and the reason, not just the what. Inline comments explain why, never narrate. Names are fully descriptive, no abbreviations. Every source file carries the copyright header. The test suite runs on every push and stays green.

## License

GPL-3.0-or-later. Contributions, when they open, are accepted under the same license. Copyright (C) 2026 James Lander, The Thinking Home.
