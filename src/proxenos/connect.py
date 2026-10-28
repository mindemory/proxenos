"""`proxenos connect`: every source, whether it's connected and when it was last read, as JSON.

The page's Connect view shows this, so it holds only names, addresses, handles and dates, never
a token, password or key. Connected means Proxenos has what it needs to read the source: a
sign-in or a setting for a live source, a setting or data for a folder, data in the vault for a
download. Last read is the newest change to the source's files under raw/.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

from proxenos.config import env
from proxenos.ingest import gmail, slack, whatsapp

# How each source gets in, in the order the page lists them.
LIVE = ("gmail", "whatsapp", "slack", "strava", "bluesky", "mentions")
DOWNLOADS = (
    "linkedin",
    "twitter",
    "instagram",
    "facebook",
    "threads",
    "calendar",
    "drive",
    "photos",
    "keep",
    "gtasks",
    "youtube",
    "chrome",
    "email",
    "spotify",
    "letterboxd",
)
FOLDERS = ("notes", "website")


def report(vault: Path, whatsapp_db: Path = whatsapp.DEFAULT_DB) -> dict:
    raw = vault / "raw"
    accounts = [
        {
            "name": name,
            "address": address,
            "sign_in": "google" if secret.startswith(gmail.OAUTH) else "app_password",
            "last_read": _last_read(raw / "email" / name),
        }
        for name, (address, secret) in sorted(gmail.accounts().items())
    ]
    # Mail folders no Gmail account reads came from an mbox download.
    mbox = [d for d in _subdirs(raw / "email") if d.name not in {a["name"] for a in accounts}]
    store = whatsapp.store_problem(whatsapp_db)
    google_client = os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET")
    strava_saved = vault / "state" / "strava_token.json"  # the Strava ingester's latest token
    strava_token = os.environ.get("STRAVA_REFRESH_TOKEN") or strava_saved.exists()

    # What tells us a source is set up. A download or a folder also counts once it's been read.
    set_up = {
        "gmail": bool(accounts),
        "whatsapp": store is None,
        "slack": bool(slack.tokens()),
        "strava": bool(os.environ.get("STRAVA_CLIENT_ID") and strava_token),
        "bluesky": bool(env("BLUESKY_HANDLE")),
        "mentions": bool(env("FULL_NAME") or env("NAME")),
        "spotify": bool(env("SPOTIFY_EXPORT")),
        "website": bool(env("WEBSITE_REPO")),
    }
    # What stops the page's button from working, if anything.
    problems = {"gmail": None if google_client else "no_google_client", "whatsapp": store}
    folders = {"gmail": [raw / "email" / a["name"] for a in accounts], "email": mbox}

    sources = []
    for how, ids in (("live", LIVE), ("download", DOWNLOADS), ("folder", FOLDERS)):
        for source in ids:
            last_read = _last_read(*folders.get(source, [raw / source]))
            read_before = how != "live" and last_read is not None
            sources.append(
                {
                    "id": source,
                    "how": how,
                    "connected": set_up.get(source, False) or read_before,
                    "last_read": last_read,
                    "problem": problems.get(source),
                    "detail": (env("BLUESKY_HANDLE") or None) if source == "bluesky" else None,
                    "accounts": accounts if source == "gmail" else [],
                }
            )
    return {"sources": sources}


def _subdirs(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []


def _last_read(*folders: Path) -> str | None:
    """When any month file under these folders last changed, as UTC ISO, or None."""
    times = [f.stat().st_mtime for d in folders if d.is_dir() for f in d.rglob("*.jsonl")]
    if not times:
        return None
    newest = datetime.fromtimestamp(max(times), UTC)
    return newest.isoformat(timespec="seconds").replace("+00:00", "Z")
