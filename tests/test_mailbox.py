"""Tests for the Bandcamp IMAP mailbox link extraction."""

from email.message import EmailMessage

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
