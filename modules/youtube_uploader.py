"""
Uploads the finished video to YouTube via the Data API v3 (free, OAuth-based).

First run opens a browser to authorize; after that, token.json is cached
and reused automatically.

Quota note: each upload costs ~1600 units out of your 10,000/day free quota,
so you can upload ~6 videos/day on the free tier before hitting the cap.
"""
import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# NOTE: broadened from upload-only to full youtube scope (read upload history
# for topic-repeat avoidance) PLUS yt-analytics.readonly (read per-video
# retention/watch-time for performance_tracker.py's "winner repeat" system).
# If you're upgrading from an older token.pickle with a narrower scope,
# delete token.pickle and re-authenticate once to pick up the new scope.
SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
CLIENT_SECRETS_FILE = "client_secret.json"
TOKEN_FILE = "token.pickle"


def _get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                raise RuntimeError(
                    f"{CLIENT_SECRETS_FILE} not found. Download OAuth client JSON from "
                    "Google Cloud Console -> APIs & Services -> Credentials -> "
                    "Create Credentials -> OAuth client ID -> Desktop app."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return creds


def _get_authenticated_service():
    return build("youtube", "v3", credentials=_get_credentials())


def _get_analytics_service():
    """Used by performance_tracker.py to read retention/watch-time metrics."""
    return build("youtubeAnalytics", "v2", credentials=_get_credentials())


def get_recent_video_titles(max_results=20):
    """
    Returns titles of your channel's most recent uploads (any privacy status),
    used to avoid picking a trending topic too similar to something already
    posted. This reads real channel state, so it survives across server
    restarts/redeploys even when local disk doesn't.
    """
    youtube = _get_authenticated_service()

    channels_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = channels_resp.get("items", [])
    if not items:
        return []

    uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    playlist_resp = youtube.playlistItems().list(
        part="snippet",
        playlistId=uploads_playlist_id,
        maxResults=max_results,
    ).execute()

    return [item["snippet"]["title"] for item in playlist_resp.get("items", [])]


def upload_short(video_path, title, description, hashtags, privacy_status="public"):
    """
    privacy_status: "public", "unlisted", or "private" (use "private" while testing!)
    """
    youtube = _get_authenticated_service()

    tags = [h.lstrip("#") for h in hashtags]
    full_description = f"{description}\n\n" + " ".join(hashtags)

    body = {
        "snippet": {
            "title": title[:100],
            "description": full_description[:5000],
            "tags": tags[:500],
            "categoryId": "22",  # People & Blogs; change if you have a fixed niche
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"Uploaded: https://youtube.com/shorts/{video_id}")
    return video_id
