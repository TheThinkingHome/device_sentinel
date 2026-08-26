# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: messenger.py, Version: 0.18.2 (2026-08-26)

"""Sending the daily brief, and nothing else yet.

The third file split out of the coordinator, and the first that
speaks outward. Ruling 126 holds the event-triggered engine closed
until the detection formulas are settled; ruling 132 lets the
document channel open now, because emailing the brief repeats a
report the person already reads on a schedule they set, and makes no
claim in the moment about a device that just broke. When the push
engine is built it belongs here beside this, which is why the file
exists rather than another method on the coordinator.

One job now. This module chooses the targets and sends; the
rendering lives with the reports, which is where the document is
written, so the email and the file are one string rather than two
renderings that agree by inspection. This file used to hold a second
renderer, and the warning written here at the time, that two
renderers over one set of rows could drift invisibly until somebody
compared an email against a file, turned out to be exactly what
happened (ruling #188).

The sender reads the settings already stored and composes nothing
new. That is what lets it ship while the event-triggered engine is
still held shut: mailing a document a person already reads asserts
nothing the file did not already assert, where a push says this
device is wrong now and inherits the formula behind it
(ruling #132).
"""

from __future__ import annotations

from typing import Any

from .const import (
    BRIEF_TITLE,
    CONF_BRIEF_TARGETS,
    CONF_REMINDER_MODE,
    DEFAULT_REMINDER_MODE,
    LOGGER,
    PERSISTENT_CREATE,
    PERSISTENT_TARGET,
    RESTORE_NOTICE_ID,
    RESTORE_NOTICE_TITLE,
    REMINDER_MODE_NONE,
    REMINDER_MODE_OVERNIGHT,
)

# Inline rather than a stylesheet block, because several mail
# clients strip a <style> element and would render an unruled table
# of times as a wall of text.


class MessengerMixin:
    """Delivery for the coordinator.

    Mixed into DeviceSentinelCoordinator; every attribute reached
    for here belongs to that class.
    """

    def _brief_should_send(self) -> bool:
        """Return whether the day's brief is due to anyone.

        The mode is the whole rule, and quiet hours deliberately do
        not apply. Quiet hours exist to stop an event waking
        somebody; the brief arrives at an hour the person chose, and
        it is the thing that carries what quiet hours suppressed, so
        suppressing it too would mean nothing ever arrived
        (ruling #136).
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
            # The emailed body is the brief page itself, the same
            # string written to www: one rendering serves the file,
            # the dashboard card, and the mail client, so what
            # arrives is what is on disk. The composed text stays as
            # the message field for services without HTML and as the
            # plain fallback. The rule that the mail must be the
            # document that was written predates the HTML page and
            # was carried across to it when the page replaced the
            # Markdown brief (rulings #135 and #179).
            #
            # The stashed page is used only where it was rendered
            # from this very text, so the body can never describe a
            # different document from the one being sent
            # (ruling #184). A
            # mismatched or missing stash renders the text again
            # rather than sending the stashed page. Since the two
            # renderers became one (ruling #188) that fallback
            # produces the identical document, so a mismatch now
            # costs nothing at all.
            stashed_text, stashed_page = getattr(
                self, "_last_brief_pair", (None, None)
            )
            payload["data"] = {
                "html": stashed_page
                if stashed_page is not None and stashed_text == text
                else self._render_brief_html(text)
            }
        return payload

    async def async_send_brief(self, text: str | None) -> int:
        """Send a closed brief to its targets, and return how many took it.

        Called only from the brief's own scheduled write, so a
        regenerate or a midnight rewrite cannot mail an in-progress
        document: mailing one of those would deliver the same day
        several times, each incomplete (ruling #135). Each target is
        tried on its own and a
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

    async def async_announce_restore(
        self, headline: str, detail: str
    ) -> int:
        """Send the restore notice everywhere, ignoring quiet hours.

        Ruling #345. Three surfaces: the daily-brief targets, which
        is where a person's email lives; the high-priority targets,
        which is the phone; and a persistent notification carrying an
        id of its own.

        The id matters. The three standing surfaces each overwrite
        themselves by design, and a restore notice sharing one of
        those ids would be gone by the next brief. This one has its
        own, so it sits in the panel until it is dismissed, which
        makes it the most durable of the three channels rather than
        the most fragile.

        Quiet hours do not apply. A device flapping at three in the
        morning should stay quiet; a storage file that could not be
        read is a one-time event about the integrity of everything
        the integration knows, and a person wants it on waking rather
        than three days later.

        Every target is tried on its own and a failure is a log line:
        the restore already succeeded, and a notify platform that
        will not answer must not turn a recovery into an error.
        """
        message = f"{headline}\n\n{detail}"
        sent = 0
        targets = {
            target
            for target in (self.entry.options.get(CONF_BRIEF_TARGETS) or [])
            if target and target != PERSISTENT_TARGET
        }
        targets.update(self._high_priority_targets())
        for target in sorted(targets):
            domain, _, service = target.partition(".")
            if not service:
                continue
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    {"title": RESTORE_NOTICE_TITLE, "message": message},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                LOGGER.warning(
                    "Restore notice to %s was not delivered: %s", target, err
                )
                continue
            sent += 1
        try:
            await self.hass.services.async_call(
                PERSISTENT_TARGET,
                PERSISTENT_CREATE,
                {
                    "title": RESTORE_NOTICE_TITLE,
                    "message": message,
                    "notification_id": RESTORE_NOTICE_ID,
                },
                blocking=True,
            )
            sent += 1
        except Exception as err:  # noqa: BLE001
            LOGGER.warning("Restore notice was not posted: %s", err)
        LOGGER.warning("Restore notice sent to %d surface(s)", sent)
        return sent
