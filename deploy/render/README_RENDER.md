# Deploying to Render (free, no credit card) + cron-job.org (free scheduler)

Render's free tier doesn't include built-in scheduled Cron Jobs (that's a paid
feature). The workaround: deploy this as a small web service with one
protected endpoint, then use a free external scheduler to "ping" that
endpoint 4x/day.

⚠️ **Untested resource ceiling**: Render's free web service has limited
RAM/CPU. This pipeline runs video encoding (MoviePy) and local speech
transcription (faster-whisper) — both are memory-hungry. It may work fine, or
it may crash/timeout on the free tier. Deploy it, run one manual test (step 7
below), and watch the logs. If it consistently fails on resources, the
PC + Task Scheduler approach from earlier is the reliable fallback.

## 1. Push this project to GitHub

```bash
cd shorts-automator
git init
git add .
git commit -m "Initial commit"
```
Create a new repo on github.com (can be private), then:
```bash
git remote add origin https://github.com/<you>/shorts-automator.git
git branch -M main
git push -u origin main
```

**Double check `.env`, `client_secret.json`, and `token.pickle` do NOT appear
in the repo on GitHub's website afterward** — `.gitignore` is set up to
exclude them, but it's worth a 10-second look since these are real credentials.

## 2. Create the Render account and web service

1. render.com → sign up (no card required for free tier)
2. Dashboard → **New +** → **Web Service**
3. Connect your GitHub account, pick the `shorts-automator` repo
4. Render will detect the `Dockerfile` automatically — leave build/start
   commands blank (the Dockerfile handles it)
5. Instance type: **Free**
6. Click **Create Web Service** (first deploy will fail until env vars are
   set in the next step — that's expected, continue)

## 3. Encode your secret files to paste into Render's env vars

Render env vars are plain text, so binary/JSON secret files get base64-encoded
first. Run this **on your own PC**, in the project folder:

**Windows (PowerShell):**
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("client_secret.json")) | Set-Clipboard
```
(this copies the result straight to your clipboard)

Repeat for the token file:
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("token.pickle")) | Set-Clipboard
```

**Mac/Linux:**
```bash
base64 -w 0 client_secret.json | pbcopy   # Mac
base64 -w 0 client_secret.json | xclip    # Linux
```

## 4. Add environment variables on Render

Render dashboard → your service → **Environment** → add these:

| Key | Value |
|---|---|
| `YOUTUBE_API_KEY` | from your `.env` |
| `GROQ_API_KEY` | from your `.env` |
| `PEXELS_API_KEY` | from your `.env` |
| `GOOGLE_CLIENT_SECRET_B64` | paste the base64 from step 3 |
| `GOOGLE_TOKEN_PICKLE_B64` | paste the other base64 from step 3 |
| `TRIGGER_SECRET` | make up a long random string — this protects your endpoint from strangers triggering uploads on your channel |
| `SHORTS_PRIVACY` | `private` (recommended — see note at the bottom) |

Click **Save Changes** — this triggers a redeploy automatically.

## 5. Find your service URL

Once deployed, Render shows a URL like:
```
https://pulserankd.onrender.com
```

Visit it in a browser — you should see `OK - PulseRankd trigger server is running`.
If you see an error instead, check **Logs** in the Render dashboard for what failed.

## 6. Test the actual trigger, once, manually

Visit (replace with your real URL and secret):
```
https://pulserankd.onrender.com/run-pipeline?token=YOUR_TRIGGER_SECRET
```

This will hang for a while (a few minutes) since it's rendering the actual
video — that's expected, don't refresh. Watch **Logs** in the Render
dashboard in a second tab to see it progress through each pipeline stage live.

If it succeeds, you'll eventually see `{"status": "success"}` in the browser.
If it fails, the logs will show exactly which stage broke.

## 7. Set up the free scheduler (cron-job.org)

1. cron-job.org → sign up (free, no card)
2. Create 4 cron jobs, one per time slot, each hitting:
   ```
   https://pulserankd.onrender.com/run-pipeline?token=YOUR_TRIGGER_SECRET
   ```
3. Set each job's schedule to one of your 4 daily times (8am, 12pm, 4pm, 8pm
   — set the timezone in cron-job.org's job settings, not your local one)
4. Set the **timeout** setting to the maximum cron-job.org allows — the
   render can take a few minutes, and you want the scheduler to wait rather
   than mark it "failed" while it's still legitimately working server-side

Note: even if cron-job.org's own timeout gives up waiting for a response,
the request keeps running on Render's server in the background until done —
a client timeout doesn't cancel the actual video job.

## About `SHORTS_PRIVACY`

Left as `private` on purpose, same reasoning as the PC-deployment version:
unattended + always-public is the exact pattern that risks a channel-wide
flag under YouTube's policy on templated/repetitive automated content. A
quick daily check in YouTube Studio to flip good ones public is cheap
insurance. Change the env var to `public` if you want true zero-touch anyway
— your call.

## If the free tier can't handle it

Signs of resource exhaustion: repeated timeouts, "killed" in logs, or the
video render stage never completing. If that happens, this same Docker setup
works on Render's cheapest paid tier ($7/mo, more RAM), or fall back to the
PC + Task Scheduler approach — same codebase either way, just a different
`deploy/` folder.
