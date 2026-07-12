"""
Finds trending topics to make Shorts about.

Two free sources, combined:
1. YouTube Data API - "mostPopular" videos (chart=mostPopular) -> real titles
   currently getting traction on YouTube itself.
2. Google Trends (official public RSS feed, free) - realtime/daily trending
   search terms, which often predate YouTube coverage.

Both are free. YouTube API has a 10,000 unit/day quota; this call costs ~100 units.
"""
import os
import requests
import xml.etree.ElementTree as ET

YOUTUBE_API_KEY = ""

# --- Topic queue -------------------------------------------------------
# topics_queue.txt: one topic per line, edit freely (blank lines / lines
# starting with # are ignored). Each run consumes (removes) the first
# usable line. When the queue is empty, pick_best_topic() falls back to
# auto-trend-fetching as before.
#
# posted_topics_log.txt: auto-maintained. Every topic actually used (queue
# OR auto-fetched) gets appended here after a successful run, so a topic
# is never reused even after it scrolls out of "recent YouTube uploads".
QUEUE_PATH = "topics_queue.txt"
LOG_PATH = "posted_topics_log.txt"

# Suffix performance_tracker.py appends to a queue line when it re-queues a
# proven high-retention topic ("winner repeat" — same concept, forced new hook).
VARIATION_SUFFIX = " ||winner_variation"


def peek_queued_topic(queue_path=QUEUE_PATH):
    """Return the next usable RAW line (may include VARIATION_SUFFIX) from the
    queue file, or None if empty/missing."""
    if not os.path.exists(queue_path):
        return None
    with open(queue_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped
    return None


def remove_queued_topic(raw_line, queue_path=QUEUE_PATH):
    """Remove the first line exactly matching raw_line from the queue file
    (call this only after a run using that topic has actually succeeded).
    Pass the RAW line (topic["raw_line"] from pick_best_topic), not just the
    clean title, so winner-repeat entries (which carry VARIATION_SUFFIX) are
    matched and removed correctly."""
    if not os.path.exists(queue_path):
        return
    with open(queue_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    removed = False
    kept = []
    for line in lines:
        if not removed and line.strip() == raw_line:
            removed = True
            continue
        kept.append(line)
    with open(queue_path, "w", encoding="utf-8") as f:
        f.writelines(kept)


def queue_winner_variations(topic_title, count=3, queue_path=QUEUE_PATH):
    """
    "Winner repeat" system: append `count` copies of a proven high-retention
    topic to the front-ish of the queue, tagged with VARIATION_SUFFIX so
    pick_best_topic() knows to tell script_generator to keep the same concept
    but force a different hook/emotion/pacing each time. Called by
    performance_tracker.py once a video crosses the retention threshold.
    """
    lines = []
    if os.path.exists(queue_path):
        with open(queue_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    new_lines = [f"{topic_title}{VARIATION_SUFFIX}\n" for _ in range(count)]
    with open(queue_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines + lines)


def load_posted_log(log_path=LOG_PATH):
    if not os.path.exists(log_path):
        return []
    with open(log_path, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]


def append_posted_log(topic_title, log_path=LOG_PATH):
    """Call this after a run using topic_title has actually succeeded."""
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(topic_title + "\n")


def get_youtube_trending(region="US", max_results=15, category_id=None):
    """Pull currently-trending YouTube videos (titles = proven-to-work hooks)."""
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY missing in .env")

    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": max_results,
        "key": YOUTUBE_API_KEY,
    }
    if category_id:
        params["videoCategoryId"] = category_id

    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    items = r.json().get("items", [])

    results = []
    for it in items:
        sn = it["snippet"]
        stats = it.get("statistics", {})
        results.append({
            "title": sn["title"],
            "description": sn.get("description", "")[:300],
            "tags": sn.get("tags", []),
            "views": int(stats.get("viewCount", 0)),
            "source": "youtube_trending",
        })
    return results


def get_google_trends(geo="US", top_n=15):
    """
    Realtime trending search terms from Google's official public RSS feed
    (no library, no key, more stable than the unofficial pytrends scraper).
    """
    url = f"https://trends.google.com/trending/rss?geo={geo}"
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)

        results = []
        for item in root.findall(".//item")[:top_n]:
            title_el = item.find("title")
            if title_el is None or not title_el.text:
                continue
            # approx_traffic + news snippet titles are nested in the
            # ht: namespace; grab a related news headline if present for extra context
            news_titles = [
                n.text for n in item.findall(
                    ".//{https://trends.google.com/trending/rss}news_item_title"
                ) if n.text
            ]
            results.append({
                "title": title_el.text,
                "related_headline": news_titles[0] if news_titles else "",
                "source": "google_trends",
            })
        return results
    except Exception as e:
        print(f"[trend_finder] Google Trends RSS fetch failed: {e}")
        return []


# Words that signal a topic naturally fits the high-curiosity categories the
# channel is built around (what-if / shocking / dark-mystery / AI-future /
# gaming). Used only to break ties between multiple fresh candidates from the
# same source -- we still follow real trend data, we just prefer the more
# curiosity-shaped headline among equally-fresh options.
CURIOSITY_KEYWORDS = [
    "secret", "hidden", "mystery", "mysterious", "shocking", "shock", "banned",
    "what if", "why", "how", "revealed", "truth", "warning", "danger",
    "impossible", "unbelievable", "disturbing", "dark", "creepy", "ai",
    "future", "breaks", "broke", "record", "died", "disappeared", "gone",
    "exposed", "leaked", "insane", "wild", "no one", "nobody",
]


def _curiosity_score(title):
    """Cheap keyword-overlap score (not a hard filter) — higher means the
    headline already leans toward curiosity/shock/mystery, which tends to
    convert into a stronger hook downstream."""
    lowered = title.lower()
    return sum(1 for kw in CURIOSITY_KEYWORDS if kw in lowered)


def _topic_too_similar(candidate_title, recent_titles, overlap_threshold=0.35):
    """
    Simple word-overlap check (Jaccard-style) between a candidate topic and
    each recently uploaded title. Cheap and dependency-free; good enough to
    catch "same topic, reworded title" cases without needing an LLM call.
    """
    cand_words = set(candidate_title.lower().split())
    if not cand_words:
        return False

    for recent in recent_titles:
        recent_words = set(recent.lower().split())
        if not recent_words:
            continue
        overlap = len(cand_words & recent_words) / len(cand_words | recent_words)
        if overlap >= overlap_threshold:
            return True
    return False


def pick_best_topic(niche_hint="general trending", manual_topic=None, recent_titles=None):
    """
    Returns ONE topic dict to build a video around, in priority order:
      1. manual_topic, if given (CLI override)
      2. next topic in topics_queue.txt, if the queue has one
      3. auto-fetched trending topic (YouTube trending + Google Trends),
         filtered against both recent_titles (YouTube upload history) and
         posted_topics_log.txt (permanent local record) so nothing repeats.

    NOTE: this only PICKS the topic. Call remove_queued_topic()/append_posted_log()
    yourself after the run actually succeeds — see main.py.
    """
    if manual_topic:
        return {"title": manual_topic, "source": "manual", "raw_line": None, "is_variation": False}

    queued = peek_queued_topic()
    if queued:
        is_variation = queued.endswith(VARIATION_SUFFIX)
        clean_title = queued[: -len(VARIATION_SUFFIX)] if is_variation else queued
        return {
            "title": clean_title,
            "source": "queue_variation" if is_variation else "queue",
            "raw_line": queued,
            "is_variation": is_variation,
        }

    recent_titles = recent_titles or []
    posted_log = load_posted_log()
    all_seen_titles = list(recent_titles) + posted_log

    candidates = []
    try:
        candidates += get_youtube_trending()
    except Exception as e:
        print(f"[trend_finder] YouTube trending fetch failed: {e}")
    try:
        candidates += get_google_trends()
    except Exception as e:
        print(f"[trend_finder] Google trends fetch failed: {e}")

    if not candidates:
        raise RuntimeError("No trend sources available — check API keys/network.")

    # Drop anything too close to something already posted (checks both YouTube's
    # own upload history AND our permanent local log, so a topic never repeats
    # even if it scrolls out of "recent uploads")
    fresh_candidates = [
        c for c in candidates if not _topic_too_similar(c["title"], all_seen_titles)
    ]
    if not fresh_candidates:
        print("[trend_finder] WARNING: all candidates looked too similar to recent "
              "uploads — falling back to full candidate list to avoid a hard failure.")
        fresh_candidates = candidates

    # Prefer Google Trends first: it's raw search demand, often catching a topic
    # before YouTube has competition on it. Fall back to top-viewed YouTube
    # trending video if Google Trends came back empty. Within whichever pool we
    # use, rank by curiosity score first (shocking/mystery/AI-future headlines
    # tend to make stronger hooks), tie-broken by recency/views.
    trend_hits = [c for c in fresh_candidates if c["source"] == "google_trends"]
    if trend_hits:
        trend_hits.sort(key=lambda c: _curiosity_score(c["title"]), reverse=True)
        chosen = trend_hits[0]
        return {**chosen, "raw_line": None, "is_variation": False}

    youtube_hits = [c for c in fresh_candidates if c["source"] == "youtube_trending"]
    youtube_hits.sort(key=lambda c: (_curiosity_score(c["title"]), c.get("views", 0)), reverse=True)
    chosen = youtube_hits[0]
    return {**chosen, "raw_line": None, "is_variation": False}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    topic = pick_best_topic()
    print("Chosen topic:", topic)
