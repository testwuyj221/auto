# Shorts Automator (100% free stack)

Pipeline: trending topic → script/title/hashtags (LLM) → voiceover (TTS) →
stock footage → synced captions → assembled vertical video → YouTube upload.

## ⚠️ Read this first — the monetization trap

YouTube's **"inauthentic content" policy** (tightened July 2025, enforced hard
since a Jan 2026 wave that demonetized 16 channels) does **not** ban
AI/faceless/automated content. It bans content that's **templated and
interchangeable** — same format, no real substance, easily mass-produced.

What survives:
- AI voice + stock footage **with a genuine angle, opinion, or specific detail** per video
- Real variation in topic, structure, hook, and commentary

What gets demonetized:
- Identical script skeletons reused across dozens of videos with only the
  topic swapped
- Zero commentary/insight — just narrating a headline over generic clips

The `script_generator.py` prompt is written to force a genuine angle into
every script. **Don't run this on full autopilot at high volume without
reviewing scripts** — treat the automation as a fast first draft, not a
publish button, at least until you've seen how a few dozen videos perform.

## Setup

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Also install `imagemagick` (needed by MoviePy for text captions):
- Mac: `brew install imagemagick`
- Ubuntu/Debian: `sudo apt install imagemagick`
- Windows: download from imagemagick.org, then set `IMAGEMAGICK_BINARY` env var to its `magick.exe` path

### 1. YouTube Data API key (trend search) — free
1. console.cloud.google.com → create project
2. APIs & Services → Library → enable **YouTube Data API v3**
3. Credentials → Create Credentials → API key
4. Paste into `.env` as `YOUTUBE_API_KEY`

### 2. Groq API key (script generation) — free
1. console.groq.com/keys → create key
2. Paste into `.env` as `GROQ_API_KEY`

### 3. Pexels API key (stock footage) — free
1. pexels.com/api → request access (instant)
2. Paste into `.env` as `PEXELS_API_KEY`

### 4. YouTube upload OAuth client — free
1. Same Google Cloud project as step 1 → also enable **YouTube Data API v3** (same one)
2. Credentials → Create Credentials → OAuth client ID → Application type: **Desktop app**
3. Download the JSON, rename it to `client_secret.json`, put it in the project root
4. Add yourself as a test user under OAuth consent screen (while app is unpublished/testing)

## Run it

```bash
# Dry run first — builds the video but doesn't upload. ALWAYS do this first.
python main.py --dry-run

# Use your own topic instead of auto-trend-detection
python main.py --topic "the new AI phone launch" --dry-run

# Upload for real, but as private (recommended until you trust the output)
python main.py --privacy private

# Once you've reviewed a few and you're confident:
python main.py --privacy public
```

First upload will open a browser window to authorize your Google account —
after that, `token.pickle` is cached and reused.

## Automating the schedule

Once you trust the output, run it on a cron/Task Scheduler job, e.g. daily at 9am:

```bash
# crontab -e
0 9 * * * cd /path/to/shorts-automator && venv/bin/python main.py --privacy private
```

Keep `--privacy private` in the cron job and manually flip videos to public
after a quick review — this is your quality gate against the policy issue above.

## Quota limits (free tier)

- YouTube Data API: 10,000 units/day. Trend search ≈ 100 units, each upload ≈ 1,600 units
  → you can safely do ~6 uploads/day.
- Groq free tier: generous per-minute limits, plenty for a few scripts/day.
- Pexels: 200 requests/hour, 20,000/month — plenty.

## File structure

```
main.py                    # orchestrator — run this
modules/
  trend_finder.py           # YouTube trending + Google Trends
  script_generator.py        # Groq LLM -> title/description/hashtags/script beats
  tts.py                      # edge-tts voiceover
  asset_fetcher.py             # Pexels stock footage per beat
  captions.py                   # faster-whisper word timestamps -> caption chunks
  video_builder.py                # MoviePy assembly + burned-in captions
  youtube_uploader.py               # OAuth upload via Data API v3
```
