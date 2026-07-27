# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: messenger.py, Version: 0.9.11 (2026-07-27)

"""Sending the daily brief, and nothing else yet.

The third file split out of the coordinator, and the first that
speaks outward. Ruling 126 holds the event-triggered engine closed
until the detection formulas are settled; ruling 132 lets the
document channel open now, because emailing the brief repeats a
report the person already reads on a schedule they set, and makes no
claim in the moment about a device that just broke. When the push
engine is built it belongs here beside this, which is why the file
exists rather than another method on the coordinator.

Two jobs. The renderer turns the brief into HTML so a mail client
shows its tables as tables. It reads the brief's own text rather
than rebuilding the document from the underlying rows, which
guarantees the email and the file say the same thing: two renderers
over one set of rows could drift, and the difference would be
invisible until somebody compared an email against a file. The
subset it handles is closed because we emit it: one h1, some h2s,
paragraphs, and pipe tables.

The sender reads the settings already stored (#132) and composes
nothing new.
"""

from __future__ import annotations

from html import escape
from typing import Any

from .const import (
    BRIEF_TITLE,
    CONF_BRIEF_TARGETS,
    CONF_REMINDER_MODE,
    DEFAULT_REMINDER_MODE,
    LOGGER,
    PERSISTENT_CREATE,
    PERSISTENT_TARGET,
    REMINDER_MODE_NONE,
    REMINDER_MODE_OVERNIGHT,
)

# Inline rather than a stylesheet block, because several mail
# clients strip a <style> element and would render an unruled table
# of times as a wall of text.
_TABLE_STYLE = (
    "border-collapse:collapse;width:100%;"
    "font-family:sans-serif;font-size:14px"
)
_CELL_STYLE = "border:1px solid #ddd;padding:6px 10px;text-align:left"
_HEAD_STYLE = f"{_CELL_STYLE};background:#f2f2f2;font-weight:bold"


class MessengerMixin:
    """Delivery for the coordinator.

    Mixed into DeviceSentinelCoordinator; every attribute reached
    for here belongs to that class.
    """

    @staticmethod
    def _html_cells(line: str) -> list[str]:
        """Return one pipe-table row's cells, stripped and escaped."""
        return [escape(cell.strip()) for cell in line.strip("|").split("|")]

    @staticmethod
    def _is_table_rule(line: str) -> bool:
        """Return whether a line is a table's header rule."""
        body = line.strip()
        if not body.startswith("|"):
            return False
        return set(body) <= set("|-: ")

    def _brief_html(self, text: str) -> str:
        """Return the brief rendered as HTML for a mail client.

        A closed-subset renderer over our own output, not a Markdown
        parser: the brief emits one h1, h2 sections, plain
        paragraphs and pipe tables, so those four shapes are the
        whole grammar. Anything unrecognized falls through as a
        paragraph, which keeps a future line from vanishing silently.
        """
        out: list[str] = []
        rows: list[list[str]] = []

        def flush_table() -> None:
            """Close any table being accumulated."""
            if not rows:
                return
            head, *body = rows
            cells = "".join(
                f'<th style="{_HEAD_STYLE}">{cell}</th>' for cell in head
            )
            parts = [
                f'<table style="{_TABLE_STYLE}"><tr>{cells}</tr>'
            ]
            for row in body:
                cells = "".join(
                    f'<td style="{_CELL_STYLE}">{cell}</td>' for cell in row
                )
                parts.append(f"<tr>{cells}</tr>")
            parts.append("</table>")
            out.append("".join(parts))
            rows.clear()

        for raw in text.split("\n"):
            line = raw.rstrip()
            if line.startswith("|"):
                if not self._is_table_rule(line):
                    rows.append(self._html_cells(line))
                continue
            flush_table()
            if not line.strip():
                continue
            if line.startswith("## "):
                out.append(f"<h2>{escape(line[3:])}</h2>")
            elif line.startswith("# "):
                out.append(f"<h1>{escape(line[2:])}</h1>")
            else:
                out.append(f"<p>{escape(line)}</p>")
        flush_table()
        body = "\n".join(out)
        return f'<html><body style="font-family:sans-serif">{body}</body></html>'

    def _brief_should_send(self) -> bool:
        """Return whether the day's brief is due to anyone.

        The mode is the whole rule, and quiet hours deliberately do
        not apply (#136). Quiet hours exist to stop an event waking
        somebody; the brief arrives at an hour the person chose, and
        it is the thing that carries what quiet hours suppressed, so
        suppressing it too would mean nothing ever arrived.
        """
        mode = self.entry.options.get(
            CONF_REMINDER_MODE, DEFAULT_REMINDER_MODE
        )
        if mode == REMINDER_MODE_NONE:
            return False
        if mode == REMINDER_MODE_OVERNIGHT and not self._brief_now_rows():
            LOGGER.debug(
                "Daily brief written but not sent: nothing needs "
                "attention and the mode is problems only"
            )
            return False
        return True

    def _brief_payload(self, target: str, text: str) -> dict[str, Any]:
        """Return the service data for one target.

        The persistent notification takes a title and a message and
        nothing else, so the HTML alternative is offered only to the
        notify services, which ignore a data key they do not know.
        """
        payload: dict[str, Any] = {"title": BRIEF_TITLE, "message": text}
        if target != PERSISTENT_TARGET:
            payload["data"] = {"html": self._brief_html(text)}
        return payload

    async def async_send_brief(self, text: str | None) -> int:
        """Send a closed brief to its targets, and return how many took it.

        Called only from the brief's own scheduled write, so a
        regenerate or a midnight rewrite cannot mail an in-progress
        document (#135). Each target is tried on its own and a
        failure is logged rather than raised: one unreachable mail
        server must not stop the other targets, and a brief that
        cannot be delivered is still written to disk.
        """
        if not text or not self._brief_should_send():
            return 0
        targets = [
            target
            for target in (self.entry.options.get(CONF_BRIEF_TARGETS) or [])
            if target
        ]
        if not targets:
            return 0
        sent = 0
        for target in targets:
            if target == PERSISTENT_TARGET:
                domain, service = PERSISTENT_TARGET, PERSISTENT_CREATE
            else:
                domain, _, service = target.partition(".")
                if not service:
                    LOGGER.warning(
                        "Daily brief target %s is not a service, skipped",
                        target,
                    )
                    continue
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    self._brief_payload(target, text),
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                # A notify platform can raise anything from a socket
                # error to a vendor exception, and none of them is
                # worth losing the remaining targets over.
                LOGGER.warning(
                    "Daily brief to %s was not delivered: %s", target, err
                )
                continue
            sent += 1
        LOGGER.debug(
            "Daily brief sent to %d of %d target(s)", sent, len(targets)
        )
        return sent
