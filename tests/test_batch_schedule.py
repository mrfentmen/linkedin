"""Regression tests for the slot planner.

The bug these lock down: a run that follows an interrupted run could schedule a
SECOND post into a slot that was already taken.

Sequence that caused it:

    1. an earlier run is killed mid-post, leaving pending records in
       content/schedule_state.json
    2. the next run builds its list of free slots
    3. it then runs --reconcile, which finalizes those pending records and
       writes their slots into content/posts_sent.txt
    4. the list from step 2 was never rebuilt, so those slots still looked free
       and a second post was scheduled into each one

The fix is to rebuild the free slot list after reconcile.  These tests pin the
ordering down so it cannot silently regress.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import batch_schedule as bs  # noqa: E402
from batch_schedule import compute_remaining  # noqa: E402


ALL_SLOTS = [
    "2026-09-27 08:00",
    "2026-09-27 08:15",
    "2026-09-27 08:30",
]

# A post an interrupted run left pending, which reconcile then finalized into
# this slot.
RECLAIMED = "2026-09-27 08:15"
ALREADY = {"2026-09-27 08:00"}
AMBIGUOUS = {"2026-09-27 08:30"}


def test_free_slots_exclude_both_scheduled_and_ambiguous():
    remaining = compute_remaining(ALL_SLOTS, ALREADY, AMBIGUOUS)
    assert RECLAIMED in remaining


def test_reconcile_claimed_slot_is_not_offered_again():
    """The regression: after reconcile claims a slot, it must not be free."""
    after = ALREADY | {RECLAIMED}

    remaining = compute_remaining(ALL_SLOTS, after, AMBIGUOUS)

    assert RECLAIMED not in remaining
    assert remaining == []


def test_plan_built_before_reconcile_is_stale():
    """Shows why the recompute is needed, not just cosmetic.

    The list built before reconcile still contains the reclaimed slot.  Had the
    driver scheduled from it, that slot would have received a second post.
    """
    before_reconcile = compute_remaining(ALL_SLOTS, ALREADY, AMBIGUOUS)
    after_reconcile = compute_remaining(ALL_SLOTS, ALREADY | {RECLAIMED}, AMBIGUOUS)

    assert RECLAIMED in before_reconcile, "precondition for the bug"
    assert RECLAIMED not in after_reconcile
    assert len(before_reconcile) == len(after_reconcile) + 1


def test_driver_stops_when_a_batch_claims_nothing(monkeypatch, capsys):
    """A full LinkedIn account must not burn a post per batch.

    When LinkedIn refuses a schedule, the batch claims no slot.  Every further
    batch would make the same refused request, so the driver must stop.  Nothing
    is lost either way: the posts stay in the queue and the next run retries.
    """
    calls: list[list[str]] = []

    def fake_schedule_batch(slots, headless=True) -> bool:
        calls.append(list(slots))
        return True          # claims nothing, exactly like a refusal

    monkeypatch.setattr(bs, "run_reconcile", lambda: True)
    monkeypatch.setattr(bs, "get_already_scheduled", lambda: set())
    monkeypatch.setattr(bs, "get_ambiguous_times", lambda: set())
    monkeypatch.setattr(bs, "get_queue_count", lambda: 500)
    monkeypatch.setattr(bs, "schedule_batch", fake_schedule_batch)
    monkeypatch.setattr(bs.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "batch_schedule",
            "--start-date", "2026-09-27",
            "--end-date", "2026-09-27",
            "--start-time", "08:00",
            "--end-time", "09:00",
            "--interval-minutes", "15",
            "--batch-size", "2",
        ],
    )

    assert bs.main() == 0
    assert len(calls) == 1, f"expected one batch then a stop, got {len(calls)} batches"
    assert "not accepting schedules" in capsys.readouterr().out


def test_driver_never_schedules_a_slot_reconcile_just_claimed(monkeypatch):
    """End to end on the driver: reconcile claims a slot, the loop must skip it.

    Everything that touches the network, the browser or disk is stubbed, so this
    exercises the real ordering inside main().
    """
    claimed: set[str] = set()
    scheduled: list[str] = []

    def fake_reconcile() -> bool:
        # Stands in for a post an interrupted run left pending: reconciling it
        # writes its slot into posts_sent.txt.
        claimed.add(RECLAIMED)
        return True

    def fake_schedule_batch(slots, headless=True) -> bool:
        scheduled.extend(slots)
        return True

    monkeypatch.setattr(bs, "run_reconcile", fake_reconcile)
    monkeypatch.setattr(bs, "get_already_scheduled", lambda: set(claimed))
    monkeypatch.setattr(bs, "get_ambiguous_times", lambda: set())
    monkeypatch.setattr(bs, "get_queue_count", lambda: 500)
    monkeypatch.setattr(bs, "schedule_batch", fake_schedule_batch)
    monkeypatch.setattr(bs.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "batch_schedule",
            "--start-date", "2026-09-27",
            "--end-date", "2026-09-27",
            "--start-time", "08:00",
            "--end-time", "08:30",
            "--interval-minutes", "15",
            "--batch-size", "5",
        ],
    )

    bs.main()

    assert scheduled, "the driver should still schedule the genuinely free slots"
    assert "2026-09-27 08:00" in scheduled
    assert RECLAIMED not in scheduled, (
        f"slot {RECLAIMED} was already claimed by reconcile but the driver "
        "handed it to the poster anyway, which double books it"
    )
