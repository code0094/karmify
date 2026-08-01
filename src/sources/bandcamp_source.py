"""Bandcamp music source — anonymous name-your-price ($0) → email → FLAC.

Strategy (desktop context = residential IP, which avoids most Cloudflare pain):
  1. nodriver (antidetect headless Chromium) opens the release page.
  2. Drives the "name your price" widget: amount 0 → download.
  3. Enters the address of the app's built-in mailbox (Gmail + plus-alias).
  4. Bandcamp emails a download link; :class:`Mailbox` reads it (IMAP).
  5. Opens the download page, selects FLAC, downloads the file.

If a CAPTCHA appears: solve via CapSolver when ``captcha_api_key`` is set,
otherwise surface for a manual click in the Electron window (desktop affordance).

The CSS/text selectors below match Bandcamp's current layout and MUST be
re-verified against the live site — this is the brittle part of the flow.
"""

from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus

import structlog

from src.sources.base import MusicSource, SearchResult, SourceError

if TYPE_CHECKING:
    from src.sources.mailbox import Mailbox

logger = structlog.get_logger()


class BandcampSource(MusicSource):
    """Scrapes free/name-your-price Bandcamp releases for lossless downloads."""

    name = "bandcamp"
    quality = "flac"

    def __init__(
        self,
        mailbox: Mailbox,
        mail_address: str,
        *,
        captcha_api_key: str = "",
        nav_timeout: float = 30.0,
        email_timeout: float = 180.0,
    ) -> None:
        if not mail_address:
            raise SourceError("bandcamp_mail_address must be configured")
        self._mailbox = mailbox
        self._mail_address = mail_address
        self._captcha_api_key = captcha_api_key
        self._nav_timeout = nav_timeout
        self._email_timeout = email_timeout

    def _alias(self) -> str:
        """Build a unique plus-alias so each download maps to its own email."""
        local, _, domain = self._mail_address.partition("@")
        return f"{local}+{secrets.token_hex(4)}@{domain}"

    async def _start_browser(self) -> Any:
        # Imported lazily so the app runs without nodriver installed.
        import nodriver as uc

        return await uc.start(headless=True)

    async def search(self, query: str, *, limit: int = 20) -> list[SearchResult]:
        browser = await self._start_browser()
        try:
            url = f"https://bandcamp.com/search?q={quote_plus(query)}&item_type=t"
            page = await browser.get(url)
            await page.sleep(2)

            results: list[SearchResult] = []
            # NOTE: verify selector — Bandcamp search results use `.searchresult .heading a`.
            items = await page.select_all(".searchresult .heading a")
            for el in items[:limit]:
                href = el.attrs.get("href", "").split("?")[0]
                title = (el.text or "").strip()
                if not href or not title:
                    continue
                results.append(
                    SearchResult(
                        source=self.name,
                        title=title,
                        artist="",  # filled from the release page on download
                        download_ref=href,
                        audio_format="flac",  # target format; actual chosen at download
                        extra={"url": href},
                    )
                )
            return results
        except Exception as exc:  # noqa: BLE001 - surface any scraping failure uniformly
            raise SourceError(f"Bandcamp search failed: {exc}") from exc
        finally:
            await self._stop(browser)

    async def download(self, result: SearchResult, dest_dir: Path) -> Path:
        browser = await self._start_browser()
        alias = self._alias()
        try:
            page = await browser.get(result.download_ref)
            await page.sleep(2)

            await self._drive_name_your_price(page)
            await self._enter_email(page, alias)
            await self._handle_captcha(page)

            link = await self._mailbox.wait_for_download_link(
                to_alias=alias, timeout=self._email_timeout
            )

            return await self._download_flac(browser, link, dest_dir)
        except SourceError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SourceError(f"Bandcamp download failed: {exc}") from exc
        finally:
            await self._stop(browser)

    async def _drive_name_your_price(self, page: Any) -> None:
        """Set the name-your-price amount to 0 and proceed to download."""
        # NOTE: selectors to verify on live site.
        buy = await page.find("Buy Now", best_match=True)
        if buy:
            await buy.click()
            await page.sleep(1)
        price_input = await page.select("input#userPrice, input.payment-amount")
        if price_input:
            await price_input.send_keys("0")
            await page.sleep(0.5)
        proceed = await page.find("Download to Your Computer", best_match=True)
        if proceed:
            await proceed.click()
            await page.sleep(1)

    async def _enter_email(self, page: Any, alias: str) -> None:
        """Fill in the email address Bandcamp will send the download link to."""
        email_input = await page.select("input#fan_email_address, input[type=email]")
        if not email_input:
            raise SourceError("Bandcamp email field not found (layout changed?)")
        await email_input.send_keys(alias)
        await page.sleep(0.5)
        submit = await page.find("Check Your Email", best_match=True)
        if submit:
            await submit.click()
        await page.sleep(1)

    async def _handle_captcha(self, page: Any) -> None:
        """Detect a CAPTCHA and either solve it or wait for manual intervention."""
        captcha = await page.select("iframe[src*='recaptcha'], iframe[src*='hcaptcha']")
        if not captcha:
            return
        if self._captcha_api_key:
            # TODO: integrate CapSolver token injection here.
            logger.warning("source.bandcamp.captcha_autosolve_pending")
            raise SourceError("CAPTCHA encountered; CapSolver integration not yet wired")
        logger.warning("source.bandcamp.captcha_manual")
        raise SourceError("CAPTCHA encountered — manual click required in the app window")

    async def _download_flac(self, browser: Any, link: str, dest_dir: Path) -> Path:
        """Open the emailed download page, pick FLAC, and save the file."""
        page = await browser.get(link)
        await page.sleep(2)

        fmt = await page.select("select#format-type, select.format")
        if fmt:
            await fmt.send_keys("FLAC")
            await page.sleep(0.5)

        dest_dir.mkdir(parents=True, exist_ok=True)
        # nodriver downloads land in the browser's download dir; point it at dest_dir.
        # NOTE: verify nodriver's download-path API for the installed version.
        await browser.main_tab.set_download_path(dest_dir)

        dl = await page.find("Download", best_match=True)
        if not dl:
            raise SourceError("Bandcamp download button not found")
        await dl.click()

        return await self._await_file(dest_dir)

    @staticmethod
    async def _await_file(dest_dir: Path, timeout: float = 120.0) -> Path:
        """Wait for a completed (non-temp) audio file to appear in dest_dir."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            candidates = [
                p
                for p in dest_dir.glob("*")
                if p.is_file()
                and p.suffix.lower() in {".flac", ".zip", ".mp3"}
                and not p.name.endswith(".crdownload")
            ]
            if candidates:
                newest = max(candidates, key=lambda p: p.stat().st_mtime)
                logger.info("source.bandcamp.downloaded", path=str(newest))
                return newest
            await asyncio.sleep(2)
        raise SourceError("Bandcamp file did not finish downloading")

    @staticmethod
    async def _stop(browser: Any) -> None:
        try:
            browser.stop()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            logger.debug("source.bandcamp.browser_stop_failed")
