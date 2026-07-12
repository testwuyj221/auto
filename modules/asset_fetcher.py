"""
Downloads free vertical stock video clips from Pexels matching keywords.

Previously this always requested only 5 results and returned the very first
(most "relevant" per Pexels ranking) clip that met the height bar -- so the
same handful of top-ranked clips got reused across nearly every video for a
given keyword. This version pulls a bigger pool, picks randomly among the
good matches instead of always #1, and remembers which Pexels video IDs
have already been used (across runs, via used_clips_log.txt) so a clip
already in a previous Short is skipped in favor of a fresh one.
"""
import os
import random
import requests

PEXELS_API_KEY = ""
PEXELS_URL = "https://api.pexels.com/videos/search"

# Persisted across runs (committed back to the repo alongside topics_queue.txt
# / posted_topics_log.txt) so repeats are avoided channel-wide, not just
# within a single video.
USED_CLIPS_LOG = "used_clips_log.txt"
USED_CLIPS_KEEP = 500  # cap file growth; oldest entries age out first

# How many of Pexels' top-ranked results per keyword to treat as "good
# enough" and randomize among, instead of always taking result #1.
CANDIDATE_POOL_SIZE = 12


def _load_used_clip_ids(path=USED_CLIPS_LOG):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]


def _append_used_clip_id(clip_id, path=USED_CLIPS_LOG):
    ids = _load_used_clip_ids(path)
    ids.append(str(clip_id))
    ids = ids[-USED_CLIPS_KEEP:]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(ids) + "\n")


def find_clip(keyword, used_ids=None, orientation="portrait"):
    """
    Search Pexels for a vertical clip matching the keyword. Returns
    (video_id, file_url) or (None, None) if nothing usable was found.
    Picks randomly among the top CANDIDATE_POOL_SIZE relevant results
    (skipping any already-used video IDs) instead of always the #1 hit,
    so the same clip doesn't show up in video after video.
    """
    if not PEXELS_API_KEY:
        raise RuntimeError("PEXELS_API_KEY missing in .env (get a free one at pexels.com/api)")

    used_ids = used_ids or set()

    r = requests.get(
        PEXELS_URL,
        headers={"Authorization": PEXELS_API_KEY},
        params={"query": keyword, "orientation": orientation, "per_page": CANDIDATE_POOL_SIZE},
        timeout=15,
    )
    r.raise_for_status()
    videos = r.json().get("videos", [])
    if not videos:
        return None, None

    def best_file(v):
        files = sorted(v["video_files"], key=lambda f: f.get("height", 0), reverse=True)
        for f in files:
            if f.get("height", 0) >= 720:
                return f["link"]
        return None

    fresh = [v for v in videos if str(v["id"]) not in used_ids and best_file(v)]
    pool = fresh if fresh else [v for v in videos if best_file(v)]
    if not pool:
        return None, None

    chosen = random.choice(pool)
    return chosen["id"], best_file(chosen)


def find_clip_url(keyword, min_width=1080, min_height=1920, orientation="portrait"):
    """Back-compat wrapper (URL only, no dedup) for anything calling the old signature."""
    _id, url = find_clip(keyword, orientation=orientation)
    return url


def download_clip(url, out_path):
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 16):
            f.write(chunk)
    return out_path


def fetch_clips_for_beats(beats, cache_dir="assets_cache"):
    """
    For each beat, try each of its visual_keywords in order until a clip is
    found, preferring clips not already used in a previous video. Returns a
    list of local file paths, same length/order as beats.
    """
    os.makedirs(cache_dir, exist_ok=True)
    used_ids = set(_load_used_clip_ids())
    # also avoid picking the same clip twice within THIS video
    used_this_run = set()

    clip_paths = []
    for i, beat in enumerate(beats):
        found = None
        keywords = list(beat.get("visual_keywords", []))
        random.shuffle(keywords)  # don't always try keywords in the same order either
        for kw in keywords:
            clip_id, url = find_clip(kw, used_ids=used_ids | used_this_run)
            if url:
                out_path = os.path.join(cache_dir, f"beat_{i}.mp4")
                download_clip(url, out_path)
                found = out_path
                used_this_run.add(str(clip_id))
                _append_used_clip_id(clip_id)
                break
        if not found:
            print(f"[asset_fetcher] WARNING: no clip found for beat {i}, keywords={beat.get('visual_keywords')}")
        clip_paths.append(found)
    return clip_paths


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print(find_clip("city skyline night"))
