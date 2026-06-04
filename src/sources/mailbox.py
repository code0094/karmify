"""IMAP mailbox helper: poll for the Bandcamp download-link email.

Bandcamp's anonymous "name your price = 0" flow emails a download link instead of
serving it inline. The app uses a dedicated mailbox (e.g. Gmail + app password,
with ``you+random@gmail.com`` plus-aliases) and this helper reads the incoming
message and extracts the download URL.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import re
from email.message import Message

import structlog

logger = structlog.get_logger()

# Bandcamp download pages live under .bandcamp.com/download or bcbits.com links.
_LINK_RE = re.compile(r"https?://[^\s\"'<>]*bandcamp\.com/download[^\s\"'<>]*", re.IGNORECASE)


class Mailbox:
    """Reads the mailbox that receives Bandcamp download-link emails."""

    def __init__(self, imap_host: str, address: str, password: str) -> None:
        self._host = imap_host
        self._address = address
        self._password = password

    async def wait_for_download_link(
        self, *, to_alias: str, timeout: float = 180.0, poll_interval: float = 5.0
    ) -> str:
        """Poll the inbox until a Bandcamp download link addressed to ``to_alias`` arrives.

        Raises:
            TimeoutError: If no matching email is found within ``timeout`` seconds.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            link = await asyncio.to_thread(self._find_link, to_alias)
            if link:
                logger.info("mailbox.link_found", alias=to_alias)
                return link
            await asyncio.sleep(poll_interval)
        raise TimeoutError(f"No Bandcamp email for {to_alias} within {timeout:.0f}s")

    def _find_link(self, to_alias: str) -> str | None:
        """Blocking IMAP scan for an unseen Bandcamp email addressed to ``to_alias``."""
        conn = imaplib.IMAP4_SSL(self._host)
        try:
            conn.login(self._address, self._password)
            conn.select("INBOX")
            typ, data = conn.search(None, '(UNSEEN FROM "bandcamp.com")')
            if typ != "OK" or not data or not data[0]:
                return None

            for num in data[0].split():
                typ, msg_data = conn.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                msg = email.message_from_bytes(msg_data[0][1])

                if to_alias.lower() not in (msg.get("To") or "").lower():
                    continue

                link = self._extract_link(msg)
                if link:
                    conn.store(num, "+FLAGS", "\\Seen")
                    return link
            return None
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001 - logout failures are non-fatal
                logger.debug("mailbox.logout_failed")

    @staticmethod
    def _extract_link(msg: Message) -> str | None:
        """Pull the first Bandcamp download URL from a message's text/html parts."""
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type not in ("text/plain", "text/html"):
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            match = _LINK_RE.search(text)
            if match:
                return match.group(0)
        return None
