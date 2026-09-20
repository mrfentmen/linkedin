"""Tests for the read-only scheduled-posts checker.

Two things are pinned down here.

1. Parsing.  LinkedIn renders a list entry as
   "Posting Mon, Sep 21, 2026 at 5:30 PM".  The schedule panel also renders a
   much shorter line, "Posting at Sun, Sep 20, 6:30 PM", for the time you are
   currently picking.  That short line must never be counted as a list entry,
   or every run would invent a phantom post.

2. The scroll bug.  The first version of the checker read the page once, after
   scrolling to the bottom, and reported exactly 200 entries with holes at both
   ends.  That was a rendering window, not the list.  The collector must union
   what it sees at every scroll position.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_scheduled import (  # noqa: E402
    HumanBrowser,
    collect_scheduled_slots,
    parse_linkedin_slots,
)


def _entry(weekday: str, month: str, day: int, time: str) -> str:
    return f"Posting {weekday}, {month} {day}, 2026 at {time}"


def test_parses_a_single_entry_into_24_hour_local_time():
    text = _entry("Mon", "Sep", 21, "5:30 PM")
    assert parse_linkedin_slots(text) == ["2026-09-21 17:30"]


def test_handles_noon_and_midnight():
    assert parse_linkedin_slots(_entry("Tue", "Sep", 22, "12:00 PM")) == ["2026-09-22 12:00"]
    assert parse_linkedin_slots(_entry("Tue", "Sep", 22, "12:15 AM")) == ["2026-09-22 00:15"]


def test_parses_a_run_of_entries_in_order():
    text = "\n".join(
        [
            _entry("Tue", "Sep", 22, "11:00 AM"),
            _entry("Tue", "Sep", 22, "11:15 AM"),
            _entry("Tue", "Sep", 22, "11:30 AM"),
        ]
    )
    assert parse_linkedin_slots(text) == [
        "2026-09-22 11:00",
        "2026-09-22 11:15",
        "2026-09-22 11:30",
    ]


def test_ignores_the_panels_own_short_posting_line():
    # This is the time picker's current value, not a scheduled entry.  It has no
    # weekday and no year, so it must not parse.
    assert parse_linkedin_slots("Posting at Sun, Sep 20, 6:30 PM") == []


def test_ignores_unrelated_text():
    text = "Schedule post\nScheduled (200)\nDate*\nTime*\nConfirm\n"
    assert parse_linkedin_slots(text) == []


class _FakeMouse:
    def __init__(self, page: "_FakePage") -> None:
        self._page = page

    def wheel(self, _x: int, y: int) -> None:
        step = 1 if y > 0 else -1
        self._page.index = max(0, min(len(self._page.windows) - 1, self._page.index + step))


class _FakePage:
    """A page that only ever shows a sliding window of a longer list."""

    def __init__(self, windows: list[str]) -> None:
        self.windows = windows
        self.index = 0
        self.mouse = _FakeMouse(self)

    def inner_text(self, _selector: str) -> str:
        return self.windows[self.index]


def test_collector_unions_a_sliding_window():
    """Each read shows two entries; all six must still be collected."""
    entries = [
        _entry("Mon", "Sep", 21, "8:00 AM"),
        _entry("Mon", "Sep", 21, "8:15 AM"),
        _entry("Mon", "Sep", 21, "8:30 AM"),
        _entry("Mon", "Sep", 21, "8:45 AM"),
        _entry("Mon", "Sep", 21, "9:00 AM"),
        _entry("Mon", "Sep", 21, "9:15 AM"),
    ]
    windows = ["\n".join(entries[i : i + 2]) for i in range(len(entries) - 1)]

    original = HumanBrowser.human_delay
    HumanBrowser.human_delay = staticmethod(lambda *_a, **_k: None)
    try:
        seen, _text = collect_scheduled_slots(_FakePage(windows), step=600)
    finally:
        HumanBrowser.human_delay = original

    assert sorted(seen) == [
        "2026-09-21 08:00",
        "2026-09-21 08:15",
        "2026-09-21 08:30",
        "2026-09-21 08:45",
        "2026-09-21 09:00",
        "2026-09-21 09:15",
    ]
