"""
Free text-to-speech via edge-tts (uses Microsoft Edge's online voices,
no API key required, natural-sounding).

IMPORTANT: this also captures word-level timing directly from edge-tts's own
"WordBoundary" events during synthesis, instead of running a separate Whisper
transcription pass afterward. edge-tts already knows exactly when each word
is spoken (it generated the speech), so re-transcribing the audio with an ML
model was redundant — and on memory-constrained hosting (e.g. Render's free
tier), dropping Whisper entirely removes a real source of OOM crashes.
"""
import asyncio
import os
import re
import edge_tts

# en-US-GuyNeural reads noticeably more "text-to-speech-y" than some of the
# newer multilingual neural voices, especially combined with the pitch bump
# below. en-US-EricNeural and en-US-ChristopherNeural are deeper, more
# even-cadence "documentary narrator" voices that read less roboticly for
# this kind of fact/story short. Swap DEFAULT_VOICE to try others:
#   en-US-EricNeural         - calm, deep, natural narrator (current default)
#   en-US-ChristopherNeural  - similar, slightly more casual
#   en-US-GuyNeural          - previous default, more "announcer" energy
#   en-US-JennyNeural / en-US-AriaNeural - natural female alternatives
# Full list: `edge-tts --list-voices` (free, no key needed).
DEFAULT_VOICE = "en-US-EricNeural"

# Un-tuned "-10%/+2Hz" was making the voice sound more clipped/dramatic,
# which read as more artificial, not less. 0%/0Hz is edge-tts's own natural
# cadence for this voice; nudge only in small steps if you want it slower.
DEFAULT_RATE = "-2%"
DEFAULT_PITCH = "+0Hz"

# --- Pause compression -----------------------------------------------------
# edge-tts (and punctuation in the generated script) can leave gaps between
# words/sentences that feel like dead air on a fast-paced Short. This trims
# any gap longer than MAX_PAUSE_MS down to MAX_PAUSE_MS and shifts every
# later word_boundary timestamp to match, so captions stay in sync with the
# now-shorter audio. Requires ffmpeg (already installed in the GH Actions
# workflow) via pydub.
MAX_PAUSE_MS = 250
MIN_SILENCE_LEN_MS = 380
SILENCE_THRESH_OFFSET_DB = 16


async def _synthesize_with_timestamps(text, out_path, voice, rate, pitch):
    # boundary="WordBoundary" is required explicitly: newer edge-tts versions
    # default Communicate() to "SentenceBoundary" instead of per-word timing.
    # Without this, chunk["type"] is never "WordBoundary" below, so
    # word_boundaries silently comes back empty and captions.py has nothing
    # to render -- the pipeline still succeeds end-to-end, just with zero
    # burned-in captions and no error anywhere.
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    word_boundaries = []

    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset/duration are in 100-nanosecond units; convert to seconds
                start = chunk["offset"] / 10_000_000
                end = (chunk["offset"] + chunk["duration"]) / 10_000_000
                word_boundaries.append({
                    "word": chunk["text"],
                    "start": start,
                    "end": end,
                })

    if not word_boundaries:
        raise RuntimeError(
            "edge-tts returned zero WordBoundary events -- captions would be "
            "silently empty. This should not happen with boundary='WordBoundary' "
            "explicitly set; check for an edge-tts API change."
        )

    return word_boundaries


def _compress_pauses(mp3_path, word_boundaries, max_pause_ms=MAX_PAUSE_MS,
                      min_silence_len=MIN_SILENCE_LEN_MS,
                      thresh_offset_db=SILENCE_THRESH_OFFSET_DB):
    """
    Shrinks any silent gap longer than max_pause_ms down to max_pause_ms,
    re-exports the mp3, and shifts word_boundaries to match the new,
    shorter timeline. Fails soft: if pydub/ffmpeg aren't available or
    anything goes wrong, returns the original audio/timestamps unchanged
    rather than blocking the pipeline.
    """
    try:
        from pydub import AudioSegment
        from pydub.silence import detect_silence
    except ImportError:
        print("[tts] pydub not installed -- skipping pause compression "
              "(pip install pydub to enable this).")
        return mp3_path, word_boundaries

    try:
        audio = AudioSegment.from_file(mp3_path)
        silence_thresh = audio.dBFS - thresh_offset_db
        silences = detect_silence(audio, min_silence_len=min_silence_len,
                                   silence_thresh=silence_thresh)
        long_gaps = [(s, e) for s, e in silences if (e - s) > max_pause_ms]
        if not long_gaps:
            return mp3_path, word_boundaries

        new_audio = AudioSegment.empty()
        cursor = 0
        shift_points = []  # (original_ms_after_which_shift_applies, cumulative_removed_ms)
        cumulative_removed = 0

        for start, end in long_gaps:
            keep_end = start + max_pause_ms // 2
            resume_at = end - max_pause_ms // 2
            if keep_end <= cursor or resume_at <= keep_end:
                continue
            new_audio += audio[cursor:keep_end]
            cumulative_removed += (resume_at - keep_end)
            shift_points.append((resume_at, cumulative_removed))
            cursor = resume_at

        new_audio += audio[cursor:]
        new_audio.export(mp3_path, format="mp3")

        def _shift(t_sec):
            t_ms = t_sec * 1000
            removed = 0
            for point, cum in shift_points:
                if t_ms >= point:
                    removed = cum
                else:
                    break
            return max(0.0, t_sec - removed / 1000)

        for w in word_boundaries:
            w["start"] = _shift(w["start"])
            w["end"] = _shift(w["end"])

        saved_ms = cumulative_removed
        print(f"[tts] Compressed {len(shift_points)} long pause(s), "
              f"trimmed ~{saved_ms/1000:.1f}s of dead air.")
        return mp3_path, word_boundaries
    except Exception as e:
        print(f"[tts] Pause compression failed, keeping original audio: {e}")
        return mp3_path, word_boundaries


def text_to_speech(text, out_path="output/voiceover.mp3", voice=DEFAULT_VOICE,
                    rate=DEFAULT_RATE, pitch=DEFAULT_PITCH, compress_pauses=True):
    """
    Returns (audio_path, word_boundaries) — word_boundaries is a list of
    {"word": str, "start": float, "end": float}, ready to pass straight into
    captions.group_words_into_caption_chunks().

    rate: edge-tts speaking-rate string, e.g. "-20%" (slower), "+10%" (faster).
    pitch: edge-tts pitch string, e.g. "+2Hz", "-5Hz".
    compress_pauses: trims any gap longer than MAX_PAUSE_MS down to it (see
        _compress_pauses above). Set False to hear the raw edge-tts output.
    """
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # Extra safety net: even if script_generator.py's sanitizer misses
    # something, strip ellipses/long dashes right before synthesis too --
    # these are what most reliably cause edge-tts to insert a long pause.
    text = text.replace("...", ".").replace("\u2026", ".")
    text = text.replace("--", ",").replace("\u2014", ",").replace("\u2013", ",")
    text = re.sub(r"\.{2,}", ".", text)

    word_boundaries = asyncio.run(_synthesize_with_timestamps(text, out_path, voice, rate, pitch))

    if compress_pauses:
        out_path, word_boundaries = _compress_pauses(out_path, word_boundaries)

    return out_path, word_boundaries


if __name__ == "__main__":
    path, words = text_to_speech("This is a test of the free text to speech engine.", "output/test_tts.mp3")
    print(f"Saved {path}")
    for w in words[:5]:
        print(w)
