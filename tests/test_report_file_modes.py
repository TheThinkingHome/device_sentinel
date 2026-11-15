# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_report_file_modes.py, Version: 0.29.0 (2026-11-14)

"""Report files are readable by their owner only (rule CODE-10).

The reports and the probe file name the house's devices and when they
failed. Nothing else on the host needs them, so they are created with
mode 600, as the storage copies are, and a probe file an earlier release
made readable to all is narrowed at its next write.
"""

from __future__ import annotations

import os
import stat

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import REPORT_DIR, REPORT_STACK_PROBE
from custom_components.device_sentinel.reports import ReportWritingMixin

from tests.helpers import setup_coordinator


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_a_report_is_written_owner_only(tmp_path):
    path = tmp_path / "daily_brief.html"
    ReportWritingMixin._write_file(str(path), "<p>brief</p>")
    assert path.read_text(encoding="utf-8") == "<p>brief</p>"
    assert _mode(path) == 0o600


def test_a_rewritten_report_is_owner_only(tmp_path):
    path = tmp_path / "device_telemetry.md"
    path.write_text("old", encoding="utf-8")
    os.chmod(path, 0o644)
    ReportWritingMixin._write_file(str(path), "new")
    assert _mode(path) == 0o600


async def test_an_old_probe_file_is_narrowed_at_its_next_write(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    directory = hass.config.path(REPORT_DIR)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, REPORT_STACK_PROBE)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(coord._probe_header()) + "\n")
    os.chmod(path, 0o644)
    await hass.async_add_executor_job(coord._probe_write_lines, ["| a line |"])
    assert _mode(path) == 0o600
    assert "| a line |" in open(path, encoding="utf-8").read()
    os.remove(path)
