"""Playwright browser context with storage_state-based cookie persistence.

Why storage_state instead of launch_persistent_context:
    Chrome 130+ on macOS uses App-Bound Encryption for cookies stored in
    Default/Cookies.  Even with channel="chrome", Playwright cannot decrypt
    those encrypted_value blobs — the bot sees an empty cookie jar and hits
    login walls on every run.

    storage_state bypasses this entirely.  Cookies are serialised to a
    plaintext JSON file (storage.json) and loaded via new_context().  No
    Chrome encryption, no SingletonLock conflicts, no profile-version drift.

Flow:
    1. First run (no storage.json): bot opens a fresh browser — you'll see
       login prompts.  Run scripts/pre_login.py once to sign in and export
       cookies.
    2. Subsequent runs: storage.json exists → cookies loaded → bot is
       already logged into LinkedIn + Indeed.
    3. Every __exit__ saves the latest cookies back to storage.json so
       sessions stay fresh across runs.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

try:
    from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
    _HAVE_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    _HAVE_PLAYWRIGHT = False
    Browser = BrowserContext = Page = None  # type: ignore[assignment]
    sync_playwright = None  # type: ignore[assignment]

try:
    from playwright_stealth import stealth_sync
    _HAVE_STEALTH = True
except ImportError:  # pragma: no cover
    _HAVE_STEALTH = False


# Real Chrome 150 UA.  We set this on the context since new_context accepts
# user_agent, unlike launch_persistent_context.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class HumanBrowser:
    """Browser wrapper that persists login cookies via storage_state JSON.

    Usage:
        with HumanBrowser(profile_dir=Path("./browser_profile")) as browser:
            page = browser.new_page()
            page.goto("https://linkedin.com/jobs")
            # ... apply ...
        # cookies auto-saved to browser_profile/storage.json on exit
    """

    def __init__(self, profile_dir: Path, headless: bool = False) -> None:
        if not _HAVE_PLAYWRIGHT:
            raise RuntimeError(
                "Playwright is not installed. Run:\n"
                "  pip install -r requirements.txt && python -m playwright install chromium"
            )
        self.profile_dir = profile_dir
        self.headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._storage_path = profile_dir / "storage.json"

    # ------------------------------------------------------------------
    # context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "HumanBrowser":
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = sync_playwright().start()

        # Launch system Chrome so the UA / TLS fingerprint matches what
        # Indeed / LinkedIn expect from a real browser.  Fall back to
        # Playwright's bundled Chromium if Chrome.app isn't installed.
        try:
            self._browser = self._playwright.chromium.launch(
                channel="chrome",
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    # Prevent Chrome 130+ from using App-Bound Encryption
                    # on new cookies written this session.  Existing
                    # cookies are loaded from storage.json (plaintext),
                    # but any new cookies set by LinkedIn/Indeed during
                    # the run would be re-encrypted if this flag weren't
                    # here — and storage_state export might then capture
                    # encrypted blobs instead of plaintext values.
                    "--disable-features=AppBoundEncryption",
                ],
            )
        except Exception:
            self._browser = self._playwright.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )

        # Load cookies from storage.json if it exists; otherwise start fresh.
        storage_state = str(self._storage_path) if self._storage_path.exists() else None

        self._context = self._browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1440, "height": 900},
            user_agent=DEFAULT_USER_AGENT,
            locale="en-US",
            timezone_id="America/New_York",
        )

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._context:
                # Persist cookies so the next run picks them up.
                self._context.storage_state(path=str(self._storage_path))
                self._context.close()
        finally:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()

    # ------------------------------------------------------------------
    # page helpers
    # ------------------------------------------------------------------

    def new_page(self) -> Page:
        assert self._context is not None, (
            "Use as a context manager: `with HumanBrowser(...) as hb:`"
        )
        page = self._context.new_page()
        if _HAVE_STEALTH:
            try:
                stealth_sync(page)
            except Exception:
                pass
        return page

    # ------------------------------------------------------------------
    # human-like interaction
    # ------------------------------------------------------------------

    @staticmethod
    def human_delay(min_ms: int = 400, max_ms: int = 1200) -> None:
        """Sleep a random amount like a person would."""
        import time
        time.sleep(random.uniform(min_ms / 1000.0, max_ms / 1000.0))

    @staticmethod
    def jittered_click(page, selector: str, *, expect_type: str = "button") -> None:
        """Click an element at a randomized coordinate within it (avoid the dead center)."""
        page.wait_for_selector(selector, state="visible", timeout=10000)
        box = page.locator(selector).bounding_box()
        if box is None:
            page.locator(selector).click()
            HumanBrowser.human_delay()
            return
        x_offset = random.uniform(0.2, 0.8) * box["width"]
        y_offset = random.uniform(0.2, 0.8) * box["height"]
        page.mouse.move(box["x"] + x_offset, box["y"] + y_offset)
        HumanBrowser.human_delay(50, 200)
        page.mouse.click(box["x"] + x_offset, box["y"] + y_offset)
        HumanBrowser.human_delay()

    @staticmethod
    def scroll_jitter(page, pixels: int = 400) -> None:
        """Scroll down a little, with a few intermediate pauses, like a person reading."""
        steps = random.randint(3, 6)
        per = pixels // steps
        for _ in range(steps):
            page.mouse.wheel(0, per + random.randint(-30, 30))
            HumanBrowser.human_delay(100, 350)

    @staticmethod
    def random_idle(min_s: float = 0.5, max_s: float = 1.5) -> None:
        import time
        time.sleep(random.uniform(min_s, max_s))
