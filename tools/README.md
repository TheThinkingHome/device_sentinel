<!-- File: tools/README.md, Version: 0.28.11 (2026-11-10) -->
# Tools

Scripts for working on Device Sentinel. None of them is part of the integration, and Home Assistant never runs them. Each one says how to run it at the top of the file.

| File | What it does |
|---|---|
| `panel_checks/` | Checks for the dashboard, which is JavaScript and cannot be tested by pytest. Each file loads the panel into a browser that runs inside the test and checks what it draws. Their own [README](panel_checks/README.md) lists them. |
| `setup_container.sh` | Builds the whole test environment in a fresh container: both Home Assistant test harnesses and the browser for the panel checks. Run it from the repository's top folder. |
| `anonymise_fleet.py` | Makes the test houses from real houses' files. The names in them are replaced, so no house can be recognised, and the real files stay with their owners. |
| `check_comments.py` | Lists any comment or docstring that tells the history of a line (a release, a date, a person) instead of naming the rule it follows. |
| `compare_code.py` | Proves that two copies of the code differ only in comments and docstrings, or with `--text`, only in their words. |
| `update_battery_library.py` | Refreshes the copy of the Battery Notes library that Device Sentinel ships. Run before each Latest release. |
