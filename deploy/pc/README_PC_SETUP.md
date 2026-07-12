# Running on your own laptop — 4 videos/day, catch-up aware

Since your laptop isn't always on at exact times, this uses a smart scheduler
instead of plain cron/Task Scheduler triggers: it checks every 30 minutes
whether a video is "due," and if your laptop was off when a slot's time
passed, it catches that video up automatically once you're back online —
but never more than one every 45 minutes, so a laptop that was off all day
doesn't dump 4 videos back-to-back the moment it wakes up.

## 1. One-time setup (if you haven't already)

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # fill in your API keys
```
Also make sure `client_secret.json` and `token.pickle` (from your earlier
OAuth setup) are in the project root.

## 2. Test the scheduler manually once

```bash
python scheduler.py
```
- If it's not yet past one of today's target times (8am/12pm/4pm/8pm), it'll
  print "Nothing due right now" and exit — that's correct behavior, not a bug.
- If a slot IS due, it'll run the full pipeline right then.

## 3. Set up Task Scheduler to call it automatically

1. Open **Task Scheduler** → **Create Task**
2. General tab: name it `PulseRankd Scheduler Check`, check **"Run whether
   user is logged on or not"**
3. Triggers tab → **New** → set to trigger **Daily**, starting at e.g.
   `12:00 AM` → check **"Repeat task every"** → set to **30 minutes** → for a
   duration of **1 day** (this makes it check every 30 min, all day, every day)
4. Actions tab → **New**:
   - Program: full path to your venv's python, e.g.
     ```
     C:\Users\shaw2\OneDrive\Documents\shorts-automator\venv\Scripts\python.exe
     ```
   - Arguments: `scheduler.py`
   - Start in: `C:\Users\shaw2\OneDrive\Documents\shorts-automator`
5. Conditions tab → uncheck **"Start only if on AC power"** if it's a laptop,
   and check **"Wake the computer to run this task"** if it sleeps

That's it — from now on, Windows checks every 30 minutes, and the scheduler
itself decides whether a video is actually due.

## 4. Uploading your own topic anytime, manually

Two ways:

**Double-click** `upload_my_topic.bat` — or run it from a terminal:
```bash
upload_my_topic.bat "the new iPhone 17 launch" public
```
(the privacy argument is optional, defaults to private)

**Or directly**, if you prefer the terminal:
```bash
python main.py --topic "your topic here" --privacy private
```

A manual run like this doesn't interfere with the scheduler's state — it's
a completely separate one-off, doesn't count toward or against the 4
scheduled slots for the day.

## 5. Changing the times or number of videos/day

Open `scheduler.py`, edit this line near the top:
```python
TARGET_TIMES = ["08:00", "12:00", "16:00", "20:00"]
```
Add/remove/change times freely — 24-hour format, as many as you want per day.

## 6. Checking on it without babysitting

`scheduler_state.json` (auto-created) shows you exactly what ran today and
when. Nothing fancy needed — open it anytime:
```json
{
  "date": "2026-07-09",
  "completed_slots": ["08:00", "12:00"],
  "last_run": "2026-07-09T12:03:41"
}
```
