# Deploying PulseRankd to run unattended, 4x/day

Your PC being on isn't reliable for "set and forget," so this runs on a small
always-on server instead. **Oracle Cloud's Always Free tier** is the
recommendation — unlike AWS/GCP free tiers (12 months, then billed), Oracle's
free VM has no expiry, and its free ARM instance (4 cores/24GB RAM) is far
more than this pipeline needs.

## 1. Create the free server

1. Sign up at oracle.com/cloud/free (needs a card for identity verification,
   but the Always Free resources are never billed)
2. Create a Compute Instance:
   - Image: **Canonical Ubuntu 22.04**
   - Shape: **VM.Standard.A1.Flex** (Ampere/ARM, Always Free eligible) — 2 OCPU / 12GB RAM is plenty
   - Keep the default networking/SSH key setup (download the private key when prompted)
3. Note the instance's public IP once it's running

## 2. Connect to it

```bash
ssh -i /path/to/downloaded-key.pem ubuntu@<server-public-ip>
```

## 3. Install dependencies on the server

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv ffmpeg imagemagick git

# Allow ImageMagick to handle text (Ubuntu's default policy blocks it)
sudo sed -i 's/rights="none" pattern="@\*"/rights="read|write" pattern="@*"/' /etc/ImageMagick-6/policy.xml
```

## 4. Get your project onto the server

From your own PC (not the server), upload the whole project folder:
```bash
scp -i /path/to/key.pem -r shorts-automator ubuntu@<server-public-ip>:~/
```

## 5. Set up the Python environment on the server

```bash
ssh -i /path/to/key.pem ubuntu@<server-public-ip>
cd shorts-automator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
chmod +x deploy/run_pipeline.sh
```

## 6. Copy your working credentials over

These three files must exist in the project root **on the server** — copy
them from your PC where you already authorized everything:
- `.env` (your API keys)
- `client_secret.json`
- `token.pickle` (this is what lets it skip the browser login — critical)

```bash
scp -i /path/to/key.pem .env client_secret.json token.pickle ubuntu@<server-public-ip>:~/shorts-automator/
```

## 7. Test it manually once, on the server, before trusting cron with it

```bash
cd shorts-automator
./deploy/run_pipeline.sh
```
Check `logs/run_*.log` for the output and confirm the video builds correctly
in this new environment (font rendering, ffmpeg, etc. can behave slightly
differently server-side — this is your chance to catch that before it's unattended).

## 8. Set the timezone so "8am" actually means 8am your time

```bash
sudo timedatectl set-timezone Asia/Kolkata
```

## 9. Install the schedule

```bash
crontab deploy/crontab.txt
crontab -l   # confirm it's in
```

This runs at 8am, 12pm, 4pm, and 8pm daily, uploading as **private** by
default — this is intentional, see below.

## About true zero-touch

Everything above gets you to "runs on its own, uploads automatically." One
thing I'd push back on softly: I kept new uploads defaulting to **private**
rather than public, given the earlier note about YouTube's policy on
templated/repetitive automated content — a bad or repetitive run going
public four times a day, unreviewed, for weeks, is the exact pattern that
gets flagged. A quick daily 2-minute check (flip good ones to public in
YouTube Studio) costs you almost nothing and is real insurance for your
channel.

If you still want it fully hands-off with no daily check, you can override
that default:
```bash
# in crontab, or by exporting before the cron job runs
SHORTS_PRIVACY=public
```
Just know that's the one part of "I do nothing" that trades away your
quality/safety gate.

## Monitoring without checking in daily

Logs land in `shorts-automator/logs/`. To get a lightweight heads-up on
failures without logging in constantly, you could wire `run_pipeline.sh` to
ping a free notification service (e.g. ntfy.sh, ping a Discord webhook) on
`$EXIT_CODE != 0` — say the word and I'll add that in.
