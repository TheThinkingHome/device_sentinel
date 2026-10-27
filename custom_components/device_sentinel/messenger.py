# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: messenger.py, Version: 0.27.10 (2026-10-27)

"""Sending the daily brief, and the notice after a storage restore.

A file split out of the coordinator. The engine that pushes about
devices lives in `notifier.py`; this file keeps the two messages that
are documents and notices rather than alerts.

This module chooses the targets and sends; the
rendering lives with the reports, which is where the document is
written, so the email and the file are one string rather than two
renderings that can drift apart (rule BRIEF-12).

The sender reads the settings already stored and composes nothing
new: mailing a document a person already reads asserts nothing the
file did not already assert, where a push says this device is wrong
now and inherits the formula behind it (rule BRIEF-11).
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
    RESTORE_NOTICE_TITLE,
    REMINDER_MODE_NONE,
    REMINDER_MODE_OVERNIGHT,
    SMTP_DOMAIN,
    SMTP_SEND_MESSAGE,
    SMTP_TARGET_PREFIX,
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
        (rule NOTE-07).
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
            # string written to the reports folder: one rendering
            # serves the file and the mail client, so what arrives
            # is what is on disk. The composed text stays as
            # the message field for services without HTML and as the
            # plain fallback. The mail is the document that was
            # written (rule BRIEF-12).
            #
            # The stashed page is used only where it was rendered
            # from this very text, so the body can never describe a
            # different document from the one being sent. A
            # mismatched or missing stash renders the text again
            # rather than sending the stashed page. There is one
            # renderer, so that fallback produces the identical
            # document (rule BRIEF-12).
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
        several times, each incomplete (rule BRIEF-11). Each target is
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
            if target.startswith(SMTP_TARGET_PREFIX):
                # An SMTP recipient chosen as its entity: the page goes
                # as the email's HTML body through smtp.send_message,
                # which Home Assistant keeps when it retires the
                # old-style notify actions for SMTP in 2027.3. The
                # composed text stays as the plain body.
                payload = self._brief_payload(target, text)
                try:
                    await self.hass.services.async_call(
                        SMTP_DOMAIN,
                        SMTP_SEND_MESSAGE,
                        {
                            "title": payload["title"],
                            "message": payload["message"],
                            "html": payload["data"]["html"],
                        },
                        blocking=True,
                        target={"entity_id": target[len(SMTP_TARGET_PREFIX):]},
                    )
                except Exception as err:  # noqa: BLE001
                    LOGGER.warning(
                        "Daily brief to %s was not delivered: %s", target, err
                    )
                    continue
                sent += 1
                continue
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

        Two surfaces here: the daily-brief targets,
        which is where a person's email lives, and the high-priority
        targets, which is the phone. The durable third is a Repair
        card the caller raises: it sits where a person looks for
        things needing attention, survives a restart, and carries a
        severity (rule REP-08).

        Quiet hours do not apply. A device flapping at three in the
        morning should stay quiet; a storage file that could not be
        read is a one-time event about the integrity of everything
        the integration knows, and a person wants it on waking rather
        than three days later (rule STOR-12).

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
        # The high-priority targets at any hour (rule STOR-12), and the
        # normal-priority targets outside Quiet Hours, as every push
        # reaches them (rule NOTE-02).
        targets.update(self._push_targets())
        for target in sorted(targets):
            call: dict[str, Any] = {}
            if target.startswith(SMTP_TARGET_PREFIX):
                domain, service = SMTP_DOMAIN, SMTP_SEND_MESSAGE
                call["target"] = {
                    "entity_id": target[len(SMTP_TARGET_PREFIX):]
                }
            else:
                domain, _, service = target.partition(".")
                if not service:
                    continue
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    {"title": RESTORE_NOTICE_TITLE, "message": message},
                    blocking=True,
                    **call,
                )
            except Exception as err:  # noqa: BLE001
                LOGGER.warning(
                    "Restore notice to %s was not delivered: %s", target, err
                )
                continue
            sent += 1
        # No persistent notification here. The durable surface is a
        # repair card, raised by the caller, because posting both puts
        # one event on five surfaces with the most durable one in the
        # place things are dismissed by reflex (rule REP-08).
        LOGGER.debug("Restore notice sent to %d surface(s)", sent)
        return sent
