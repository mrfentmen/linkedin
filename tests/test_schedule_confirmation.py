"""Tests for the schedule confirmation check.

The bug these lock down: the poster treated the Schedule click as the result.
It returned SCHEDULED as soon as the button was clicked, whatever LinkedIn did
with it.  A schedule LinkedIn quietly dropped was still written to
posts_sent.txt, so the post left the queue and never published, and the slot
stayed marked taken forever.  That is how 74 posts went missing.

The fix asks LinkedIn's own "Scheduled (N)" count whether it moved.  Anything
unproven must come back as NOT confirmed, because unconfirmed now means the run
stops instead of a post disappearing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from linkedin_poster import (  # noqa: E402
    SCHEDULED_LABEL_RE,
    SCHEDULED_TAB_SELECTORS,
    _confirm_scheduled_growth,
)


def test_confirm_accepts_a_count_that_moved():
    confirmed, error = _confirm_scheduled_growth(200, 201)
    assert confirmed is True
    assert error == ""


def test_confirm_rejects_an_unchanged_count():
    confirmed, error = _confirm_scheduled_growth(200, 200)
    assert confirmed is False
    assert "no higher than" in error


def test_confirm_rejects_a_count_that_went_down():
    confirmed, error = _confirm_scheduled_growth(200, 199)
    assert confirmed is False
    assert "no higher than" in error


def test_confirm_rejects_a_missing_reading():
    """If the count cannot be read, the schedule is unproven, not assumed."""
    confirmed, error = _confirm_scheduled_growth(200, None)
    assert confirmed is False
    assert "could not read" in error


def test_confirm_rejects_a_missing_baseline():
    confirmed, error = _confirm_scheduled_growth(None, 201)
    assert confirmed is False
    assert "no baseline" in error


def test_label_regex_reads_the_count_from_the_real_label():
    # This exact label was read off the live account.
    assert SCHEDULED_LABEL_RE.search("Scheduled (200)").group(1) == "200"


def test_label_regex_handles_thousands_separators():
    assert SCHEDULED_LABEL_RE.search("Scheduled (1,204)").group(1) == "1,204"


def test_label_regex_ignores_a_label_without_a_count():
    assert SCHEDULED_LABEL_RE.search("Scheduled") is None


def test_tab_selectors_prefer_the_count_label():
    """The first selector must target 'Scheduled (N)', not a bare 'Scheduled'."""
    assert SCHEDULED_TAB_SELECTORS[0] == 'a:has-text("Scheduled (")'
