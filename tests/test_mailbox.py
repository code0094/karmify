"""Tests for the Bandcamp IMAP mailbox: link extraction and the wait loop."""

from email.message import EmailMessage
from unittest.mock import MagicMock

import pytest

import src.sources.mailbox as mailbox_mod
from src.sources.mailbox import Mailbox


def test_extract_link_from_plain_text() -> None:
    msg = EmailMessage()
    msg["To"] = "me+abc123@gmail.com"
    msg.set_content(
        "Thanks! Download here: https://artist.bandcamp.com/download/track?id=1&sig=xyz enjoy"
    )
    link = Mailbox._extract_link(msg)
    assert link is not None
    assert link.startswith("https://artist.bandcamp.com/download/track")
    assert "sig=xyz" in link


def test_extract_link_none_when_absent() -> None:
    msg = EmailMessage()
    msg.set_content("No links here, sorry.")
    assert Mailbox._extract_link(msg) is None


# ---- wait_for_download_link loop ------------------------------------------

LINK = "https://artist.bandcamp.com/download/track?id=1"


def _mailbox() -> Mailbox:
    return Mailbox("imap.example.com", "me@gmail.com", "pw")


@pytest.mark.asyncio
async def test_wait_link_returns_on_first_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    mb = _mailbox()
    # _find_link is the IMAP boundary; MagicMock (not Async) — called via to_thread.
    monkeypatch.setattr(mb, "_find_link", MagicMock(return_value=LINK))

    assert await mb.wait_for_download_link(to_alias="me+x@gmail.com", timeout=5) == LINK


@pytest.mark.asyncio
async def test_wait_link_polls_until_found(monkeypatch: pytest.MonkeyPatch) -> None:
    mb = _mailbox()
    finder = MagicMock(side_effect=[None, LINK])
    monkeypatch.setattr(mb, "_find_link", finder)

    link = await mb.wait_for_download_link(to_alias="me+x@gmail.com", timeout=5, poll_interval=0)

    assert link == LINK
    assert finder.call_count == 2


@pytest.mark.asyncio
async def test_wait_link_timeout_zero_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    mb = _mailbox()
    finder = MagicMock(return_value=LINK)
    monkeypatch.setattr(mb, "_find_link", finder)

    with pytest.raises(TimeoutError):
        await mb.wait_for_download_link(to_alias="me+x@gmail.com", timeout=0)
    finder.assert_not_called()  # zero timeout means not even one poll


# ---- _find_link IMAP layer -------------------------------------------------


def _mail_bytes(to: str, body: str) -> bytes:
    msg = EmailMessage()
    msg["To"] = to
    msg.set_content(body)
    return msg.as_bytes()


def _fake_imap(monkeypatch: pytest.MonkeyPatch, search_data: list, fetches: list) -> MagicMock:
    conn = MagicMock()
    conn.search.return_value = ("OK", search_data)
    conn.fetch.side_effect = fetches
    monkeypatch.setattr(mailbox_mod.imaplib, "IMAP4_SSL", lambda host: conn)
    return conn


def test_find_link_filters_alias_and_marks_seen_selectively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The foreign-alias mail must stay UNSEEN for a concurrent waiter; only the
    matching mail is flagged as read."""
    other = _mail_bytes("other+z@gmail.com", f"link: {LINK}")
    mine = _mail_bytes("me+abc@gmail.com", f"link: {LINK}")
    conn = _fake_imap(
        monkeypatch,
        search_data=[b"1 2"],
        fetches=[
            ("OK", [(b"1 (RFC822)", other), b")"]),  # trailing b")" as real imaplib does
            ("OK", [(b"2 (RFC822)", mine), b")"]),
        ],
    )

    link = _mailbox()._find_link("me+abc@gmail.com")

    assert link == LINK
    conn.store.assert_called_once_with(b"2", "+FLAGS", r"\Seen")
    conn.logout.assert_called_once()


def test_find_link_none_when_no_unseen(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _fake_imap(monkeypatch, search_data=[b""], fetches=[])

    assert _mailbox()._find_link("me+abc@gmail.com") is None
    conn.fetch.assert_not_called()
    conn.logout.assert_called_once()


# ---- _extract_link: html part ----------------------------------------------


def test_extract_link_from_html_part() -> None:
    msg = EmailMessage()
    msg["To"] = "me+abc@gmail.com"
    msg.set_content("plain part without links")
    msg.add_alternative(f'<a href="{LINK}">Download</a>', subtype="html")

    link = Mailbox._extract_link(msg)
    assert link is not None
    assert link.startswith("https://artist.bandcamp.com/download/track")
