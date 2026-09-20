#!/usr/bin/env python3
"""One-time LinkedIn login helper — sign in once, save the session cookies.

Run this on a machine with a real display, before the first scheduled run and
whenever the session expires:

    cd ~/Desktop/jobs/linkedin
    python3 scripts/pre_login.py

What it does:
    1. Opens a visible Chrome window on LinkedIn's login page.
    2. Waits for you to sign in and press Enter.
    3. Verifies the session by loading the feed.
    4. Writes the cookies to browser_profile/storage.json.

That storage.json is the credential the scheduled runs use.  Only LinkedIn is
touched, so the exported file carries no Google or Indeed cookies.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the package is importable from the repo root.
HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
sys.path.insert(0, str(PKG_ROOT))

from auto_apply.core.browser import HumanBrowser
from auto_apply.core import paths as pathsmod


LOGIN_URL = "https://www.linkedin.com/login"
CHECK_URL = "https://www.linkedin.com/feed/"


def main() -> int:
    profile_dir = pathsmod.default_browser_profile()
    storage_path = profile_dir / "storage.json"

    print("=" * 60)
    print("  linkedin — one-time login helper")
    print("=" * 60)
    print()
    print(f"Session will be saved to:  {storage_path}")
    print()

    if storage_path.exists():
        print("storage.json already exists. Running this overwrites it.")
        print()

    print("A Chrome window will open:")
    print("  1. Sign in to LinkedIn")
    print("  2. Solve any CAPTCHA that appears")
    print("  3. Wait until your feed loads")
    print("  4. Come back to THIS terminal and press Enter")
    print()

    input("Press Enter to open Chrome and start... ")

    with HumanBrowser(profile_dir=profile_dir, headless=False) as browser:
        page = browser.new_page()

        print(f"\nOpening LinkedIn ({LOGIN_URL})...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        HumanBrowser.human_delay(1000, 2000)

        print("Sign in to LinkedIn in the Chrome window.")
        print("When your feed is visible, press Enter here...")
        input()

        try:
            page.goto(CHECK_URL, wait_until="domcontentloaded", timeout=20000)
            HumanBrowser.human_delay(1000, 2000)
            current = page.url
            if "login" in current.lower() or "signin" in current.lower():
                print(f"  Still on a login page ({current}). You may not be signed in.")
                print("  The file is still written — re-run this script to fix it.")
            else:
                print(f"  LinkedIn session looks active ({current[:70]}...)")
        except Exception as exc:
            print(f"  Could not verify the LinkedIn session: {exc}")

        page.close()

    if not storage_path.exists():
        print("\nNo storage.json was written. Nothing to do.")
        return 1

    print()
    print("=" * 60)
    print(f"  Session saved to {storage_path}")
    print(f"  Size: {storage_path.stat().st_size} bytes")
    print()
    print("  Next: trim it, then store it as the repo secret:")
    print("     python3 scripts/trim_session.py browser_profile/storage.json")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
