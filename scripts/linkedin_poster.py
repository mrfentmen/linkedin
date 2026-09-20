#!/usr/bin/env python3
"""Post to LinkedIn via browser automation — no API keys, no OAuth, no company page.

Uses the same Playwright + storage.json cookie setup as the job applier.
Run pre_login.py first if you haven't already (so storage.json has your
LinkedIn session).

Usage:
    # Post a single message directly from the command line:
    python scripts/linkedin_poster.py "My post content here"

    # Post the next item from the queue file (for cron / scheduling):
    python scripts/linkedin_poster.py --next

    # Dry-run: open LinkedIn but don't click Post (test selectors):
    python scripts/linkedin_poster.py --dry-run "Test post"

    # Schedule a post for later using LinkedIn's native scheduling:
    python scripts/linkedin_poster.py --schedule "2026-07-15 09:00" "My future post"
    python scripts/linkedin_poster.py --schedule "2026-07-15 09:00" --next

    # Schedule multiple posts in one browser session:
    python scripts/linkedin_poster.py --next --schedule "2026-07-15 09:00,2026-07-15 12:00,2026-07-15 15:00"

Queue file format (posts_queue.txt):
    Posts are separated by a line containing exactly "---".

    Post one content here.
    Multiple lines are fine.
    ---
    Post two content here.
    Also multi-line.
    ---

When --next is used, the first post is consumed, posted, and appended to
posts_sent.txt.  The remaining posts stay in posts_queue.txt.

Scheduling (macOS):
    # Edit your crontab:  crontab -e
    # Add this line to post every weekday at 9 AM (headless — no Chrome window):
    0 9 * * 1-5  cd /Users/dtaxk/Desktop/jobs/auto-apply && source .venv/bin/activate && python scripts/linkedin_poster.py --headless --next >> logs/linkedin_poster.log 2>&1

    # Or every day at 10 AM:
    0 10 * * *  cd /Users/dtaxk/Desktop/jobs/auto-apply && source .venv/bin/activate && python scripts/linkedin_poster.py --headless --next >> logs/linkedin_poster.log 2>&1
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the package is importable.
HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
sys.path.insert(0, str(PKG_ROOT))

from auto_apply.core.browser import HumanBrowser
from auto_apply.core import paths as pathsmod
from auto_apply.core.schedule_state import (
    PostResult,
    PostStatus,
    ExclusiveRunLock,
    ScheduleState,
    ScheduleStateCorrupt,
    ScheduleRunLocked,
)


# ---------------------------------------------------------------------------
# file paths
# ---------------------------------------------------------------------------

QUEUE_FILE = PKG_ROOT / "content" / "posts_queue.txt"
SENT_FILE = PKG_ROOT / "content" / "posts_sent.txt"
AMBIGUOUS_FILE = PKG_ROOT / "content" / "posts_ambiguous.txt"
SCHEDULE_STATE_FILE = PKG_ROOT / "content" / "schedule_state.json"
SCHEDULE_LOCK_FILE = PKG_ROOT / "content" / "schedule_run.lock"
LOG_DIR = PKG_ROOT / "logs"
LOG_FILE = LOG_DIR / "linkedin_poster.log"

# LinkedIn's post composer character limit.
LINKEDIN_CHAR_LIMIT = 3000


# ---------------------------------------------------------------------------
# LinkedIn UI selectors (ordered by preference; first match wins)
# ---------------------------------------------------------------------------

# The clickable area that opens the post composer on the feed page.
# LinkedIn uses a <div> with aria-label="Start a post" (confirmed July 2026).
POST_TRIGGER_SELECTORS = [
    'div[aria-label="Start a post"]',
    'a[href*="/preload/sharebox/"]',
    'a:has-text("Start a post")',
    'button[aria-label="Start a post"]',
    'button[aria-label*="Start a post" i]',
    'div.share-box-feed-entry__wrapper a',
    '.share-box-feed-entry__trigger',
]

# The text editor inside the post modal.  LinkedIn uses a contenteditable
# div.ql-editor.  Must click INTO it after the modal opens.
EDITOR_SELECTORS = [
    # Current composer markup: the placeholder is a <p> inside the
    # contenteditable root (the <p> itself may not be editable).
    '[contenteditable="true"]:has(> p[data-placeholder="Share your thoughts ..."])',
    '[contenteditable="true"]:has(> p[data-placeholder^="Share your thoughts"])',
    'p[data-placeholder="Share your thoughts ..."][contenteditable="true"]',
    'p[data-placeholder^="Share your thoughts"][contenteditable="true"]',
    'div.ql-editor[contenteditable="true"]',
    'div[aria-label="Text editor for creating content"]',
    'div[role="textbox"][contenteditable="true"]',
    'div[role="textbox"][aria-label*="Text editor" i]',
    'div.share-creation-state__container div[role="textbox"]',
    'div[contenteditable="true"]',
]

# The submit button inside the modal (for immediate posts).
SUBMIT_SELECTORS = [
    'button:has-text("Post")',
    'button[aria-label="Post"]',
    'button.share-actions__primary-action',
    'div[role="dialog"] button:has-text("Post")',
    '.share-box-footer button.artdeco-button--primary',
]

# LinkedIn's native scheduling UI (clock icon → date/time panel → Confirm).
# Composer was rebuilt with a new panel (Aug 2026): clicking the clock anchor
# `a[aria-label="Scheduled"]` opens an inline date/time panel with
#   input[data-testid="date-picker-input"]   value like 8/23/2026
#   input[data-testid="time-picker-input"]   value like 8:15 AM
# and a final button labeled "Confirm".  Legacy selectors are kept as
# fallbacks for older composer versions.
SCHEDULE_CLOCK_SELECTORS = [
    # Current composer markup: a span wraps <svg id="clock-medium">.
    # The generated class names are unstable, so use the semantic icon id.
    'span:has(> svg#clock-medium)',
    'button:has(svg#clock-medium)',
    'svg#clock-medium',
    # Older variants use a <use> node or data-test-icon instead.
    'button:has(svg use[href="#clock-medium"])',
    'button:has(svg[data-test-icon="clock-medium"])',
    'svg[data-test-icon="clock-medium"]',
    'a[aria-label="Scheduled"]',
    'button[aria-label="Schedule post"]',
    'button:has-text("Scheduled")',
    'button[aria-label*="Scheduled" i]',
    'a:has-text("Scheduled")',
]

# Text fallbacks for the clock button, tried after the icon selectors.
SCHEDULE_CLOCK_TEXT_FALLBACKS = [
    'button:has-text("Scheduled")',
    'button[aria-label*="Scheduled" i]',
    'a:has-text("Scheduled")',
]

# The schedule panel's list tab, rendered as "Scheduled (200)".  The label is
# LinkedIn's own count of scheduled posts, which makes it the only evidence
# available in the browser that a schedule click was actually accepted.
SCHEDULED_TAB_SELECTORS = [
    'a:has-text("Scheduled (")',
    'button:has-text("Scheduled (")',
    '[role="tab"]:has-text("Scheduled (")',
    'a[aria-label="Scheduled"]',
]
SCHEDULED_LABEL_RE = re.compile(r"scheduled\s*\(\s*([\d,]+)\s*\)", re.I)
SCHEDULE_DATE_SELECTORS = [
    'input[data-testid="date-picker-input"]',
    'input#share-post__scheduled-date',
]
SCHEDULE_TIME_SELECTORS = [
    'input[data-testid="time-picker-input"]',
    'input#share-post__scheduled-time',
]
SCHEDULE_TIME_PICKER_BUTTON_SELECTORS = [
    'button[data-testid="time-picker-clock-button"]',
]
SCHEDULE_TIME_OPTION_SELECTORS = [
    'div[data-testid="time-picker-option"]',
    '[role="option"]',
    'li[data-testid*="time" i]',
    'button[data-testid*="time" i]',
]
SCHEDULE_CALENDAR_BUTTON_SELECTORS = [
    'button[data-testid="date-picker-input-calendar-button"]',
]
SCHEDULE_DAY_SELECTOR_TMPL = 'button[aria-label*="{month} {day}, {year}" i]'
SCHEDULE_NEXT_MONTH_SELECTORS = [
    'button[aria-label="Next month"]',
    'button[aria-label*="Next month" i]',
]
SCHEDULE_PREV_MONTH_SELECTORS = [
    'button[aria-label="Previous month"]',
    'button[aria-label*="Previous month" i]',
]
SCHEDULE_NEXT_SELECTORS = [
    'button[aria-label="Next"]',
]
SCHEDULE_CONFIRM_SELECTORS = [
    # Current composer control is a generated-class span containing exactly
    # "Confirm". Keep this list Confirm-only so Schedule cannot be clicked
    # before the date/time panel has been accepted.
    'span:text-is("Confirm")',
    'div[data-testid="dialog-content"] button:has-text("Confirm")',
]
SCHEDULE_FINAL_SELECTORS = [
    # After Confirm, the composer footer exposes the separate final action.
    'span:text-is("Schedule")',
    'button:has-text("Schedule")',
    'button:has-text("Schedule post")',
    '[role="button"]:has-text("Schedule")',
    'button[aria-label*="Schedule" i]',
    '[role="button"][aria-label*="Schedule" i]',
]
SCHEDULE_PANEL_SELECTORS = [
    'div[data-sdui-screen="com.linkedin.sdui.flagshipnav.sharing.ShareSchedulePostPicker"]',
    'div[data-testid="dialog-content"]',
]

# Success indicator after a post is scheduled.
SUCCESS_TOAST_SELECTORS = [
    'div.artdeco-toast-item:has-text("scheduled")',
    'div.artdeco-toast-item:has-text("Post scheduled")',
    'div.artdeco-toast-item:has-text("Scheduled")',
    'div.artdeco-toast-item:has(svg[data-test-icon="check-circle"])',
    'div.artdeco-toast-item:has(svg[data-test-icon="checkmark"])',
    'div.artdeco-toast-item',
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _find_first(page, selectors: list[str], timeout_ms: int = 20000):
    """Return (locator, selector_string) for the first visible match, or (None, None).

    Returns the *winning selector* alongside the locator so callers can use
    it with jittered_click (which needs a selector string, not a locator).
    """
    per_selector = max(500, timeout_ms // max(1, len(selectors)))
    for sel in selectors:
        try:
            loc = page.locator(sel)
            # Fast path: skip selectors that match zero DOM elements.
            if loc.count() == 0:
                continue
            loc.wait_for(state="visible", timeout=per_selector)
            if loc.count() > 0:
                return loc.first, sel
        except Exception:
            continue
    return None, None


def _click_exact_visible_text(page, text: str) -> bool:
    """Click a visible semantic control whose rendered text exactly matches."""
    try:
        hit = page.evaluate("""(target) => {
            const candidates = Array.from(document.querySelectorAll(
                'button, a, [role="button"], [role="link"], span'
            ));
            for (const node of candidates) {
                if ((node.innerText || '').trim() !== target) continue;
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                if (style.display === 'none' || style.visibility === 'hidden' ||
                    rect.width === 0 || rect.height === 0) continue;
                const control = node.closest('button, a, [role="button"], [role="link"]') || node;
                const controlRect = control.getBoundingClientRect();
                if (controlRect.width === 0 || controlRect.height === 0) continue;
                return {
                    x: Math.round(controlRect.left + controlRect.width / 2),
                    y: Math.round(controlRect.top + controlRect.height / 2),
                    tag: control.tagName,
                    aria: control.getAttribute('aria-label') || ''
                };
            }
            return null;
        }""", text)
        if not hit:
            return False
        _log(f"   Schedule control found by visible text ({hit['tag']} {hit['aria']})")
        page.mouse.click(hit['x'], hit['y'])
        return True
    except Exception as exc:
        _log(f"   Visible-text Schedule fallback failed: {exc}")
        return False


def _log(msg: str) -> None:
    """Print with timestamp to stdout and append to log file."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# queue operations
# ---------------------------------------------------------------------------

def read_queue() -> list[str]:
    """Read posts_queue.txt, split by '---' lines.  Returns list of posts."""
    if not QUEUE_FILE.exists():
        return []
    raw = QUEUE_FILE.read_text(encoding="utf-8")
    posts = [block.strip() for block in raw.split("\n---\n")]
    return [p for p in posts if p]  # drop empty blocks


def write_queue(posts: list[str]) -> None:
    """Write remaining posts back to the queue file atomically."""
    _atomic_write_queue(posts)


def _history_has(record_id: str, path: Path) -> bool:
    """Return whether a record id was already written to a history file."""
    if not path.exists():
        return False
    marker = f"record_id={record_id}"
    return marker in path.read_text(encoding="utf-8", errors="replace")


def move_to_sent(post: str, schedule_time: str | None, record_id: str) -> None:
    """Append a successfully scheduled/posted message to history once."""
    if _history_has(record_id, SENT_FILE):
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    target = f"scheduled_for={schedule_time}\n" if schedule_time else ""
    entry = f"[{ts}]\nrecord_id={record_id}\n{target}{post}\n---\n"
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def move_to_ambiguous(post: str, schedule_time: str | None, error: str, record_id: str) -> None:
    """Keep uncertain outcomes out of the retryable queue, once."""
    if _history_has(record_id, AMBIGUOUS_FILE):
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = (
        f"[{ts}]\nrecord_id={record_id}\nstatus=ambiguous\n"
        f"scheduled_for={schedule_time or ''}\n"
        f"error={error[:500]}\n{post}\n---\n"
    )
    with open(AMBIGUOUS_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def _atomic_write_queue(posts: list[str]) -> None:
    """Replace the queue atomically so an interruption cannot truncate it."""
    import os
    import tempfile
    content = "\n---\n".join(posts)
    fd, tmp_name = tempfile.mkstemp(prefix=".posts_queue.", dir=str(QUEUE_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, QUEUE_FILE)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# schedule helper
# ---------------------------------------------------------------------------

def _fill_schedule_input(page, input_locator, value: str) -> bool:
    """Fill a date/time text input and submit it (select-all → type → Enter)."""
    try:
        input_locator.wait_for(state="visible", timeout=10000)
        try:
            input_locator.click(timeout=6000)
        except Exception:
            # Floating overlay may block the click; dismiss and focus directly.
            try:
                page.keyboard.press("Escape")
                HumanBrowser.human_delay(300, 600)
            except Exception:
                pass
            input_locator.focus()
        HumanBrowser.human_delay(200, 400)
        # Select all, then type over the selection.  The modifier is platform
        # specific: Command (Meta) on macOS, Control everywhere else.
        # Playwright does not raise on the wrong modifier, it silently does
        # nothing, so the platform has to be detected instead of caught.
        # Without this, a Linux run appends to the existing date (giving
        # "9/20/20269/27/2026") and the verification below always fails.
        select_all = "Meta+A" if sys.platform == "darwin" else "Control+A"
        page.keyboard.press(select_all)
        HumanBrowser.human_delay(100, 250)
        input_locator.type(value, delay=30)
        HumanBrowser.human_delay(300, 600)
        page.keyboard.press("Enter")
        HumanBrowser.human_delay(400, 800)
        current = (input_locator.input_value() or "").strip()
        # LinkedIn's inputs normalize whitespace (e.g. "10:00 AM" → "10:00AM")
        # and sometimes add leading zeros; compare with all whitespace removed.
        norm = lambda s: "".join(s.lower().split())
        return norm(current) == norm(value)
    except Exception:
        return False


def _schedule_post(page, schedule_time: str) -> bool:
    """Use LinkedIn's native scheduling UI to queue a post for later.

    New-composer flow: click clock icon → fill date → fill time → Confirm.
    schedule_time format: "YYYY-MM-DD HH:MM" (e.g. "2026-07-15 09:00").
    """
    try:
        schedule_dt = datetime.strptime(schedule_time.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        _log(f"❌ Invalid schedule time '{schedule_time}'. Use format: YYYY-MM-DD HH:MM")
        return False

    date_str = f"{schedule_dt.month}/{schedule_dt.day}/{schedule_dt.year}"   # 8/23/2026
    time_str = schedule_dt.strftime("%I:%M %p").lstrip("0")                 # "10:00 AM"

    _log(f"Scheduling post for {schedule_dt.strftime('%B %d, %Y at %I:%M %p')}…")

    # 1. Click the clock/schedule icon to open the schedule panel.
    #    The composer footer (which holds the clock) renders LATE and at
    #    unpredictable times.  _find_first's fast path gives up the moment
    #    a selector has zero matches (which is exactly what happens before
    #    the footer paints), so instead WAIT for the clock properly with
    #    wait_for_selector, then fall back to a raw-JS scan for the exact
    #    icon the user provided (`svg[data-test-icon="clock-medium"]`).
    import time as _t
    clock, clock_sel = None, None
    for sel in SCHEDULE_CLOCK_SELECTORS:
        try:
            page.wait_for_selector(sel, state="visible", timeout=6000)
            clock, clock_sel = page.locator(sel).first, sel
            _log(f"   Clock button found via {sel}")
            break
        except Exception:
            continue
    if clock is None:
        # Raw-JS scan: ANY element wrapping the clock-medium icon.
        try:
            hit = page.evaluate("""() => {
                const icons = document.querySelectorAll('svg[data-test-icon="clock-medium"], svg use[href="#clock-medium"]');
                for (const svg of icons) {
                    const el = svg.closest('button, a, [role="button"]') || svg.parentElement;
                    if (!el) continue;
                    const r = el.getBoundingClientRect();
                    const vis = r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
                    if (!vis) continue;
                    const er = el.getBoundingClientRect();
                    return {x: Math.round(er.x + er.width/2), y: Math.round(er.y + er.height/2)};
                }
                return null;
            }""")
            if hit:
                _log(f"   Clock icon found via JS scan at ({hit['x']},{hit['y']})")
                page.mouse.click(hit["x"], hit["y"])
                clock = True
        except Exception as e:
            _log(f"   JS clock scan failed: {e}")
    if clock is None:
        _log("❌ Could not find schedule/clock button.")
        page.screenshot(path=str(LOG_DIR / "clock_btn_missing.png"))
        return False
    if clock_sel is not None:
        HumanBrowser.jittered_click(page, clock_sel)
    HumanBrowser.human_delay(250, 500)

    # 2. Wait for the schedule panel, then select the date via the calendar.
    #    Same fix: wait_for_selector (not the give-up-on-zero fast path).
    panel, _ = None, None
    for sel in SCHEDULE_PANEL_SELECTORS:
        try:
            page.wait_for_selector(sel, state="visible", timeout=8000)
            panel = page.locator(sel)
            break
        except Exception:
            continue
    if panel is None:
        page.screenshot(path=str(LOG_DIR / "schedule_panel_not_found.png"))
        return False
    if panel is None:
        _log("❌ Could not find schedule panel after clicking the clock.")
        page.screenshot(path=str(LOG_DIR / "schedule_panel_not_found.png"))
        return False

    # 2b. Select the exact requested date. Prefer the rendered date input;
    # LinkedIn sometimes omits the current day button from the calendar DOM
    # after several same-day scheduling actions.
    date_input, date_input_sel = _find_first(page, SCHEDULE_DATE_SELECTORS, timeout_ms=5000)
    date_selected = False
    if date_input is not None:
        date_selected = _fill_schedule_input(page, date_input, date_str)
        if date_selected:
            _log(f"   Date control: entered {date_str}")
            HumanBrowser.human_delay(150, 300)

    if not date_selected:
        cal_btn, cal_sel = _find_first(page, SCHEDULE_CALENDAR_BUTTON_SELECTORS, timeout_ms=10000)
        if cal_btn is None:
            _log("❌ Could not find calendar popup button.")
            page.screenshot(path=str(LOG_DIR / "schedule_calendar_btn_missing.png"))
            return False
        HumanBrowser.jittered_click(page, cal_sel)
        HumanBrowser.human_delay(150, 300)

    target = (schedule_dt.strftime("%B"), schedule_dt.day, schedule_dt.year)
    day_btn = None
    day_sel = None
    if date_selected:
        day_btn, day_sel = True, None
    for _ in range(13) if not date_selected else range(0):
        candidate_sel = SCHEDULE_DAY_SELECTOR_TMPL.format(
            month=target[0], day=target[1], year=target[2]
        )
        day_btn, day_sel = _find_first(page, [candidate_sel], timeout_ms=2500)
        if day_btn is not None:
            break
        nav_sel = (
            SCHEDULE_NEXT_MONTH_SELECTORS[0]
            if schedule_dt > datetime.now()
            else SCHEDULE_PREV_MONTH_SELECTORS[0]
        )
        nav = page.locator(nav_sel).first
        if nav.count() == 0 or not nav.is_visible():
            _log(f"❌ Calendar cannot reach {target[0]} {target[1]}, {target[2]}.")
            return False
        HumanBrowser.jittered_click(page, nav_sel)
        HumanBrowser.human_delay(100, 250)

    if day_btn is None or (day_sel is None and not date_selected):
        _log(f"❌ Could not find calendar day for {target[0]} {target[1]}, {target[2]}.")
        page.screenshot(path=str(LOG_DIR / "calendar_day_not_found.png"))
        return False
    if not date_selected:
        _log(f"   Date control: selecting {target[0]} {target[1]}, {target[2]}")
        HumanBrowser.jittered_click(page, day_sel)
        HumanBrowser.human_delay(150, 300)

    # 3. Open the time control and select the exact requested time.
    clock_btn, clock_btn_sel = _find_first(
        page, SCHEDULE_TIME_PICKER_BUTTON_SELECTORS, timeout_ms=15000
    )
    if clock_btn is None:
        _log("❌ Could not find time picker clock button after selecting the date.")
        page.screenshot(path=str(LOG_DIR / "schedule_time_btn_missing.png"))
        return False
    _log(f"   Time control: opening and selecting {time_str}")
    HumanBrowser.jittered_click(page, clock_btn_sel)
    HumanBrowser.human_delay(150, 300)

    option = None
    option_sel = None
    for option_base in SCHEDULE_TIME_OPTION_SELECTORS:
        candidate = f'{option_base}:text-is("{time_str}")'
        option, option_sel = _find_first(page, [candidate], timeout_ms=2500)
        if option is not None:
            break

    if option is not None and option_sel is not None:
        HumanBrowser.jittered_click(page, option_sel)
        HumanBrowser.human_delay(150, 300)
    else:
        # Some LinkedIn accounts render the picker as a combobox rather than
        # a list of option divs. Use the visible input as a fallback and then
        # accept the highlighted value with the keyboard.
        time_input, time_input_sel = _find_first(page, SCHEDULE_TIME_SELECTORS, timeout_ms=5000)
        if time_input is None:
            _log(f"❌ Time option not found for {time_str!r}.")
            page.screenshot(path=str(LOG_DIR / "schedule_time_failed.png"))
            return False
        try:
            time_input.click(timeout=6000)
            time_input.fill("")
            time_input.type(time_str, delay=40)
            HumanBrowser.human_delay(250, 500)
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            HumanBrowser.human_delay(150, 300)
            current_time = (time_input.input_value() or "").strip()
            if "".join(current_time.lower().split()) != "".join(time_str.lower().split()):
                _log(f"❌ Time input did not accept {time_str!r}; got {current_time!r}.")
                page.screenshot(path=str(LOG_DIR / "schedule_time_failed.png"))
                return False
        except Exception as exc:
            _log(f"❌ Could not select time {time_str!r}: {exc}")
            page.screenshot(path=str(LOG_DIR / "schedule_time_failed.png"))
            return False

    # 4. Confirm the date/time selection. This is deliberately Confirm-only.
    confirm, confirm_sel = _find_first(page, SCHEDULE_CONFIRM_SELECTORS, timeout_ms=15000)
    if confirm is None:
        _log("❌ Could not find Confirm after selecting date and time.")
        page.screenshot(path=str(LOG_DIR / "schedule_confirm_missing.png"))
        return False
    _log("   Confirmation control: clicking Confirm")
    HumanBrowser.jittered_click(page, confirm_sel)
    HumanBrowser.human_delay(250, 500)

    # 5. Submit the scheduled post with the separate footer Schedule action.
    # After Confirm, LinkedIn rebuilds the footer asynchronously. Retry with
    # progressive waits so we catch it even when rendering is slow.
    import time as _time
    final_btn = None
    final_sel = None
    for attempt in range(4):
        wait = 500 + attempt * 1200
        HumanBrowser.human_delay(wait // 2, wait)
        final_btn, final_sel = _find_first(page, SCHEDULE_FINAL_SELECTORS, timeout_ms=5000)
        if final_btn is not None and final_sel is not None:
            break
        if _click_exact_visible_text(page, "Schedule"):
            final_btn, final_sel = True, None
            break
        if attempt < 3:
            _log(f"   Schedule button not ready yet (attempt {attempt+1}), retrying…")
    if final_btn is not None:
        if final_sel is not None:
            _log("   Submission control: clicking Schedule")
            HumanBrowser.jittered_click(page, final_sel)
        else:
            _log("   Submission control: clicked Schedule via visible text")
    else:
        _log("❌ Confirm succeeded, but the final Schedule button was not found after 4 attempts.")
        page.screenshot(path=str(LOG_DIR / "schedule_submit_missing.png"))
        return False

    try:
        page.wait_for_selector(
            'div[data-testid="dialog-content"]', state="detached", timeout=8000
        )
    except Exception:
        _log("⚠️ Schedule panel did not detach cleanly after Schedule; post may still have been scheduled.")

    return True


def _read_scheduled_count(page) -> int | None:
    """Read LinkedIn's own count of scheduled posts, or None if unreadable.

    Opens the composer, clicks the schedule clock, and reads the
    "Scheduled (N)" tab label.  This is the same read scripts/check_scheduled.py
    performs, and it is the only in-browser evidence that LinkedIn accepted a
    schedule.  Returns None rather than guessing when the label cannot be read.
    """
    try:
        page.goto("https://www.linkedin.com/sharing/compose", wait_until="domcontentloaded")
        HumanBrowser.human_delay(2000, 3200)

        clock, clock_sel = _find_first(page, SCHEDULE_CLOCK_SELECTORS, timeout_ms=15000)
        if clock is None:
            _log("⚠️ Could not open the schedule panel to read the scheduled count.")
            return None
        HumanBrowser.jittered_click(page, clock_sel)
        HumanBrowser.human_delay(1500, 2400)

        tabs, tab_sel = _find_first(page, SCHEDULED_TAB_SELECTORS, timeout_ms=8000)
        if tabs is None or tab_sel is None:
            _log("⚠️ Could not find the 'Scheduled (N)' tab to read the count.")
            return None

        label = (tabs.inner_text() or "").strip()
        match = SCHEDULED_LABEL_RE.search(label)
        if not match:
            _log(f"⚠️ Scheduled tab label did not contain a count: {label!r}")
            return None
        return int(match.group(1).replace(",", ""))
    except Exception as exc:
        _log(f"⚠️ Error reading the scheduled count: {type(exc).__name__}")
        return None


def _confirm_scheduled_growth(previous: int | None, observed: int | None) -> tuple[bool, str]:
    """Decide whether a post we just scheduled is really on LinkedIn.

    LinkedIn's "Scheduled (N)" label is the account's own count.  A schedule
    that LinkedIn accepted makes it go up.  This is the check that was missing:
    the poster used to return SCHEDULED as soon as the Schedule button was
    clicked, whatever LinkedIn did with it, so a rejected schedule still got
    written to posts_sent.txt and its post left the queue forever.

    Returns (confirmed, error_message).  Anything unproven is NOT confirmed.
    """
    if observed is None:
        return False, "could not read LinkedIn's scheduled count, so the schedule is unconfirmed"
    if previous is None:
        return False, "no baseline scheduled count, so the schedule is unconfirmed"
    if observed <= previous:
        return False, (
            f"LinkedIn's scheduled count is {observed}, no higher than {previous} "
            "before this post, so it was probably not accepted"
        )
    return True, ""


def _wait_for_success_indicator(page, timeout_ms: int = 4000) -> bool:
    """Wait for LinkedIn's success toast after scheduling a post.

    Returns True only if a fresh success toast is detected and dismissed.
    """
    try:
        toast, _ = _find_first(page, SUCCESS_TOAST_SELECTORS, timeout_ms=timeout_ms)
        if toast is not None:
            # Verify the toast actually indicates success, not an error.
            toast_text = (toast.text_content() or "").strip()
            if "scheduled" in toast_text.lower() or "success" in toast_text.lower():
                _log("✅ LinkedIn confirmed the post was scheduled (success toast detected).")
                # Try to dismiss the toast so it does not block the next "Start a post" button.
                try:
                    # Look for a dismiss button inside the toast.
                    dismiss = toast.locator('button[aria-label*="Dismiss" i], button[aria-label*="Close" i], button.artdeco-toast-item__dismiss').first
                    if dismiss.count() > 0:
                        dismiss.click()
                    else:
                        toast.click()
                    # Wait for the toast to fully disappear before continuing.
                    toast.wait_for(state="detached", timeout=5000)
                except Exception:
                    pass
                return True
            else:
                _log(f"⚠️  Toast detected but text does not indicate success: {toast_text[:100]}")
    except Exception:
        pass
    _log("⚠️ Could not detect LinkedIn success toast (post may still have gone through).")
    return False


def _reset_to_feed(page) -> None:
    """Navigate to a fresh composer page and wait for it to settle.

    Despite the name this lands on /sharing/compose, not the feed, so the
    next post starts from a composer that is already open.
    """
    if _page_closed(page):
        return
    try:
        # Close native dialogs and overlays before navigating. LinkedIn can
        # leave a dialog mounted after a failed schedule transition, which
        # otherwise intercepts the next Start a post click.
        for _ in range(5):
            try:
                page.keyboard.press("Escape")
                HumanBrowser.human_delay(250, 450)
            except Exception:
                break
        # Navigate twice to force a clean DOM reload — stale dialogs can
        # survive a single goto if the page already matches the URL.
        page.goto("about:blank", wait_until="domcontentloaded")
        HumanBrowser.human_delay(200, 400)
        page.goto("https://www.linkedin.com/sharing/compose", wait_until="domcontentloaded")
        HumanBrowser.human_delay(1200, 1800)
        # Dismiss any post-navigation dialogs that may have appeared.
        _dismiss_overlays(page)
    except Exception:
        pass


def _page_closed(page) -> bool:
    """True when the browser page is gone. Guards every later interaction."""
    try:
        return page is None or page.is_closed()
    except Exception:
        return True


def _editor_is_open(page) -> bool:
    """True when a visible composer text editor is on the page.

    This is the guard for anything destructive. Every control that
    _dismiss_overlays clicks (modal backdrop, Close, Discard, Escape) also
    exists while a composer is open, so without this check the helper
    throws away the very editor we are about to fill.
    """
    if _page_closed(page):
        return False
    try:
        return page.locator('div[contenteditable="true"]:visible').count() > 0
    except Exception:
        return False


def _safe_screenshot(page, name: str) -> None:
    """Diagnostic screenshot that never raises if the page has closed."""
    if _page_closed(page):
        return
    try:
        page.screenshot(path=str(LOG_DIR / name))
    except Exception:
        pass


def _dismiss_overlays(page) -> None:
    """Dismiss leftover dialogs, but never an open composer.

    Regression guard: on the /sharing/compose route the editor is already
    rendered, and the backdrop plus Close/Discard/Escape controls handled
    below belong to that composer. Running this first used to dismiss it,
    bounce the page to /feed/?shareActive=true, and sometimes close the tab
    outright, which surfaced as "TargetClosedError: Mouse.wheel" on the next
    interaction.
    """
    if _page_closed(page) or _editor_is_open(page):
        return
    try:
        # LinkedIn's overlay backdrop often has a semi-transparent dismiss
        # layer. Click the backdrop to close before using Escape.
        try:
            backdrop = page.locator('div.artdeco-modal-overlay, div.artdeco-modal__dismiss')
            if backdrop.count() > 0 and backdrop.first.is_visible():
                backdrop.first.click(timeout=3000)
                HumanBrowser.human_delay(250, 500)
        except Exception:
            pass
        # Also check for explicitly dismissable dialogs.
        for _ in range(5):
            if _page_closed(page) or _editor_is_open(page):
                return
            try:
                dismiss_btn = page.locator(
                    'button[aria-label*="Dismiss" i], button[aria-label*="Close" i], '
                    'div.artdeco-modal__actionbar button:has-text("Discard"), '
                    'button:has-text("Discard")'
                ).first
                if dismiss_btn.count() > 0 and dismiss_btn.is_visible():
                    dismiss_btn.click(timeout=3000)
                    HumanBrowser.human_delay(250, 500)
                    continue
            except Exception:
                pass
            page.keyboard.press("Escape")
            HumanBrowser.human_delay(250, 450)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# post
# ---------------------------------------------------------------------------

def _compose_one_post(page, content: str, *, dry_run: bool = False, schedule_time: str | None = None) -> PostStatus:
    """Compose and schedule/post a single message within an already-open page.

    Returns a PostStatus.  A missing confirmation after the Schedule click
    is AMBIGUOUS and must not be retried automatically.
    """
    # 1. Open the composer.
    #
    # Order matters here. The /sharing/compose route renders the editor
    # directly, so the editor is looked for FIRST and only a page without one
    # falls through to the dismiss-then-click-a-trigger path. Previously
    # _dismiss_overlays ran unconditionally first, which closed the composer
    # on this route before it could ever be filled.
    if _page_closed(page):
        _log("❌ Browser page was already closed before composing.")
        return PostStatus.FAILED

    if not _editor_is_open(page) and "sharing/compose" in page.url:
        # The composer is client-rendered, so give it time before concluding
        # it is missing. A slow load must not look like a broken page.
        try:
            page.wait_for_selector(
                'div[contenteditable="true"]', state="visible", timeout=20000
            )
        except Exception:
            pass

    if not _editor_is_open(page):
        _dismiss_overlays(page)
        if _page_closed(page):
            _log("❌ Browser page closed while dismissing overlays.")
            return PostStatus.FAILED

        trigger = None
        trigger_sel = None
        trigger, trigger_sel = _find_first(page, POST_TRIGGER_SELECTORS, timeout_ms=20000)
        if trigger is None:
            # Sometimes the feed needs a scroll to render the post box.
            try:
                page.mouse.wheel(0, -200)
            except Exception as exc:
                _log(f"❌ Page went away while looking for the post box: {type(exc).__name__}")
                return PostStatus.FAILED
            HumanBrowser.human_delay(500, 1000)
            trigger, trigger_sel = _find_first(page, POST_TRIGGER_SELECTORS, timeout_ms=15000)

        if trigger is None:
            _log("❌ Could not find 'Start a post' button. LinkedIn may have changed its UI.")
            _safe_screenshot(page, "post_trigger_not_found.png")
            return PostStatus.FAILED

        HumanBrowser.jittered_click(page, trigger_sel)
        HumanBrowser.human_delay(500, 900)

    # 2. Wait for the sharebox modal to appear, then find the text editor.
    # LinkedIn's post composer: first try the dedicated share container, then
    # fall back to a visible dialog (excluding hidden video.js modals that
    # resolve to 5+ hidden elements and cause false timeouts).
    try:
        page.wait_for_selector('div.share-creation-state__container', state="visible", timeout=15000)
    except Exception:
        try:
            page.wait_for_selector('div[role="dialog"]:not([aria-hidden="true"]):not(.vjs-error-display):not(.vjs-hidden)', state="visible", timeout=10000)
        except Exception:
            # Last resort: wait for any contenteditable editor to appear.
            page.wait_for_selector('div[contenteditable="true"][role="textbox"]', state="visible", timeout=10000)

    editor, _ = _find_first(page, EDITOR_SELECTORS, timeout_ms=20000)
    if editor is None:
        _log("❌ Could not find post text editor. LinkedIn may have changed its UI.")
        _safe_screenshot(page, "editor_not_found.png")
        return PostStatus.FAILED

    # 3. Fill the post content.
    try:
        editor.click(timeout=8000)
    except Exception:
        # A floating overlay (e.g. LinkedIn's "Comment settings" popover)
        # sometimes blocks pointer events over the editor.  Dismiss it and
        # focus the editor programmatically instead.
        try:
            page.keyboard.press("Escape")
            HumanBrowser.human_delay(300, 600)
        except Exception:
            pass
        editor.focus()
    # LinkedIn's editor is contenteditable. fill() is much faster and more
    # reliable than type() for long posts, ensuring hashtags at the end
    # are not dropped due to typing timeouts. Do it immediately after focus
    # so long queued posts do not spend human-delay time being inserted.
    editor.fill(content)
    # Playwright fill() dispatches the input events LinkedIn needs. LinkedIn
    # may rebuild the contenteditable node immediately afterward, so do not
    # issue another locator action against it here.

    # Give LinkedIn's composer a short render tick to enable its controls.
    HumanBrowser.human_delay(50, 120)

    if dry_run:
        _log(f"✅ DRY RUN — post composed but NOT submitted. Content preview:\n    {content[:120]}…")
        _safe_screenshot(page, "dry_run_preview.png")
        return PostStatus.DRY_RUN

    # 4. Schedule or post immediately.
    if schedule_time:
        ok = _schedule_post(page, schedule_time)
        if not ok:
            _safe_screenshot(page, "schedule_failed.png")
            return PostStatus.FAILED
    else:
        submit, submit_sel = _find_first(page, SUBMIT_SELECTORS, timeout_ms=15000)
        if submit is None:
            _log("❌ Could not find 'Post' button. LinkedIn may have changed its UI.")
            _safe_screenshot(page, "submit_not_found.png")
            return PostStatus.FAILED

        HumanBrowser.jittered_click(page, submit_sel)
        HumanBrowser.human_delay(2000, 4000)

    # 5. Wait for the modal to close or the post to appear in the feed.
    #    (Scheduled posts already waited inside _schedule_post for the
    #    schedule panel to detach, so skip the long wait here.)
    if not schedule_time:
        try:
            page.wait_for_selector(
                'div[role="dialog"]',
                state="detached",
                timeout=20000,
            )
        except Exception:
            _log("⚠️  Post modal did not detach cleanly — post may still have gone through.")

    # 6. Check LinkedIn's success indicator when available. LinkedIn often
    # accepts the Schedule click but leaves the composer mounted and emits no
    # toast (especially in this browser profile). The final Schedule button
    # click above is the authoritative action; the toast is only diagnostic.
    _wait_for_success_indicator(page)

    HumanBrowser.human_delay(300, 700)
    return PostStatus.SCHEDULED if schedule_time else PostStatus.POSTED


def post_to_linkedin(contents: list[str], *, dry_run: bool = False, headless: bool = False, schedule_times: list[str] | None = None, session_limit: int = 10, profile_dir: Path | None = None, state_path: Path | None = None) -> list[PostResult]:
    """Open LinkedIn once and schedule/post multiple messages in one tab.

    Set headless=True for cron/automated runs (no visible Chrome window).
    Set schedule_times to a list of "YYYY-MM-DD HH:MM" strings to use
    LinkedIn's native scheduling instead of posting immediately.
    Returns a list of durable PostResult values.  The browser is restarted
    between bounded chunks so a dead session does not invalidate the whole run.

    profile_dir overrides the browser profile directory (used by parallel
    workers so each process gets its own storage.json copy and they never
    race writing the shared session file).  state_path overrides the durable
    journal path (one file per worker for the same reason).
    """
    if schedule_times is None:
        schedule_times = [None] * len(contents)

    if len(contents) != len(schedule_times):
        _log("❌ Number of posts does not match number of schedule times.")
        return [PostResult(PostStatus.FAILED, c, t, "schedule length mismatch") for c, t in zip(contents, schedule_times)]

    if session_limit < 1:
        raise ValueError("session_limit must be at least 1")

    if profile_dir is None:
        cfg = pathsmod.user_config()
        if cfg.exists():
            import yaml
            config = yaml.safe_load(cfg.read_text(encoding="utf-8"))
            paths_cfg = config.get("paths", {})
            profile_dir = Path(paths_cfg.get("browser_profile") or pathsmod.default_browser_profile())
        else:
            profile_dir = pathsmod.default_browser_profile()

    if not profile_dir.is_absolute():
        profile_dir = pathsmod.package_root() / profile_dir

    storage_path = profile_dir / "storage.json"
    if not storage_path.exists():
        error = "storage.json not found. Run scripts/pre_login.py first to sign into LinkedIn."
        _log(f"❌ {error}")
        return [PostResult(PostStatus.FAILED, c, t, error) for c, t in zip(contents, schedule_times)]

    _log(f"Opening LinkedIn {'(DRY RUN — will not click Post)' if dry_run else ''}{' (headless)' if headless else ''}…")

    results: list[PostResult] = []
    state = None if dry_run else ScheduleState(state_path or SCHEDULE_STATE_FILE)
    if state:
        state.recover_in_progress()

    for chunk_start in range(0, len(contents), session_limit):
        chunk_end = min(chunk_start + session_limit, len(contents))
        chunk = list(zip(contents[chunk_start:chunk_end], schedule_times[chunk_start:chunk_end]))
        _log(f"Starting browser chunk {chunk_start + 1}-{chunk_end} of {len(contents)}")
        browser = None
        page = None
        processed_in_chunk = 0
        try:
            browser = HumanBrowser(profile_dir=profile_dir, headless=headless)
            browser.__enter__()
            page = browser.new_page()
            page.goto("https://www.linkedin.com/sharing/compose", wait_until="domcontentloaded")
            HumanBrowser.human_delay(400, 800)
            if "login" in page.url.lower() or "authwall" in page.url.lower() or "checkpoint" in page.url.lower():
                error = "Redirected to login — storage.json session expired"
                _log(f"❌ {error}")
                for content, schedule_time in chunk:
                    result = PostResult(PostStatus.FAILED, content, schedule_time, error)
                    if state:
                        state.record(result)
                    results.append(result)
                processed_in_chunk = len(chunk)
                continue

            # Baseline for the confirmation check: how many posts does LinkedIn
            # say are scheduled right now?
            confirmed_count = _read_scheduled_count(page)
            _log(f"   LinkedIn reports {confirmed_count} scheduled posts at the start of this chunk")

            for local_idx, (content, schedule_time) in enumerate(chunk, start=1):
                existing = state.get(PostResult(PostStatus.IN_PROGRESS, content, schedule_time)) if state else None
                if existing and existing.get("status") in {
                    PostStatus.SCHEDULED.value,
                    PostStatus.POSTED.value,
                    PostStatus.AMBIGUOUS.value,
                }:
                    _log(f"⏭️ Skipping terminal checkpoint for chunk item {chunk_start + local_idx}")
                    results.append(PostResult(PostStatus(existing["status"]), content, schedule_time, existing.get("error", "")))
                    processed_in_chunk += 1
                    continue

                if not content.strip():
                    result = PostResult(PostStatus.FAILED, content, schedule_time, "empty content")
                elif len(content) > LINKEDIN_CHAR_LIMIT:
                    result = PostResult(PostStatus.FAILED, content, schedule_time, f"{len(content)} chars exceeds {LINKEDIN_CHAR_LIMIT}")
                else:
                    if state:
                        state.record(PostResult(PostStatus.IN_PROGRESS, content, schedule_time))
                    try:
                        status = _compose_one_post(page, content, dry_run=dry_run, schedule_time=schedule_time)
                        error = "" if status != PostStatus.AMBIGUOUS else "Schedule action completed without reliable confirmation"
                        # The Schedule click is a request, not a result.  Ask
                        # LinkedIn whether the count actually moved before this
                        # post is recorded as sent.  Unconfirmed means AMBIGUOUS,
                        # which stops the run instead of silently dropping a post.
                        if schedule_time and status == PostStatus.SCHEDULED:
                            observed = _read_scheduled_count(page)
                            confirmed, error = _confirm_scheduled_growth(confirmed_count, observed)
                            if confirmed:
                                confirmed_count = observed
                            else:
                                _log(f"⚠️ Unconfirmed schedule for {schedule_time}: {error}")
                                status = PostStatus.AMBIGUOUS
                        result = PostResult(status, content, schedule_time, error)
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        _log(f"❌ Exception while posting: {error}")
                        # Timeout errors during composer opening mean we never
                        # touched the post — mark as FAILED so it stays retryable.
                        # Actual scheduling exceptions (after Confirm/Schedule)
                        # must stay AMBIGUOUS because LinkedIn may have accepted.
                        exc_type = type(exc).__name__
                        if "Timeout" in exc_type or "timeout" in error.lower():
                            result = PostResult(PostStatus.FAILED, content, schedule_time, error)
                        else:
                            result = PostResult(PostStatus.AMBIGUOUS, content, schedule_time, error)

                if state:
                    state.record(result)
                results.append(result)
                processed_in_chunk += 1
                is_last_item = (chunk_start + local_idx) == len(contents)
                if result.ok or result.status == PostStatus.DRY_RUN:
                    _log(f"✅ {result.status.value} for {schedule_time or 'now'} ({len(content)} chars)")
                elif result.status == PostStatus.AMBIGUOUS:
                    _log(f"⚠️ Ambiguous outcome for {schedule_time or 'now'}; stopping this run")
                    return results
                else:
                    _log("❌ Failed post; will reset composer before continuing")
                # Navigate to a fresh composer between posts so the schedule
                # panel / composer state can never leak into the next post.
                if not is_last_item:
                    _reset_to_feed(page)
        except Exception as exc:
            error = f"Browser chunk failed: {type(exc).__name__}: {exc}"
            _log(f"❌ {error}")
            for content, schedule_time in chunk[processed_in_chunk:]:
                result = PostResult(PostStatus.AMBIGUOUS, content, schedule_time, error)
                if state:
                    state.record(result)
                results.append(result)
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.__exit__(None, None, None)
                except Exception:
                    pass

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="linkedin_poster",
        description="Post to LinkedIn via browser automation (no API keys needed).",
    )
    p.add_argument(
        "content", nargs="?", default=None,
        help="Post text.  If omitted, use --next to read from the queue.",
    )
    p.add_argument(
        "--next", action="store_true",
        help="Post the next item from posts_queue.txt (moves it to posts_sent.txt).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Open LinkedIn and compose the post but DO NOT click Post.",
    )
    p.add_argument(
        "--schedule", metavar="DATETIME", default=None,
        help='Schedule post(s) for later using LinkedIn native scheduling. Format: "YYYY-MM-DD HH:MM" or comma-separated list for multiple posts (e.g. "2026-07-15 09:00,2026-07-15 12:00").',
    )
    p.add_argument(
        "--headless", action="store_true",
        help="Run in headless mode (no visible Chrome window). Use for cron/scheduling.",
    )
    p.add_argument(
        "--queue-status", action="store_true",
        help="Show how many posts are in the queue and exit.",
    )
    p.add_argument(
        "--reconcile", action="store_true",
        help="Finalize pending scheduled/ambiguous state records without opening LinkedIn.",
    )
    p.add_argument(
        "--queue-file", metavar="PATH", default=None,
        help="Override the queue file path (for parallel workers).",
    )
    p.add_argument(
        "--sent-file", metavar="PATH", default=None,
        help="Override the sent-history file path (for parallel workers).",
    )
    p.add_argument(
        "--ambiguous-file", metavar="PATH", default=None,
        help="Override the ambiguous-history file path (for parallel workers).",
    )
    p.add_argument(
        "--state-path", metavar="PATH", default=None,
        help="Override the durable state journal path (for parallel workers).",
    )
    p.add_argument(
        "--lock-file", metavar="PATH", default=None,
        help="Override the run lock file path (for parallel workers).",
    )
    p.add_argument(
        "--profile-dir", metavar="PATH", default=None,
        help="Override the browser profile directory (for parallel workers).",
    )
    p.add_argument(
        "--log-file", metavar="PATH", default=None,
        help="Override the log file path (for parallel workers).",
    )

    args = p.parse_args()

    global QUEUE_FILE, SENT_FILE, AMBIGUOUS_FILE, SCHEDULE_STATE_FILE, SCHEDULE_LOCK_FILE, LOG_FILE
    if args.queue_file:
        QUEUE_FILE = Path(args.queue_file)
    if args.sent_file:
        SENT_FILE = Path(args.sent_file)
    if args.ambiguous_file:
        AMBIGUOUS_FILE = Path(args.ambiguous_file)
    if args.state_path:
        SCHEDULE_STATE_FILE = Path(args.state_path)
    if args.lock_file:
        SCHEDULE_LOCK_FILE = Path(args.lock_file)
    if args.log_file:
        LOG_FILE = Path(args.log_file)
    profile_dir = Path(args.profile_dir) if args.profile_dir else None

    if args.queue_status:
        posts = read_queue()
        print(f"Queue: {len(posts)} posts waiting in {QUEUE_FILE}")
        if posts:
            print(f"Next post preview: {posts[0][:100]}…")
        return 0

    if args.reconcile:
        return _reconcile_pending_state()

    # Parse schedule times.
    schedule_times = None
    if args.schedule:
        schedule_times = [s.strip() for s in args.schedule.split(",") if s.strip()]

    # Determine content(s).
    contents = []
    if args.next:
        posts = read_queue()
        if not posts:
            _log("❌ Queue is empty. Add posts to posts_queue.txt (separated by --- lines).")
            return 1
        if schedule_times:
            # Read as many posts as we have schedule times.
            if len(posts) < len(schedule_times):
                _log(f"❌ Not enough posts in queue. Need {len(schedule_times)}, have {len(posts)}.")
                return 1
            contents = posts[:len(schedule_times)]
            _log(f"Consuming next {len(contents)} posts from queue ({len(posts)} total)…")
        else:
            # Single post mode.
            contents = [posts[0]]
            _log(f"Consuming next post from queue ({len(posts)} total)…")
    elif args.content:
        contents = [args.content]
    else:
        print("Error: provide post text as an argument or use --next to read from queue.")
        print("Usage: python scripts/linkedin_poster.py 'Your post here'")
        print("       python scripts/linkedin_poster.py --next")
        return 2

    # Checkpoint state before touching queue/history.  Dry runs never mutate
    # the queue or history; they only exercise selectors and screenshots.
    try:
        if args.next and not args.dry_run:
            # Hold the lock across browser work AND finalization so a second
            # process cannot schedule the same queue entries concurrently.
            with ExclusiveRunLock(SCHEDULE_LOCK_FILE):
                results = post_to_linkedin(
                    contents,
                    dry_run=False,
                    headless=args.headless,
                    schedule_times=schedule_times,
                    profile_dir=profile_dir,
                )
                return _finalize_cli_results(posts, results)

        results = post_to_linkedin(
            contents,
            dry_run=args.dry_run,
            headless=args.headless,
            schedule_times=schedule_times,
            profile_dir=profile_dir,
        )
    except (ScheduleStateCorrupt, ScheduleRunLocked) as exc:
        _log(f"❌ {exc}")
        return 4

    return 0 if all(
        result.status in {PostStatus.SCHEDULED, PostStatus.POSTED, PostStatus.DRY_RUN}
        for result in results
    ) else 1


def _remove_terminal_content(posts: list[str], results: list[PostResult]) -> tuple[list[str], int]:
    """Remove one queue occurrence for each terminal result by exact content."""
    remaining = list(posts)
    removed = 0
    for result in results:
        if result.status not in {PostStatus.SCHEDULED, PostStatus.POSTED, PostStatus.AMBIGUOUS}:
            continue
        try:
            remaining.remove(result.content)
        except ValueError:
            # The queue may already have been finalized before an interruption.
            # That is safe and idempotent; do not remove a different post.
            continue
        removed += 1
    return remaining, removed


def _reconcile_pending_state() -> int:
    """Finalize terminal journal records left behind by an interrupted run."""
    try:
        state = ScheduleState(SCHEDULE_STATE_FILE)
        recovered = state.recover_in_progress()
    except ScheduleStateCorrupt as exc:
        _log(f"❌ {exc}")
        return 4

    pending_records = [
        record for record in state.records.values()
        if record.get("status") in {
            PostStatus.SCHEDULED.value,
            PostStatus.POSTED.value,
            PostStatus.AMBIGUOUS.value,
        }
        and not record.get("finalized")
    ]
    results = [
        PostResult(
            PostStatus(record["status"]),
            record.get("content", ""),
            record.get("schedule_time"),
            record.get("error", ""),
        )
        for record in pending_records
    ]
    posts = read_queue()
    for result in results:
        if result.status in {PostStatus.SCHEDULED, PostStatus.POSTED}:
            move_to_sent(result.content, result.schedule_time, result.record_id)
        else:
            move_to_ambiguous(result.content, result.schedule_time, result.error, result.record_id)
        state.mark_finalized(result)
    remaining, removed = _remove_terminal_content(posts, results)
    if removed:
        write_queue(remaining)
    _log(f"Reconciled {len(results)} pending records ({recovered} interrupted) and removed {removed} matching queue posts; {len(remaining)} remain.")
    return 0


def _finalize_cli_results(posts: list[str], results: list[PostResult]) -> int:
    """Idempotently finalize terminal outcomes and mutate the queue once."""
    try:
        state = ScheduleState(SCHEDULE_STATE_FILE)
    except ScheduleStateCorrupt as exc:
        _log(f"❌ {exc}")
        return 4

    successful_count = 0
    ambiguous_count = 0
    failed_count = 0
    terminal_results: list[PostResult] = []
    for result in results:
        if result.status in {PostStatus.SCHEDULED, PostStatus.POSTED}:
            successful_count += 1
            terminal_results.append(result)
            move_to_sent(result.content, result.schedule_time, result.record_id)
            state.mark_finalized(result)
        elif result.status == PostStatus.AMBIGUOUS:
            ambiguous_count += 1
            terminal_results.append(result)
            move_to_ambiguous(result.content, result.schedule_time, result.error, result.record_id)
            state.mark_finalized(result)
        else:
            failed_count += 1

    remaining, removed = _remove_terminal_content(posts, terminal_results)
    if removed:
        write_queue(remaining)
    _log(
        f"Finalized {successful_count} successful, "
        f"{ambiguous_count} ambiguous, {failed_count} failed; "
        f"removed {removed} matching posts; {len(remaining)} remain in queue."
    )
    return 0 if failed_count == 0 and ambiguous_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
