#!/usr/bin/env python3
"""Read-only check: what does LinkedIn actually have scheduled?

This script never posts, never schedules and never clicks a submit control.  The
only things it clicks are the schedule clock and the "Scheduled (N)" tab,
because those only navigate within a view.  It never presses Confirm or Post.

It answers a question the archive cannot: content/posts_sent.txt records what we
*asked* LinkedIn to schedule.  This asks LinkedIn what it *has*.

What it does:
    1. Opens LinkedIn with the saved session.
    2. Opens the schedule panel and reads the "Scheduled (N)" tab label.  That N
       is LinkedIn's own count, printed back verbatim so it can be checked.
    3. Clicks that tab and reads the entries, scrolling until the list stops
       growing.  A lazily rendered list would otherwise be undercounted.
    4. Diffs LinkedIn's list against content/posts_sent.txt, slot by slot, and
       reports exactly which slots the archive claims that LinkedIn does not
       hold, and which LinkedIn holds that the archive never recorded.

Times are compared in the account's local time zone, which is how both sides
store them.  That is not an assumption: the archive slot 2026-09-20 18:30 and
LinkedIn's "Sun, Sep 20, 2026 at 6:30 PM" are the same event.

Usage:
    python3 scripts/check_scheduled.py
    python3 scripts/check_scheduled.py --headless
    python3 scripts/check_scheduled.py --profile-dir path/to/browser_profile
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
# PKG_ROOT for auto_apply, HERE for importing the poster's selectors.
sys.path.insert(0, str(PKG_ROOT))
sys.path.insert(0, str(HERE))

from auto_apply.core.browser import HumanBrowser  # noqa: E402
from auto_apply.core import paths as pathsmod  # noqa: E402

COMPOSE_URL = "https://www.linkedin.com/sharing/compose"
SENT_FILE = PKG_ROOT / "content" / "posts_sent.txt"
OUT_DIR = PKG_ROOT / "logs"

# The composer's clock.  Its <svg> id is stable; the span wrapping it is the
# clickable node, and it is not a <button>.
CLOCK_SELECTORS = [
    "span:has(> svg#clock-medium)",
    "svg#clock-medium",
]
CLOCK_SELECTOR = CLOCK_SELECTORS[0]

# The tab that shows the list, rendered as "Scheduled (200)".
SCHEDULED_TAB_SELECTOR = (
    'a:has-text("Scheduled ("), button:has-text("Scheduled ("), '
    '[role="tab"]:has-text("Scheduled (")'
)
SCHEDULED_LABEL_RE = re.compile(r"scheduled\s*\(\s*([\d,]+)\s*\)", re.I)

# A real list entry, e.g. "Posting Mon, Sep 21, 2026 at 5:30 PM".
# Requires the weekday and the year, so the panel's own short
# "Posting at Sun, Sep 20, 6:30 PM" line cannot match.
LI_ENTRY_RE = re.compile(
    r"Posting\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+"
    r"(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
    r"(?P<day>\d{1,2}),\s+(?P<year>\d{4})\s+at\s+"
    r"(?P<hour>\d{1,2}):(?P<min>\d{2})\s*(?P<ampm>AM|PM)",
    re.I,
)

SLOT_RE = re.compile(r"scheduled_for=(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})")

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_linkedin_slots(text: str) -> list[str]:
    """Pull 'YYYY-MM-DD HH:MM' slots out of the rendered scheduled list."""
    slots: list[str] = []
    for match in LI_ENTRY_RE.finditer(text):
        mon = MONTHS.get(match.group("mon")[:3].lower())
        if mon is None:
            continue
        hour = int(match.group("hour")) % 12
        if match.group("ampm").upper() == "PM":
            hour += 12
        try:
            when = datetime(
                int(match.group("year")), mon, int(match.group("day")), hour,
                int(match.group("min")),
            )
        except ValueError:
            continue
        slots.append(when.strftime("%Y-%m-%d %H:%M"))
    return slots


def archive_slots(only_future: bool = True) -> list[str]:
    """Slots content/posts_sent.txt claims, optionally only still-future ones.

    Slots are stored in the account's local time, the same clock LinkedIn's
    schedule panel shows, so "future" is judged against local time.  Comparing
    them against UTC would call a slot still future for hours after it passed.
    """
    if not SENT_FILE.exists():
        return []
    now = datetime.now()
    out: list[str] = []
    for slot in SLOT_RE.findall(SENT_FILE.read_text(encoding="utf-8", errors="replace")):
        if only_future:
            try:
                if datetime.strptime(slot, "%Y-%m-%d %H:%M") <= now:
                    continue
            except ValueError:
                continue
        out.append(slot)
    return out


def collect_scheduled_slots(page, max_rounds: int = 120, step: int = 600) -> tuple[dict[str, int], str]:
    """Walk the whole list and accumulate every entry seen.

    A long list is virtualised: the DOM keeps only the rows near the viewport,
    so reading the text once gives you a window, not the list.  Earlier this
    read only the final scroll position and produced a fake set of 200 with
    holes at both ends.  So: go back to the top, step down slowly, and union
    what is on screen at every step.

    Returns ({slot: times_seen}, final_text).
    """
    seen: dict[str, int] = {}
    text = ""

    # Back to the top first, in case the view is already part way down.
    for _ in range(12):
        try:
            page.mouse.wheel(0, -4000)
        except Exception:
            break
        HumanBrowser.human_delay(150, 300)

    idle = 0
    for _ in range(max_rounds):
        try:
            text = page.inner_text("body")
        except Exception:
            break

        before = len(seen)
        for slot in parse_linkedin_slots(text):
            seen[slot] = seen.get(slot, 0) + 1

        if len(seen) == before:
            idle += 1
            if idle >= 6:
                break
        else:
            idle = 0

        try:
            page.mouse.wheel(0, step)
        except Exception:
            break
        HumanBrowser.human_delay(250, 500)

    return seen, text


def read_linkedin_count(page) -> tuple[int | None, str]:
    """Open the schedule panel and read LinkedIn's own scheduled count."""
    page.goto(COMPOSE_URL, wait_until="domcontentloaded")
    HumanBrowser.human_delay(2500, 3500)

    clock = page.locator(CLOCK_SELECTOR)
    try:
        clock.first.wait_for(state="visible", timeout=15000)
    except Exception:
        print("Could not find the schedule clock on the compose page.")
        print("The session may have expired, or LinkedIn changed its UI.")
        return None, ""

    clock.first.click()
    HumanBrowser.human_delay(1800, 2600)

    tab = page.locator(SCHEDULED_TAB_SELECTOR)
    if tab.count() == 0:
        print("Opened the schedule panel but found no 'Scheduled' tab.")
        return None, ""

    labels: list[str] = []
    for i in range(min(tab.count(), 6)):
        try:
            labels.append((tab.nth(i).inner_text() or "").strip())
        except Exception:
            continue
    print(f"  candidate 'Scheduled' labels seen: {labels}")

    label = labels[0] if labels else ""
    match = SCHEDULED_LABEL_RE.search(label)
    if not match:
        for candidate in labels:
            match = SCHEDULED_LABEL_RE.search(candidate)
            if match:
                label = candidate
                break
    if not match:
        print(f"Could not read a count from the Scheduled tab (labels: {labels}).")
        return None, label
    return int(match.group(1).replace(",", "")), label


def open_scheduled_list(page) -> tuple[dict[str, int], str]:
    """Click the 'Scheduled (N)' tab and walk the list."""
    tab = page.locator(SCHEDULED_TAB_SELECTOR)
    if tab.count() == 0:
        print("No 'Scheduled' tab to open.")
        return {}, ""
    try:
        tab.first.click()
        HumanBrowser.human_delay(2200, 3000)
    except Exception as exc:
        print(f"Could not open the scheduled list: {exc}")
        return {}, ""
    return collect_scheduled_slots(page)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run with no visible window (default is visible, which is easier to trust).",
    )
    parser.add_argument(
        "--profile-dir",
        default=None,
        help="Override the browser profile directory holding storage.json",
    )
    args = parser.parse_args()

    profile_dir = Path(args.profile_dir) if args.profile_dir else pathsmod.default_browser_profile()
    if not (profile_dir / "storage.json").exists():
        print(f"No session at {profile_dir / 'storage.json'}")
        print("Run scripts/pre_login.py first.")
        return 1

    print("=" * 62)
    print("  LinkedIn scheduled posts — READ ONLY")
    print("=" * 62)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    linkedin_count = None
    linkedin_slots: list[str] = []

    with HumanBrowser(profile_dir=profile_dir, headless=args.headless) as browser:
        page = browser.new_page()

        print(f"\nOpening {COMPOSE_URL} ...")
        linkedin_count, label = read_linkedin_count(page)
        if label:
            print(f"\nScheduled tab label, exactly as read: {label!r}")

        if linkedin_count is not None:
            print("\nOpening the scheduled list and walking it ...")
            seen, text = open_scheduled_list(page)

            panel_path = OUT_DIR / "scheduled_list_dump.txt"
            if text.strip():
                panel_path.write_text(text, encoding="utf-8")
                print(f"Final viewport text saved to {panel_path}")

            linkedin_slots = sorted(seen)
            print(f"Distinct entries collected while scrolling: {len(linkedin_slots)}")
            if linkedin_slots:
                print(f"  earliest: {linkedin_slots[0]}")
                print(f"  latest:   {linkedin_slots[-1]}")
                held = {s: n for s, n in seen.items() if n > 1}
                if held:
                    print(f"  times seen more than once while scrolling: {len(held)}")
                else:
                    print("  every time appeared exactly once while scrolling")

            shot = OUT_DIR / "scheduled_list_check.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
                print(f"Screenshot saved to {shot}")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Cross-check against the archive
    # ------------------------------------------------------------------
    print("\n" + "-" * 62)
    print("Archive cross-check (content/posts_sent.txt)")
    print("-" * 62)

    archive = archive_slots(only_future=True)
    unique_archive = sorted(set(archive))

    print(f"Slots the archive claims that are still in the future: {len(unique_archive)}")
    if linkedin_count is not None:
        print(f"LinkedIn's own scheduled count (tab label):             {linkedin_count}")
    if linkedin_slots:
        print(f"Entries read from LinkedIn's list:                      {len(linkedin_slots)}")
        print(f"  of which distinct times:                              {len(set(linkedin_slots))}")

    if linkedin_slots:
        li_set = set(linkedin_slots)
        ar_set = set(unique_archive)

        missing = sorted(ar_set - li_set)
        extra = sorted(li_set - ar_set)

        print(f"\nClaimed by the archive but NOT on LinkedIn ({len(missing)}):")
        for slot in missing[:40]:
            print(f"  {slot}")
        if len(missing) > 40:
            print(f"  ... and {len(missing) - 40} more")

        print(f"\nOn LinkedIn but never recorded in the archive ({len(extra)}):")
        for slot in extra[:40]:
            print(f"  {slot}")
        if len(extra) > 40:
            print(f"  ... and {len(extra) - 40} more")

        if not missing and not extra:
            print("\n  The archive matches LinkedIn exactly.")

    counts = Counter(archive)
    dupes = {slot: n for slot, n in sorted(counts.items()) if n > 1}
    if dupes:
        print(f"\nSlots the archive claims more than once ({len(dupes)}):")
        for slot, n in dupes.items():
            print(f"  {slot}  x{n}")

    if linkedin_slots:
        li_dupes = {s: n for s, n in Counter(linkedin_slots).items() if n > 1}
        if li_dupes:
            print(f"\nTimes LinkedIn holds more than one post ({len(li_dupes)}):")
            for slot, n in sorted(li_dupes.items()):
                print(f"  {slot}  x{n}")
        else:
            print("\nLinkedIn holds exactly one post at every listed time.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
