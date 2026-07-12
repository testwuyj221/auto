"""
Smart scheduler for 4 videos/day that doesn't require the laptop to be on at
exact times. Designed to be triggered every ~30 minutes by Task Scheduler
(see deploy/pc/README_PC_SETUP.md).

Logic each time this runs:
  1. Look at today's 4 target times (default 8am/12pm/4pm/8pm).
  2. Find target times that have already passed and haven't run yet today.
  3. If one exists AND enough time has passed since the last run (MIN_GAP_MINUTES),
     run the pipeline once and mark that slot done.
  4. Otherwise do nothing and exit — the next scheduled check will pick up
     where this left off.

This means: if your laptop is on at the scheduled times, videos go out right
on schedule. If it was off, missed slots get caught up automatically next
time it's on — but never more than one video per MIN_GAP_MINUTES, so a laptop
that was off all day doesn't dump 4 videos back-to-back the moment it wakes up.
"""
import json
import os
from datetime import datetime, timedelta

import main as pipeline

STATE_FILE = "scheduler_state.json"
TARGET_TIMES = ["08:00", "12:00", "16:00", "20:00"]  # 24h format, edit as you like
MIN_GAP_MINUTES = 45  # minimum spacing between two videos, even when catching up


def _load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"date": None, "completed_slots": [], "last_run": None}


def _save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _reset_if_new_day(state, today_str):
    if state.get("date") != today_str:
        state["date"] = today_str
        state["completed_slots"] = []
    return state


def check_and_run():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    state = _load_state()
    state = _reset_if_new_day(state, today_str)

    # find target slots that are due (time has passed) and not yet done today
    due_slots = []
    for t in TARGET_TIMES:
        if t in state["completed_slots"]:
            continue
        target_dt = datetime.strptime(f"{today_str} {t}", "%Y-%m-%d %H:%M")
        if now >= target_dt:
            due_slots.append(t)

    if not due_slots:
        print(f"[scheduler] Nothing due right now ({now.strftime('%H:%M')}). Next check later.")
        return

    # enforce minimum spacing since the last actual run
    if state.get("last_run"):
        last_run_dt = datetime.fromisoformat(state["last_run"])
        if now - last_run_dt < timedelta(minutes=MIN_GAP_MINUTES):
            wait_left = timedelta(minutes=MIN_GAP_MINUTES) - (now - last_run_dt)
            print(f"[scheduler] Slot(s) due ({due_slots}) but waiting {wait_left} more "
                  f"before next run to keep videos spaced out.")
            return

    # run exactly ONE due slot per check — keeps multiple catch-ups spaced out
    # naturally across subsequent scheduler checks instead of firing together
    slot = due_slots[0]
    print(f"[scheduler] Running catch-up/scheduled video for slot {slot} ({today_str})")

    try:
        privacy = os.environ.get("SHORTS_PRIVACY", "private")
        pipeline.run(manual_topic=None, dry_run=False, privacy=privacy)
        state["completed_slots"].append(slot)
        state["last_run"] = now.isoformat()
        print(f"[scheduler] Slot {slot} completed successfully.")
    except Exception as e:
        print(f"[scheduler] Run for slot {slot} FAILED: {e}")
        # Don't mark as completed — it'll be retried on the next check instead
        # of silently skipping today's video for this slot.
    finally:
        _save_state(state)


if __name__ == "__main__":
    check_and_run()
