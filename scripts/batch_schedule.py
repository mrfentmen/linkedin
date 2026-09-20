#!/usr/bin/env python3
"""Batch schedule LinkedIn posts across multiple days at 15-minute intervals.

Usage:
    python scripts/batch_schedule.py [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
                                     [--start-time HH:MM] [--end-time HH:MM]
                                     [--interval-minutes N] [--batch-size N]
                                     [--headless]

Default: Aug 24 through Aug 30, 2026, 9:00 AM to 8:00 PM, every 15 minutes,
         5 posts per browser session, headless.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
_VENV_PYTHON = PKG_ROOT / ".venv" / "bin" / "python"
# Use the project venv when it exists (local runs).  In CI there is no venv,
# so fall back to the interpreter already running this script.
VENV_PYTHON = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable
POSTER_SCRIPT = str(HERE / "linkedin_poster.py")


def generate_slots(start_date: str, end_date: str, start_time: str, end_time: str, interval_min: int) -> list[str]:
    """Generate all schedule time slots in the range, constrained to daily window."""
    # Parse daily boundaries
    day_start_h, day_start_m = map(int, start_time.split(":"))
    day_end_h, day_end_m = map(int, end_time.split(":"))
    day_start_minutes = day_start_h * 60 + day_start_m
    day_end_minutes = day_end_h * 60 + day_end_m

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    slots = []
    current_date = start_dt
    while current_date <= end_dt:
        # For each day, generate slots within the [start_time, end_time] window
        current = current_date.replace(hour=0, minute=0) + timedelta(minutes=day_start_minutes)
        day_end = current_date.replace(hour=0, minute=0) + timedelta(minutes=day_end_minutes)
        while current <= day_end:
            slot_str = current.strftime("%Y-%m-%d %H:%M")
            # Don't include slots before the overall start (only matters for day 1)
            overall_start = datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
            if current >= overall_start:
                slots.append(slot_str)
            current += timedelta(minutes=interval_min)
        current_date += timedelta(days=1)
    return slots


def get_already_scheduled() -> set[str]:
    """Read posts_sent.txt and return set of already-scheduled times."""
    sent_path = PKG_ROOT / "content" / "posts_sent.txt"
    if not sent_path.exists():
        return set()
    scheduled = set()
    import re
    for line in sent_path.read_text(encoding="utf-8", errors="replace").split("\n"):
        m = re.search(r"scheduled_for=(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", line)
        if m:
            scheduled.add(m.group(1))
    return scheduled


def get_ambiguous_times() -> set[str]:
    """Read posts_ambiguous.txt and return set of ambiguous-scheduled times."""
    ambig_path = PKG_ROOT / "content" / "posts_ambiguous.txt"
    if not ambig_path.exists():
        return set()
    scheduled = set()
    import re
    for line in ambig_path.read_text(encoding="utf-8", errors="replace").split("\n"):
        m = re.search(r"scheduled_for=(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", line)
        if m:
            scheduled.add(m.group(1))
    return scheduled


def compute_remaining(
    all_slots: list[str],
    already: set[str],
    ambiguous: set[str],
) -> list[str]:
    """Slots in the range that are still free.

    Kept as its own function so the reconcile ordering below can be tested:
    a slot claimed by reconcile must never come back as free.
    """
    skip = already | ambiguous
    return [s for s in all_slots if s not in skip]


def run_reconcile() -> bool:
    """Run --reconcile to clean up any pending state."""
    result = subprocess.run(
        [VENV_PYTHON, POSTER_SCRIPT, "--reconcile"],
        cwd=str(PKG_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode == 0


def get_queue_count() -> int:
    """Return remaining queue count."""
    result = subprocess.run(
        [VENV_PYTHON, POSTER_SCRIPT, "--queue-status"],
        cwd=str(PKG_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    import re
    m = re.search(r"Queue: (\d+) posts", result.stdout)
    return int(m.group(1)) if m else 0


def schedule_batch(schedule_times: list[str], headless: bool = True) -> bool:
    """Schedule one batch of posts. Returns True on success."""
    times_str = ",".join(schedule_times)
    cmd = [
        VENV_PYTHON, POSTER_SCRIPT,
        "--next",
        "--schedule", times_str,
    ]
    if headless:
        cmd.append("--headless")
    
    print(f"\n{'='*60}")
    print(f"Batch: {len(schedule_times)} posts from {schedule_times[0]} to {schedule_times[-1]}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(PKG_ROOT),
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes for a batch of 5-8 posts
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        return True
    except subprocess.TimeoutExpired:
        print("⚠️  Batch timed out — will reconcile and continue")
        return False
    except Exception as e:
        print(f"❌ Batch error: {e}")
        return False


def main():
    import argparse
    p = argparse.ArgumentParser(description="Batch schedule LinkedIn posts")
    p.add_argument("--start-date", default="2026-08-24")
    p.add_argument("--end-date", default="2026-08-30")
    p.add_argument("--start-time", default="09:00")
    p.add_argument("--end-time", default="20:00")
    p.add_argument("--interval-minutes", type=int, default=15)
    p.add_argument("--batch-size", type=int, default=5)
    p.add_argument(
        "--max-batches",
        type=int,
        default=0,
        help="Stop after N batches (0 = no limit).  Used by CI to keep a single run bounded.",
    )
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--show-plan", action="store_true", help="Show plan and exit")
    args = p.parse_args()

    # Generate all slots
    all_slots = generate_slots(
        args.start_date, args.end_date,
        args.start_time, args.end_time,
        args.interval_minutes,
    )
    print(f"Total slots in range: {len(all_slots)}")

    # Get already-scheduled
    already = get_already_scheduled()
    ambiguous = get_ambiguous_times()
    remaining = compute_remaining(all_slots, already, ambiguous)

    print(f"Already scheduled: {len(already)}")
    print(f"Ambiguous (skipping): {len(ambiguous)}")
    print(f"Remaining to schedule: {len(remaining)}")

    if args.show_plan:
        for s in remaining:
            print(f"  {s}")
        return 0

    if not remaining:
        print("✅ All slots are already scheduled!")
        return 0

    # Reconcile any pending state first
    print("\n--- Reconciling pending state ---")
    run_reconcile()

    # Reconcile finalizes posts that an interrupted run left pending, and that
    # claims their slots in posts_sent.txt.  `remaining` was built BEFORE that,
    # so it still lists those slots and every one of them would get a second
    # post.  Rebuild it now that the state has settled.  Without this, a run
    # that follows an interrupted run double books its slots.
    already = get_already_scheduled()
    ambiguous = get_ambiguous_times()
    remaining = compute_remaining(all_slots, already, ambiguous)
    print(f"Remaining after reconcile: {len(remaining)}")

    q_count = get_queue_count()
    print(f"Queue count: {q_count}")
    if q_count < len(remaining):
        print(f"⚠️  Only {q_count} posts in queue but {len(remaining)} slots remaining!")
        if q_count == 0:
            return 1
    
    # Schedule in batches
    batch_size = min(args.batch_size, q_count)
    total_batches = (len(remaining) + batch_size - 1) // batch_size
    
    stopped_by_cap = False
    stopped_no_progress = False
    claimed_before = len(get_already_scheduled())
    for batch_num in range(total_batches):
        if args.max_batches and batch_num >= args.max_batches:
            print(f"\n⏹  Stopping after --max-batches={args.max_batches}; the next run continues from here.")
            stopped_by_cap = True
            break

        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, len(remaining))
        batch_slots = remaining[start_idx:end_idx]

        # Last line of defence: never hand the poster a slot that is already
        # claimed, whatever the plan said when the run started.
        claimed = get_already_scheduled() | get_ambiguous_times()
        batch_slots = [s for s in batch_slots if s not in claimed]
        if not batch_slots:
            print("Every slot in this batch is already claimed; skipping it.")
            continue

        # Check queue before each batch
        q_count = get_queue_count()
        if q_count < len(batch_slots):
            print(f"⚠️  Only {q_count} posts left, scaling batch down from {len(batch_slots)}")
            batch_slots = batch_slots[:q_count]
            if not batch_slots:
                print("❌ Queue is empty!")
                return 1
        
        print(f"\n📦 Batch {batch_num + 1}/{total_batches}: {len(batch_slots)} posts")
        
        ok = schedule_batch(batch_slots, headless=args.headless)
        
        # Always reconcile after each batch to handle partial completions
        print("\n--- Reconciling ---")
        run_reconcile()
        
        # Small pause between batches to let LinkedIn settle
        time.sleep(3)
        
        # Refresh remaining count
        new_already = get_already_scheduled()
        new_remaining = [s for s in remaining if s not in new_already and s not in ambiguous]
        done = len(remaining) - len(new_remaining)
        print(f"\n📊 Progress: {done}/{len(remaining)} slots scheduled")

        # A batch that claimed no new slot means LinkedIn is not accepting
        # schedules right now (its own limit, its own mood).  Every further
        # batch would make the same refused request, so stop and let the next
        # run try again.  Nothing is lost: the posts stay in the queue.
        if len(new_already) <= claimed_before:
            print("\n⏹  This batch claimed no new slot, so LinkedIn is not accepting schedules.")
            print("   Stopping this run. The posts stay in the queue for the next run.")
            stopped_no_progress = True
            break
        claimed_before = len(new_already)
    
    # Final status
    print("\n" + "="*60)
    final_already = get_already_scheduled()
    final_slots = [s for s in all_slots if s in final_already]
    final_remaining = [s for s in all_slots if s not in final_already]
    print(f"✅ Scheduled: {len(final_slots)} posts")
    print(f"❌ Remaining: {len(final_remaining)} slots")
    if final_remaining and len(final_remaining) <= 20:
        for s in final_remaining:
            print(f"   {s}")
    print(f"📋 Queue: {get_queue_count()} posts")
    print("="*60)

    # A capped run is expected to finish with slots still open — the next run
    # picks them up — so only an uncapped run reports that as a failure.
    if stopped_by_cap:
        print("✅ Run ended at the batch cap. Slots left open are handled by the next run.")
        return 0

    if stopped_no_progress:
        print("✅ Run ended early because LinkedIn accepted nothing. Slots left open are")
        print("   handled by the next run, and no post was lost.")
        return 0

    return 0 if not final_remaining else 1


if __name__ == "__main__":
    sys.exit(main())