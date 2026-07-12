"""
Full pipeline:
  performance check (winner-repeat queueing) -> trend -> script/title/hashtags
  -> voiceover -> stock clips -> captions -> assembled video -> upload to YouTube

Usage:
  python main.py                      # auto-pick a trending topic
  python main.py --topic "some topic" # use your own topic instead
  python main.py --dry-run            # build the video but DON'T upload
  python main.py --privacy private    # upload but keep it private (recommended at first!)
"""
import argparse
import os
from dotenv import load_dotenv

from modules import (
    trend_finder, script_generator, tts, asset_fetcher, captions,
    video_builder, youtube_uploader, performance_tracker, beat_splitter,
)

load_dotenv()


def _print_script_summary(topic_title, content, upload_title=None):
    """Prints title/description/hashtags/voiceover so it's easy to eyeball
    what this run actually produced. (script_generator.py no longer returns
    hook candidates, self-scores, emotion/pacing, etc. — just the four
    fields below — so this is intentionally simpler than before.)"""
    print("\n" + "=" * 60)
    print(f"TOPIC: {topic_title}")
    if upload_title and upload_title != content["title"]:
        print(f"MODEL'S GENERATED TITLE (unused): {content['title']}")
        print(f"ACTUAL UPLOAD TITLE (locked to queue): {upload_title}")
    else:
        print(f"TITLE: {content['title']}")
    print(f"DESCRIPTION: {content['description']}")
    print(f"HASHTAGS: {' '.join(content.get('hashtags', []))}")
    print("\nVOICEOVER SCRIPT:")
    print(f"  {content['voiceover']}")
    print("=" * 60 + "\n")


def run(manual_topic=None, dry_run=False, privacy="private"):
    print("== 0. Checking recent upload history (to avoid repeat topics) ==")
    recent_titles = []
    try:
        recent_titles = youtube_uploader.get_recent_video_titles(max_results=20)
        print(f"Found {len(recent_titles)} recent uploads to avoid overlapping with.")
    except Exception as e:
        # Don't let this block a run — e.g. very first run ever, or token
        # doesn't have the broadened read scope yet (see youtube_uploader.py note)
        print(f"[main] Couldn't fetch upload history, continuing without it: {e}")

    print("== 0.5. Checking video performance (winner-repeat system) ==")
    try:
        performance_tracker.run_tracking_pass()
    except Exception as e:
        # Never let analytics/tracking hiccups block content generation.
        print(f"[main] Performance tracking pass failed, continuing without it: {e}")

    print("== 1. Finding topic ==")
    topic = trend_finder.pick_best_topic(manual_topic=manual_topic, recent_titles=recent_titles)
    print(f"Topic: {topic['title']}  (source: {topic['source']})")

    extra_context = ""
    if topic.get("is_variation"):
        extra_context = (
            "This topic is a WINNER REPEAT: a past video on this exact concept already "
            "proved it keeps viewers watching. Give it a fresh angle/wording so it doesn't "
            "feel like a rerun of a first-time video on this concept."
        )

    print("== 2. Generating script/title/hashtags ==")
    content = script_generator.generate_content(
        topic["title"], extra_context=extra_context, recent_titles=recent_titles
    )
    print(f"Title: {content['title']}")

    # Locked here (not just at upload time) so the summary print below and
    # the actual YouTube upload always agree on what title will be used.
    if topic["source"] in ("queue", "queue_variation"):
        upload_title = topic["title"]
    else:
        upload_title = content["title"]

    _print_script_summary(topic["title"], content, upload_title=upload_title)

    print("== 3. Generating voiceover ==")
    voiceover_path, words = tts.text_to_speech(content["voiceover"], out_path="output/voiceover.mp3")

    print("== 3.5. Splitting script into visual beats ==")
    # script_generator.py returns one flat voiceover string now, so beats
    # (needed by asset_fetcher/video_builder to fetch+time separate stock
    # clips per segment) are derived here instead. See modules/beat_splitter.py
    beats = beat_splitter.split_into_beats(content["voiceover"], topic["title"])

    print("== 4. Fetching stock clips ==")
    clip_paths = asset_fetcher.fetch_clips_for_beats(beats)

    print("== 5. Preparing synced captions ==")
    # No emphasis_words from script_generator anymore, so captions render
    # without the highlighted-shock-word styling — everything else works.
    caption_chunks = captions.group_words_into_caption_chunks(words)

    print("== 6. Building final video ==")
    final_path = video_builder.build_video(
        beats=beats,
        clip_paths=clip_paths,
        voiceover_path=voiceover_path,
        caption_chunks=caption_chunks,
        out_path="output/final_short.mp4",
    )
    print(f"Video ready: {final_path}")

    if dry_run:
        print("Dry run — skipping upload. (Topic NOT marked as used — dry runs are free to repeat.)")
        return

    print("== 7. Uploading to YouTube ==")
    video_id = youtube_uploader.upload_short(
        video_path=final_path,
        title=upload_title,
        description=content["description"],
        hashtags=content["hashtags"],
        privacy_status=privacy,
    )

    # Record the mapping so performance_tracker.py can later look up this
    # video's real retention and, if it's a winner, know what concept to repeat.
    try:
        performance_tracker.record_upload_mapping(
            video_id=video_id,
            topic_title=topic["title"],
            video_title=content["title"],
            emotion="unknown",  # script_generator.py no longer tracks emotion/pacing
            pacing="unknown",
            is_variation=topic.get("is_variation", False),
        )
    except Exception as e:
        print(f"[main] Couldn't record upload mapping for performance tracking: {e}")

    # Only mark the topic as "used" once everything actually succeeded — if the
    # run failed earlier, the topic stays in the queue / off the log so it gets
    # tried again next time instead of being silently wasted.
    if not manual_topic:
        if topic["source"] in ("queue", "queue_variation"):
            trend_finder.remove_queued_topic(topic["raw_line"] or topic["title"])
        trend_finder.append_posted_log(topic["title"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=None, help="Manually specify a topic instead of auto-trend-detection")
    parser.add_argument("--dry-run", action="store_true", help="Build the video but skip uploading")
    parser.add_argument("--privacy", default="private", choices=["public", "unlisted", "private"])
    args = parser.parse_args()

    run(manual_topic=args.topic, dry_run=args.dry_run, privacy=args.privacy)
