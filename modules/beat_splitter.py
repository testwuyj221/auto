"""
script_generator.py now returns one flat "voiceover" string instead of a
list of per-beat dicts with visual_keywords/emphasis_words. asset_fetcher.py
and video_builder.py still need to fetch/time a *separate* stock clip per
segment of the video, so this module rebuilds that beat structure downstream
of script generation instead of inside it.

This is a simple, deterministic (non-LLM) split — good enough to keep the
video pipeline working, but the keyword extraction is naive (no LLM call,
just stopword-filtered nouns-ish words from each sentence + the topic title
as a fallback). If clip relevance matters a lot to you, consider having
script_generator ask the model for 1-2 keywords per sentence instead.
"""
import re

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "to", "for",
    "with", "is", "are", "was", "were", "be", "been", "being", "it", "its",
    "this", "that", "these", "those", "as", "by", "from", "than", "then",
    "so", "if", "when", "while", "into", "over", "under", "about", "up",
    "down", "out", "not", "no", "yes", "you", "your", "we", "our", "they",
    "their", "he", "she", "his", "her", "them", "i", "my", "me", "us",
    "will", "would", "could", "should", "can", "just", "some", "one",
    "more", "most", "have", "has", "had", "do", "does", "did", "which",
    "what", "who", "how", "why", "there", "here",
}


def _sentence_split(text):
    # Split on sentence-ending punctuation, keep it simple/deterministic.
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _keywords_for_sentence(sentence, topic_title, max_keywords=3):
    words = re.findall(r"[A-Za-z']+", sentence.lower())
    candidates = [w for w in words if len(w) > 3 and w not in _STOPWORDS]

    seen = []
    for w in candidates:
        if w not in seen:
            seen.append(w)
        if len(seen) >= max_keywords:
            break

    if not seen:
        seen = [topic_title]
    else:
        # Prepend the topic title as a broader fallback search term so
        # asset_fetcher still has something sensible to try if the specific
        # keyword returns no stock footage.
        seen.append(topic_title)

    return seen


def split_into_beats(voiceover_text, topic_title, max_beats=8):
    """
    Turns a flat voiceover string into beat dicts:
      {"section": "beat_0", "text": "...", "visual_keywords": ["...", ...]}

    max_beats caps how many separate stock clips get fetched/cut together —
    very long scripts get their trailing sentences merged into the last beat
    rather than fetching/downloading a huge number of clips.
    """
    sentences = _sentence_split(voiceover_text)
    if not sentences:
        sentences = [voiceover_text.strip()] if voiceover_text.strip() else [topic_title]

    if len(sentences) > max_beats:
        head = sentences[: max_beats - 1]
        tail = " ".join(sentences[max_beats - 1:])
        sentences = head + [tail]

    beats = []
    for i, sentence in enumerate(sentences):
        beats.append({
            "section": f"beat_{i}",
            "text": sentence,
            "visual_keywords": _keywords_for_sentence(sentence, topic_title),
        })
    return beats
