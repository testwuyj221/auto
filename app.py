"""
Web wrapper around main.py so this can run on Render's free web service tier
(which has no built-in free cron — an external scheduler hits this endpoint
on a timer instead, see deploy/render/README_RENDER.md).

IMPORTANT: this endpoint runs the pipeline SYNCHRONOUSLY (blocks until done)
rather than in a background thread. Render's free tier sleeps a service after
15 minutes with no active request — if we returned instantly and rendered in
the background, Render could freeze the process mid-video-render. Keeping the
request open the whole time keeps the service "active" until the job finishes.

Secrets (client_secret.json, token.pickle) are stored as base64 env vars on
Render (never committed to git) and decoded to disk at startup.
"""
import os
import base64
import threading
from flask import Flask, request, jsonify

app = Flask(__name__)

RUN_LOCK = threading.Lock()


def _restore_secret_file(env_var, out_path):
    """Decode a base64-encoded secret from an env var into a real file on disk."""
    b64 = os.environ.get(env_var)
    if b64 and not os.path.exists(out_path):
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"Restored {out_path} from {env_var}")


def _bootstrap_secrets():
    _restore_secret_file("GOOGLE_CLIENT_SECRET_B64", "client_secret.json")
    _restore_secret_file("GOOGLE_TOKEN_PICKLE_B64", "token.pickle")


def _ensure_working_dirs():
    for d in ["output", "assets_cache", "captions_cache", "logs"]:
        os.makedirs(d, exist_ok=True)


_ensure_working_dirs()
_bootstrap_secrets()


@app.route("/")
def health():
    return "OK - PulseRankd trigger server is running", 200


@app.route("/run-pipeline")
def run_pipeline():
    token = request.args.get("token", "")
    expected = os.environ.get("TRIGGER_SECRET")
    if not expected or token != expected:
        return jsonify({"error": "unauthorized"}), 403

    if not RUN_LOCK.acquire(blocking=False):
        return jsonify({"status": "already running, skipped"}), 429

    try:
        # Imported here (not top-level) so the health check above still works
        # even if a dependency is missing/misconfigured.
        from main import run as run_main_pipeline

        privacy = os.environ.get("SHORTS_PRIVACY", "private")
        run_main_pipeline(manual_topic=None, dry_run=False, privacy=privacy)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"Pipeline run failed: {e}")
        return jsonify({"status": "error", "detail": str(e)}), 500
    finally:
        RUN_LOCK.release()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
