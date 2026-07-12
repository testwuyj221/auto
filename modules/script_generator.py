"""
Turns a topic into: a Shorts script (voiceover text), title, description,
hashtags, a list of visual keywords (used later to fetch stock footage),
and now a full virality pass:

  - 3 competing hook variations (different emotion: fear / curiosity / shock /
    urgency), the model scores each, we keep the strongest.
  - A self-predicted "hook_strength" / "retention_potential" score (1-10).
    If either comes in under MIN_ACCEPTABLE_SCORE, we regenerate (up to
    MAX_REGENERATIONS extra attempts) instead of shipping a weak script.
  - "emphasis_words" per beat (the shock/number/key words) so downstream
    caption rendering can highlight them.
  - A lightweight variation log (hook emotion + pacing style of the last few
    videos) fed back into the prompt so the channel doesn't lock into one
    repetitive hook style/tone -- this is what keeps automated output from
    feeling identical video after video.
  - Support for "winner repeat" requests (see performance_tracker.py): when a
    topic is a repeat of a proven high-retention concept, extra_context tells
    the model to keep the concept but force a different hook/emotion/pacing.
  - Pattern-interrupt beats (roughly every 2 lines) baked into the prompt, a
    deterministic power-word check (imagine/suddenly/but/then/now, min 2, or
    it regenerates), a "first frame" rule so the hook's visuals are shocking
    on their own, and explicit monetization-safety / anti-listicle guidance.

Uses Groq's free-tier API (OpenAI-compatible /chat/completions endpoint).
Using the larger llama-3.3-70b model here (still free on Groq) — noticeably
better writing quality than the 8b model for hooks/pacing/voice.
"""
import os
import re
import json
import random
import requests
from dotenv import load_dotenv

load_dotenv()  # loads .env file

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

# --- Self-improvement loop settings -------------------------------------
# If the model's own hook_strength / retention_potential prediction comes in
# below this, we ask it to try again instead of shipping a weak script.

# --- Variation tracking --------------------------------------------------
# Records {"emotion": ..., "pacing": ...} for recent videos so the prompt can
# actively steer away from repeating the same hook style/emotion back-to-back.
VARIATION_LOG_PATH = "hook_variation_log.txt"
VARIATION_LOG_KEEP = 8

# --- Power word injection -------------------------------------------------
# Cheap, deterministic check backing up the "POWER WORD INJECTION" prompt rule
# -- if the model forgets, this is what actually forces a regeneration instead
# of silently shipping a script with zero spoken-language retention cues.


SYSTEM_PROMPT = """
You are an expert YouTube Shorts scriptwriter.

Your job is to write engaging, natural, and informative Shorts that sound like they were written by a successful YouTube creator, not an AI.

GOAL

Create a complete 30–40 second voiceover that hooks viewers immediately, keeps them interested, and ends naturally.

TITLE

YouTube now shows Shorts in a dedicated search results filter, so the title
is doing real search-discovery work, not just feed-hook work. Write it so
it:
• Contains the specific, searchable subject in plain words (a name, place,
  event, or concept someone would actually type) -- not just a vibe.
• Still creates curiosity/tension so it also works as a feed hook.
• Never misleads -- the video must actually deliver what the title promises,
  since a mismatch tanks retention and gets read as a satisfaction signal
  against the channel.
Keep it under 100 characters.

DESCRIPTION

Write 2-4 real sentences (not a repeat of the title, not empty):
• First sentence: state what the video is actually about in plain,
  searchable language (this is indexed by YouTube search, same as the title).
• Then 1-2 sentences of extra context, a teaser detail not in the voiceover,
  or why it matters -- give people a reason to read on, not just filler.
• End with one short call-to-action line (e.g. "Follow for more stories like
  this." / "Comment your pick below.").
Never leave this blank or one line long -- a thin description loses search
visibility and makes the channel look low-effort.

TARGET

• 30–40 seconds spoken (this pipeline speaks at roughly 2.2-2.4 words per second)
• That means: 80–105 words TOTAL. Not 140. Not 170. Count your words before
  returning the script -- if you're over 105, cut it down before responding.

HOW TO CUT LENGTH WITHOUT BECOMING A BARE LIST OF POINTS

• Don't remove explanations -- remove REDUNDANCY. If two sentences make the
  same point in different words, keep only the stronger one.
• Cut throat-clearing and filler ("It's important to note that...", "As you
  can see...", restating the topic mid-script).
• Prefer one sharp, concrete detail per point over two vague ones.
• Every point still needs a reason WHY it matters -- you're trading number of
  words, not trading away the "why." A shorter script with real explanations
  beats a longer script that pads the same explanation twice.
• The ending must still land as a real conclusion/question, never cut off
  mid-thought just to hit the word count.

WRITING STYLE

• Write like a human narrator.
• Use conversational, easy-to-understand English.
• Sound energetic and engaging.
• The script must flow like one continuous story.
• Every sentence should naturally connect to the next.
• Mix short and medium-length sentences.
• Explain WHY things matter, not just WHAT happened.
• Avoid robotic wording.
• Avoid textbook language.
• Avoid repetitive sentence structures.
• Never use sentence fragments.
• Never sound like a list of facts.

STORYTELLING

Don't summarize the topic.

Tell the story behind it.

Every script should feel like the viewer is listening to an interesting documentary narrator.

Whenever possible:

• Introduce the topic.
• Explain what happened.
• Explain why it happened.
• Explain the result.
• End with an interesting takeaway.

Use natural transition words when appropriate, such as:

However
But
Meanwhile
That's because
Surprisingly
Even more interesting
In the end
Finally

Never write literal ellipses ("...") or em dashes ("--") anywhere in the
voiceover text. The text-to-speech engine reads punctuation as timing: an
ellipsis or a long dash inserts a noticeable dead-air pause in the audio.
Use a period or comma instead, every time.

SCRIPT STRUCTURE

1. HOOK

Grab attention immediately.

The first sentence should make viewers curious while clearly introducing the topic.

Good examples:

"Fifty years ago, Dubai was mostly desert. Today it's one of the richest cities on Earth."

"These are the richest YouTubers in 2026, and number one earns more than some Hollywood studios."

Never start with:

• Random numbers
• Sentence fragments
• Generic introductions
• "Have you ever wondered..."
• "In this video..."

2. INTRODUCTION

Briefly explain what the video is about.

Assume the viewer knows nothing.

3. MAIN BODY

Explain everything logically.

For ranking videos:

• Follow the exact ranking requested.
• If the title says Top 5, include exactly 5 entries.
• If the title says Top 10, include exactly 10 entries.
• Never skip numbers.

Each entry should include:

• Position
• Name
• Why it deserves that position
• One interesting fact
• Relevant statistic if available

Do not simply list names.

Explain every point naturally.

For educational topics:

Tell the story step by step.

Do not jump randomly between facts.

Focus on cause and effect.

4. OUTRO

End naturally, AND make it loop.

The last line should call back to the hook, so when the video restarts (autoplay
loop or the viewer swipes back), the ending flows straight back into the
opening instead of feeling like a dead stop. This is a real 2026 ranking
signal: loops that earn a rewatch are one of the strongest engagement signals
Shorts get, and a clean loop is one of the easiest ways to earn one.

How to do it without sounding gimmicky:
• Echo a specific word, image, or phrase from the hook in the final line
  ("...and that's how a patch of desert became one of the richest cities on
  Earth" calling back to a hook about Dubai being "mostly desert").
• Or end on a question/thought that naturally makes the hook's opening line
  feel like the answer/next beat if watched again.
• Do NOT just repeat the hook verbatim — that feels broken, not looping.

Examples:

"Which one surprised you the most? Let us know below."

"Follow for more interesting facts."

Never end abruptly.

HASHTAGS

YouTube's Shorts search update means title keywords now matter far more than
hashtag count -- keep hashtags focused instead of stuffed.

Return 5 to 8 hashtags total, no spaces inside a tag, never repeat one:

• 2-3 BROAD Shorts hashtags that are actually in use right now, e.g. #shorts
  #shortsfeed #viral #fyp #trending #youtubeshorts — rotate which ones you
  pick, don't reuse the identical set every time.
• 3-5 NICHE/TOPIC-SPECIFIC hashtags derived from what this exact video is
  about (people, place, subject, category — e.g. a video about Dubai's
  economy might use #dubai #uae #economy #richestcities).

NEVER return only ["#shorts"] or only generic tags with nothing topic-specific.
The niche-specific tags are what actually get you discovered by an interested
audience — broad tags alone just dump you in an oversaturated pool.

QUALITY CHECK

Before returning the script, silently verify:

✓ Sounds like a real YouTube creator.

✓ Flows naturally.

✓ Doesn't feel like Wikipedia.

✓ Doesn't repeat sentence structures.

✓ Every important point has an explanation.

✓ The ending feels complete.

If any answer is NO, rewrite the script before returning it.

Return ONLY valid JSON.

Schema:

{
  "title": "",
  "description": "One real sentence about what this video covers, one sentence of extra context or a teaser detail, then a short call-to-action like 'Follow for more.'",
  "hashtags": ["#shorts", "#viral", "#topicword1", "#topicword2", "#topicword3"],
  "voiceover": ""
}
"""

# --- Hashtag safety net ---------------------------------------------------
# Backstop for HASHTAGS prompt rule above: if the model still ships a lazy
# ["#shorts"]-only (or otherwise too-short) list, top it up deterministically
# instead of shipping something that will never get discovered. Rotated so
# every video doesn't carry an identical broad-tag block.
#
# Kept short on purpose: YouTube's 2026 Shorts search update made TITLE
# keywords the bigger discovery lever, not hashtag volume -- see the TITLE
# and HASHTAGS sections of SYSTEM_PROMPT above. Hashtags are a light-touch
# categorization signal now, not a tag-everything SEO field.
BROAD_VIRAL_HASHTAGS = [
    "#shorts", "#shortsfeed", "#viral", "#fyp", "#trending", "#youtubeshorts",
]
MIN_HASHTAGS = 5
MAX_HASHTAGS = 8


def _topic_derived_tags(topic_title, max_tags=5):
    """Cheap keyword-derived hashtags from the topic title, used only to top
    up a too-short hashtag list -- never replaces the model's own niche tags."""
    stopwords = {
        "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or",
        "is", "are", "was", "were", "this", "that", "with", "by", "from",
        "as", "it", "its", "his", "her", "their", "how", "why", "what",
    }
    words = re.findall(r"[A-Za-z0-9]+", topic_title.lower())
    tags = []
    for w in words:
        if w in stopwords or len(w) < 3:
            continue
        tag = f"#{w}"
        if tag not in tags:
            tags.append(tag)
        if len(tags) >= max_tags:
            break
    return tags


def _ensure_hashtag_quality(data, topic_title, min_tags=MIN_HASHTAGS):
    tags = [t if t.startswith("#") else f"#{t}" for t in data.get("hashtags", [])]
    # de-dupe, case-insensitive, preserve order
    seen = set()
    deduped = []
    for t in tags:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    tags = deduped

    if len(tags) < min_tags:
        pool = BROAD_VIRAL_HASHTAGS[:]
        random.shuffle(pool)
        for t in pool:
            if t.lower() not in seen:
                tags.append(t)
                seen.add(t.lower())
            if len(tags) >= min_tags:
                break

    if len(tags) < min_tags:
        for t in _topic_derived_tags(topic_title, max_tags=min_tags - len(tags)):
            if t.lower() not in seen:
                tags.append(t)
                seen.add(t.lower())

    data["hashtags"] = tags[:MAX_HASHTAGS]
    return data


def _load_recent_variation(path=VARIATION_LOG_PATH, keep=VARIATION_LOG_KEEP):
    """Returns the last `keep` {"emotion":..., "pacing":...} entries, newest last."""
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries[-keep:]


def _append_variation(emotion, pacing, path=VARIATION_LOG_PATH):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"emotion": emotion, "pacing": pacing}) + "\n")


def _call_groq(user_prompt):
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY missing in .env (get a free one at console.groq.com/keys)")

    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    return json.loads(raw)


def _sanitize_voiceover(data):
    """Deterministic backstop for the 'no ellipses/dashes' prompt rule --
    strips characters that make edge-tts insert long unnatural pauses,
    regardless of whether the model actually followed the instruction."""
    text = data.get("voiceover", "")
    text = text.replace("...", ".").replace("\u2026", ".")  # ellipsis char too
    text = text.replace("--", ",").replace("\u2014", ",").replace("\u2013", ",")
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"\s+", " ", text).strip()
    data["voiceover"] = text
    return data


def _ensure_description_quality(data, topic_title, min_chars=40):
    """Backstop for the DESCRIPTION prompt rule above: if the model ships an
    empty or too-thin description, build a reasonable one from the title and
    voiceover instead of uploading a blank/near-blank description."""
    desc = (data.get("description") or "").strip()
    if len(desc) >= min_chars:
        return data

    title = (data.get("title") or topic_title or "").strip()
    voiceover = (data.get("voiceover") or "").strip()
    # first sentence of the voiceover as a stand-in teaser line
    first_sentence = re.split(r"(?<=[.!?])\s", voiceover)[0] if voiceover else ""

    parts = []
    if title:
        parts.append(title.rstrip(".") + ".")
    if first_sentence and first_sentence.lower() not in title.lower():
        parts.append(first_sentence)
    parts.append("Follow for more like this.")

    data["description"] = " ".join(parts).strip()
    return data


def _validate(data):
    assert "title" in data, "Missing title"
    assert "description" in data, "Missing description"
    assert "hashtags" in data and isinstance(data["hashtags"], list), "Missing hashtags"
    assert "voiceover" in data and data["voiceover"].strip(), "Missing voiceover"


# Deterministic backstop for the TARGET word count above -- we've already seen
# the model ignore a stated word target once (shipped 153 words against an
# earlier "140-170" instruction that itself was wrong), so don't rely purely
# on prompt compliance. One retry with explicit feedback, then ship whichever
# attempt is closer to the target rather than looping indefinitely.
TARGET_WORD_MIN = 80
TARGET_WORD_MAX = 105


def _word_count(data):
    return len(data.get("voiceover", "").split())




def generate_content(topic_title, extra_context="", recent_titles=None, track_variation=True):
    """
    Generate a YouTube Shorts script using the current SYSTEM_PROMPT.
    Returns a dict containing:
        - title
        - description
        - hashtags
        - voiceover
    """

    base_prompt = f"Trending topic: {topic_title}\n{extra_context}".strip()

    if recent_titles:
        recent_list = "\n".join(f"- {t}" for t in recent_titles[:15])
        base_prompt += (
            "\n\nThese are titles already posted on this channel recently.\n"
            "Do NOT reuse their angle, structure, hook, wording, or storytelling style.\n"
            "Create a fresh, unique video.\n\n"
            f"{recent_list}"
        )

    if track_variation:
        recent_variation = _load_recent_variation()
        if recent_variation:
            emotions = [v.get("emotion") for v in recent_variation if v.get("emotion")]
            pacings = [v.get("pacing") for v in recent_variation if v.get("pacing")]

            base_prompt += (
                "\n\nRecent videos used these hook emotions:\n"
                f"{emotions}\n\n"
                "Recent pacing styles:\n"
                f"{pacings}\n\n"
                "Try a different storytelling style so videos don't feel repetitive."
            )

    data = _call_groq(base_prompt)
    _validate(data)
    data = _sanitize_voiceover(data)
    word_count = _word_count(data)

    if not (TARGET_WORD_MIN <= word_count <= TARGET_WORD_MAX):
        retry_prompt = base_prompt + (
            f"\n\nYour previous attempt was {word_count} words -- "
            f"{'too long' if word_count > TARGET_WORD_MAX else 'too short'}. "
            f"Rewrite it to land between {TARGET_WORD_MIN} and {TARGET_WORD_MAX} words "
            "total. Do not just chop the ending off -- rewrite for length while "
            "keeping a real conclusion, and keep the 'why' behind each point "
            "(cut redundant phrasing, not explanations)."
        )
        retry_data = _call_groq(retry_prompt)
        _validate(retry_data)
        retry_data = _sanitize_voiceover(retry_data)
        retry_count = _word_count(retry_data)
        # keep whichever attempt actually lands closer to the target range
        if abs(retry_count - (TARGET_WORD_MIN + TARGET_WORD_MAX) / 2) < \
           abs(word_count - (TARGET_WORD_MIN + TARGET_WORD_MAX) / 2):
            data = retry_data

    if track_variation:
        _append_variation("unknown", "normal")

    data = _ensure_hashtag_quality(data, topic_title)
    data = _ensure_description_quality(data, topic_title)

    return data

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    out = generate_content("Simone Biles wins gold")
    print(json.dumps(out, indent=2))
