"""
"Track THIS, not just views" + "winner repeat" system.

Views alone don't tell you if a Short is actually working — what matters is
whether people watch it (vs swipe away) and whether they finish/replay it.
This module:

  1. Records a video_id -> topic/title/emotion/pacing mapping every time we
     upload (record_upload_mapping, called from main.py right after upload).
  2. Pulls real retention data from the YouTube Analytics API for videos in
     that mapping (average view % watched, average view duration, views) —
     this is the closest free-tier proxy to "viewed vs swiped away".
  3. Flags any video whose average_view_percentage crosses WINNER_THRESHOLD
     as a "winner", and — if we haven't already repeated it — re-queues that
     exact concept `WINNER_REPEAT_COUNT` times via
     trend_finder.queue_winner_variations(), tagged so script_generator is
     told to keep the concept but force a different hook/emotion/pacing each
     time. This is the "when one video performs, make 5 variations of it"
     strategy.

All state lives in plain files next to the rest of this repo's logs
(upload_mapping.jsonl, performance_log.jsonl, repeated_winners.txt) so it
survives across runs without needing a database.
"""
import os
import json
from datetime import date

from modules import trend_finder, youtube_uploader

MAPPING_PATH = "upload_mapping.jsonl"
PERFORMANCE_LOG_PATH = "performance_log.jsonl"
REPEATED_WINNERS_PATH = "repeated_winners.txt"

# A Short that retains 50%+ of its duration on average is doing well —
# YouTube's own creator guidance treats ~50% average view percentage as a
# strong Shorts benchmark. Tune this once you have real channel data.
WINNER_THRESHOLD_PCT = 50.0
WINNER_REPEAT_COUNT = 5  # "make 5 variations of that exact idea"

# Only check videos at least this many days old — Shorts retention data needs
# a little time (and enough views) to stabilize, and very fresh uploads will
# just come back as noisy/incomplete.
MIN_AGE_DAYS_BEFORE_CHECK = 2


def record_upload_mapping(video_id, topic_title, video_title, emotion, pacing,
                           is_variation=False, path=MAPPING_PATH):
    """Call this right after a successful upload so we can later look up this
    video's real retention and, if it's a winner, know what topic/concept to repeat."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "video_id": video_id,
            "topic_title": topic_title,
            "video_title": video_title,
            "emotion": emotion,
            "pacing": pacing,
            "is_variation": is_variation,
            "uploaded_date": date.today().isoformat(),
        }) + "\n")


def _load_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _already_checked_ids(log_path=PERFORMANCE_LOG_PATH):
    return {row["video_id"] for row in _load_jsonl(log_path)}


def _already_repeated_topics(path=REPEATED_WINNERS_PATH):
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _mark_repeated(topic_title, path=REPEATED_WINNERS_PATH):
    with open(path, "a", encoding="utf-8") as f:
        f.write(topic_title + "\n")


def _fetch_analytics(video_ids):
    """Returns {video_id: {"views":int, "avg_view_duration_s":float, "avg_view_pct":float}}."""
    if not video_ids:
        return {}
    analytics = youtube_uploader._get_analytics_service()
    resp = analytics.reports().query(
        ids="channel==MINE",
        startDate="2020-01-01",
        endDate=date.today().isoformat(),
        metrics="views,averageViewDuration,averageViewPercentage",
        dimensions="video",
        filters=f"video=={','.join(video_ids)}",
    ).execute()

    results = {}
    for row in resp.get("rows", []):
        vid, views, avg_dur, avg_pct = row
        results[vid] = {
            "views": int(views),
            "avg_view_duration_s": float(avg_dur),
            "avg_view_pct": float(avg_pct),
        }
    return results


def sync_and_find_winners(mapping_path=MAPPING_PATH, log_path=PERFORMANCE_LOG_PATH):
    """
    Pulls fresh retention data for any mapped video that's old enough and not
    yet logged, appends it to performance_log.jsonl, and returns the list of
    NEWLY-discovered winner mapping rows (topic_title, video_title, etc.) so
    main.py can decide to queue variations. Safe to call every run — it's a
    no-op if there's nothing new to check or analytics isn't reachable yet
    (e.g. first run, before any videos exist).
    """
    mappings = _load_jsonl(mapping_path)
    if not mappings:
        return []

    checked_ids = _already_checked_ids(log_path)
    today = date.today()

    due = []
    for row in mappings:
        if row["video_id"] in checked_ids:
            continue
        uploaded = date.fromisoformat(row["uploaded_date"])
        if (today - uploaded).days >= MIN_AGE_DAYS_BEFORE_CHECK:
            due.append(row)

    if not due:
        return []

    try:
        metrics_by_id = _fetch_analytics([r["video_id"] for r in due])
    except Exception as e:
        print(f"[performance_tracker] Couldn't fetch YouTube Analytics (skipping for now): {e}")
        return []

    winners = []
    with open(log_path, "a", encoding="utf-8") as f:
        for row in due:
            metrics = metrics_by_id.get(row["video_id"])
            if metrics is None:
                continue  # not enough data yet from the Analytics API
            entry = {**row, **metrics}
            f.write(json.dumps(entry) + "\n")
            if metrics["avg_view_pct"] >= WINNER_THRESHOLD_PCT:
                winners.append(entry)

    return winners


def queue_winner_repeats(winners, repeat_count=WINNER_REPEAT_COUNT):
    """
    For each newly-found winner not already repeated, push `repeat_count`
    variation slots of that concept to the front of topics_queue.txt.
    Returns the list of topic titles actually queued (for logging).
    """
    already_repeated = _already_repeated_topics()
    queued = []
    for w in winners:
        topic_title = w["topic_title"]
        if topic_title in already_repeated:
            continue
        trend_finder.queue_winner_variations(topic_title, count=repeat_count)
        _mark_repeated(topic_title)
        queued.append(topic_title)
    return queued


def run_tracking_pass():
    """Convenience entry point for main.py: sync performance data, queue
    winner-repeats, and print a short human-readable summary."""
    winners = sync_and_find_winners()
    if not winners:
        print("[performance_tracker] No new performance data / no winners this run.")
        return
    for w in winners:
        print(
            f"[performance_tracker] WINNER: '{w['video_title']}' — "
            f"{w['avg_view_pct']:.1f}% avg watched, {w['views']} views"
        )
    queued = queue_winner_repeats(winners)
    if queued:
        print(f"[performance_tracker] Queued {WINNER_REPEAT_COUNT}x variation slots for: {queued}")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    run_tracking_pass()
