"""
Groups word-level timestamps into short on-screen caption chunks.

Word timing comes directly from edge-tts (see tts.py) instead of a separate
Whisper transcription pass — this file doesn't run any ML model, which
matters a lot on memory-constrained hosting.

Now also flags "emphasis" chunks: script_generator.py tags 1-3 shock/number
words per beat ("emphasis_words"). Any caption chunk containing one of those
words gets marked emphasis=True so video_builder.py can render it in a
highlight color/bigger size — the "big, bold, highlighted key words" caption
style that performs well on Shorts.
"""
import re


def _normalize(word):
    """Lowercase + strip punctuation so 'shocking!' matches emphasis word 'shocking'."""
    return re.sub(r"[^\w]", "", word).lower()


def group_words_into_caption_chunks(words, max_words_per_chunk=4, emphasis_words=None):
    """
    Group words into small chunks (e.g. 3-4 words) for punchy on-screen captions.

    emphasis_words: optional iterable of words (from script_generator's
    per-beat "emphasis_words") to flag for highlighted caption styling.
    """
    emphasis_set = {_normalize(w) for w in (emphasis_words or []) if w}

    chunks = []
    for i in range(0, len(words), max_words_per_chunk):
        chunk = words[i:i + max_words_per_chunk]
        if not chunk:
            continue
        chunk_words = [w["word"] for w in chunk]
        is_emphasis = any(_normalize(w) in emphasis_set for w in chunk_words)
        chunks.append({
            "text": " ".join(chunk_words),
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
            "emphasis": is_emphasis,
        })
    return chunks
