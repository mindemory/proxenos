"""Observer clones: one per source, each turning a month of raw data into notes about me.

An observer only sees my side: my own messages, my sent mail, my plays and activities.
Other people's words never leave the vault. Notes land in observations/<source>/YYYY-MM.md
and are redone whenever that month's raw data changes, so the current month keeps up as it
fills in. Timestamps are shown in this machine's local time.
"""

import json
import os
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from twin import llm

# Below this much rendered text a month says too little to be worth a model call.
MIN_CHARS = 400
# About 150k tokens. Longer months are cut, and the note says so.
MAX_CHARS = 600_000


def _local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone()


def _stamp(ts: str) -> str:
    return _local(ts).strftime("%m-%d %a %H:%M")


def render_whatsapp(records: list[dict]) -> str:
    lines = []
    for r in records:
        words = r["text"] or r["caption"]
        if r["from_me"] and words:
            where = f"{r['chat_name'] or 'unknown'} ({r['chat_type']})"
            lines.append(f"{_stamp(r['ts'])} to {where}: {words}")
    return "\n".join(lines)


def render_slack(records: list[dict]) -> str:
    lines = []
    for r in records:
        if r["from_me"] and r["text"]:
            reply = " (thread reply)" if r["is_reply"] else ""
            lines.append(f"{_stamp(r['ts'])} in {r['channel_name']}{reply}: {r['text']}")
    return "\n".join(lines)


def render_email(records: list[dict]) -> str:
    parts = []
    for r in records:
        body = (r["body_new"] or "").strip()
        if r["from_me"] and (body or r["subject"]):
            recipients = len(r["to"] or []) + len(r["cc"] or [])
            parts.append(
                f"--- {_stamp(r['ts'])} to {recipients} recipient(s), "
                f"subject: {r['subject']}\n{body[:2000]}"
            )
    return "\n".join(parts)


def render_spotify(records: list[dict]) -> str:
    plays = [r for r in records if r["ms_played"] and not r["incognito"]]
    if not plays:
        return ""
    minutes = Counter()
    hours = Counter()
    skipped = sum(bool(r["skipped"]) for r in plays)
    for r in plays:
        what = f"{r['artist']} (artist)" if r["kind"] == "track" else f"{r['show']} ({r['kind']})"
        minutes[what] += r["ms_played"] / 60000
        hours[_local(r["ts"]).hour] += r["ms_played"] / 60000
    tracks = Counter()
    for r in plays:
        if r["kind"] == "track":
            tracks[f"{r['track']} by {r['artist']}"] += 1
    total = sum(minutes.values())
    lines = [f"{len(plays)} plays, {total / 60:.1f} hours, {skipped / len(plays):.0%} skipped."]
    lines.append("Top artists and shows by minutes:")
    lines += [f"  {name}: {m:.0f} min" for name, m in minutes.most_common(40)]
    lines.append("Most played tracks:")
    lines += [f"  {name}: {n} plays" for name, n in tracks.most_common(25)]
    lines.append("Listening by hour of day (minutes):")
    lines.append("  " + ", ".join(f"{h:02d}h {hours[h]:.0f}" for h in range(24)))
    return "\n".join(lines)


def render_strava(records: list[dict]) -> str:
    lines = []
    for r in records:
        km = (r["distance_m"] or 0) / 1000
        mins = (r["moving_time_s"] or 0) / 60
        extra = f", avg HR {r['average_heartrate']:.0f}" if r["average_heartrate"] else ""
        lines.append(
            f"{_stamp(r['ts'])} {r['sport_type']} '{r['name']}': {km:.1f} km in {mins:.0f} min, "
            f"{r['total_elevation_gain_m'] or 0:.0f} m up{extra}, {r['kudos_count'] or 0} kudos"
        )
    return "\n".join(lines)


_SOURCES: dict[str, tuple[str, Callable[[list[dict]], str]]] = {
    "whatsapp": ("their own WhatsApp messages (personal chat)", render_whatsapp),
    "slack": ("their own Slack messages (work chat)", render_slack),
    "email": ("their own sent email", render_email),
    "spotify": ("a summary of their Spotify listening", render_spotify),
    "strava": ("their Strava activities", render_strava),
}
# Stream directories that hold one source's monthly files; the trailing name is dropped
# from the observation path (raw/slack/<team>/messages → observations/slack/<team>).
_STREAM_DIRS = {"messages", "plays", "activities"}


def streams(vault: Path) -> list[tuple[str, Path]]:
    """Every raw stream with monthly files, as (observation name, directory)."""
    found = []
    for month_file in sorted((vault / "raw").glob("**/*.jsonl")):
        directory = month_file.parent
        parts = list(directory.relative_to(vault / "raw").parts)
        if parts[-1] in _STREAM_DIRS:
            parts.pop()
        name = "/".join(parts)
        if parts[0] in _SOURCES and (name, directory) not in found:
            found.append((name, directory))
    return found


def pending(vault: Path, since: str | None = None) -> list[tuple[str, Path, Path]]:
    """Months whose raw file is newer than its note: (name, raw month file, note path)."""
    todo = []
    for name, directory in streams(vault):
        for month_file in sorted(directory.glob("*.jsonl")):
            if since and month_file.stem < since:
                continue
            note = vault / "observations" / name / f"{month_file.stem}.md"
            if not note.exists() or note.stat().st_mtime < month_file.stat().st_mtime:
                todo.append((name, month_file, note))
    return todo


def render(name: str, month_file: Path) -> str:
    with month_file.open(encoding="utf-8") as f:
        records = [json.loads(line) for line in f]
    return _SOURCES[name.split("/")[0]][1](records)


def observe(vault: Path, since: str | None = None, dry_run: bool = False) -> dict[str, int]:
    stats = Counter()
    person = os.environ.get("TWIN_NAME", "the person")
    for name, month_file, note in pending(vault, since):
        text = render(name, month_file)
        if len(text) < MIN_CHARS:
            stats["too_little"] += 1
            continue
        stats["chars"] += len(text)
        if dry_run:
            stats["would_observe"] += 1
            continue
        cut = ""
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS]
            cut = "\n\n(This month was longer than one request allows; only its start is shown.)"
        source = _SOURCES[name.split("/")[0]][0]
        answer = llm.ask(
            f"Month: {month_file.stem}. Source: {source}.\n\n{text}{cut}",
            system=_OBSERVER_SYSTEM.format(person=person),
            effort="medium",
        )
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(f"# {name}, {month_file.stem}\n\n{answer.strip()}\n", encoding="utf-8")
        stats["observed"] += 1
    # Roughly four characters per token: enough to see what a backfill will cost.
    stats["est_input_tokens"] = stats.pop("chars", 0) // 4
    return dict(stats)


_OBSERVER_SYSTEM = """\
You are one of several observers helping build a faithful model of {person}: a digital twin \
that has to think, choose and write the way they do. You see one month of one data source, \
and only {person}'s own side of it. Write notes that a later step will merge with notes from \
other sources and months.

Write markdown under these headings, skipping any the source can't speak to:
## Focus: what occupied them this month (projects, events, plans, problems).
## Interests: topics, ideas, things they read, shared or listened to, and how intensely.
## People: who they gave attention to and in what role. Names only as they appear; never \
infer anything sensitive about other people.
## Voice: how they write in this register (length, tone, humor, punctuation, languages, \
recurring phrases), with 3 to 5 short verbatim examples of their own phrasing.
## Mood and rhythm: energy, stress, time of day, routines.
## Changes: anything that looks new or different from a settled pattern.
## Open questions: what this month raises that the data can't answer.

Stick to what the data shows and say so when something isn't visible. Refer to them as \
{person} and don't assume pronouns. Keep it under about 600 words."""
