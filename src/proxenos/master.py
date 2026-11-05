"""The master: the only writer of the self-model, and the loop that keeps it current.

A run pulls whatever sources can sync unattended, has the observers write notes on new or
changed months, then folds every note (and the user's reactions to clone output) into vault/self/.
Fast-moving files are rewritten directly. Slow ones (who they are, how they write) only change
through proposals in self/proposals/ that the user accepts with `proxenos master accept`. The
vault is its own local git repo tracking self/ and observations/, so every change to the model
of the user is a commit.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos import fidelity, importer, llm, memory, observe, outbox, plans, vectors
from proxenos.clones import recall, tasks, work
from proxenos.config import env, env_key
from proxenos.ingest import (
    applemail,
    beeper,
    bluesky,
    docs,
    gcalendar,
    gmail,
    letterboxd,
    maccalendar,
    mentions,
    microsoft,
    slack,
    slackdump,
    spotify,
    strava,
    website,
    whatsapp,
)

# name → what the file holds; consolidation writes exactly these.
SELF_FILES = {
    "identity": "who they are: roles, life situation, current projects, values, how they decide",
    "interests": "topics with weight (high/medium/low), last active month and trend "
    "(rising/stable/fading), most important first",
    "taste": "what they read, listen to and pick versus skip, and why",
    "voice": "how they write in each register (personal chat, work chat, email), with short "
    "verbatim examples of their own phrasing",
    "routines": "daily and weekly rhythm: work hours, exercise, music, sleep and activity",
    "open_questions": "what the self-model is unsure about, phrased as questions to ask them",
}
VECTOR_SECONDS = 240  # of embedding in a sync; the rest waits for the next one
SLOW = {"identity", "voice"}

# The raw/ folders each unattended source vouches for when it syncs, so one checked with nothing
# new shows as fresh on the page, not behind (state/checked.json). Beeper's are the chat apps it
# has brought in before. Spotify's export is as new as the file the user downloaded, so it
# vouches only once its plays come in live.
_CHECKS = {
    "whatsapp": ("whatsapp",),
    "letterboxd": ("letterboxd",),
    "gmail": ("email",),
    "microsoft": ("email", "calendar"),
    "gcalendar": ("calendar",),
    "applemail": ("email",),
    "maccalendar": ("calendar",),
    "docs": ("notes",),
    "strava": ("strava",),
    "slack": ("slack",),
    "slackdump": ("slack",),
    "website": ("website",),
    "mentions": ("mentions",),
    "bluesky": ("bluesky",),
}
CHECKED = Path("state", "checked.json")

# Sources that sync unattended, each with what tells us it's set up.
_UNATTENDED = [
    (whatsapp, lambda: sys.platform == "darwin"),  # WhatsApp for Mac; Windows' has no store
    (spotify, lambda: env("SPOTIFY_EXPORT") or spotify.live()),
    (letterboxd, lambda: env("LETTERBOXD_USER")),
    (gmail, gmail.accounts),
    (microsoft, microsoft.accounts),
    (gcalendar, gcalendar.accounts),
    (applemail, applemail.available),
    (maccalendar, maccalendar.available),
    (docs, docs.folders),
    (beeper, lambda: os.environ.get("BEEPER_ACCESS_TOKEN")),
    (strava, lambda: os.environ.get("STRAVA_CLIENT_ID")),
    (slack, slack.tokens),
    (slackdump, slackdump.archives),
    (website, lambda: env("WEBSITE_REPO")),
    (mentions, lambda: env("FULL_NAME")),
    (bluesky, lambda: env("BLUESKY_HANDLE")),
]


def run(vault: Path, since: str | None = None) -> dict[str, int]:
    stats = sync(vault)
    stats.update(observe.observe(vault, since))
    stats.update(consolidate(vault))
    return stats


def _checks(vault: Path, name: str) -> tuple[str, ...]:
    """The raw/ folders a source that just synced vouches for."""
    if name == "beeper":
        return beeper.sources(vault)
    if name == "spotify":
        return ("spotify",) if spotify.live(vault) else ()
    return _CHECKS.get(name, ())


def _write_checked(vault: Path, checked: dict[str, str]) -> None:
    """Add when each raw/ folder was last checked to state/checked.json, which the page reads."""
    path = vault / CHECKED
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    data = (old if isinstance(old, dict) else {}) | checked
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sync(vault: Path) -> dict[str, int]:
    """Import new downloads, refresh every set-up source and the memory built from them. None
    of that needs a model; with a key set, chats newly waiting on the user also get a reply
    drafted, a few per sync, and once an hour, when something was said since, the task list,
    its plans and the drafts waiting are brought up to date with it."""
    os.environ.setdefault(env_key("FULL_NAME"), env("NAME"))
    stats = {"sources_synced": 0, "sources_failed": 0}
    stats.update(importer.run(vault))
    checked: dict[str, str] = {}
    for module, configured in _UNATTENDED:
        if not configured():
            continue
        parser = argparse.ArgumentParser()
        if hasattr(module, "add_arguments"):
            module.add_arguments(parser)
        name = getattr(module, "__name__", "source").rsplit(".", 1)[-1]
        try:
            module.run(vault, parser.parse_args([]))
            stats["sources_synced"] += 1
            when = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            checked |= dict.fromkeys(_checks(vault, name), when)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - one broken source must not stop the rest
            stats["sources_failed"] += 1
            reason = str(e) if isinstance(e, SystemExit) else f"{type(e).__name__}: {e}"
            print(f"sync: {name} failed ({' '.join(reason.split())[:200]})", file=sys.stderr)
    if checked:
        _write_checked(vault, checked)
    # What the sources just brought in becomes searchable, then today's recall is redone from it.
    # Both are derived data: a failure here never costs the sync.
    try:
        stats["records_indexed"] = memory.build(vault).get("records_indexed", 0)
    except (Exception, SystemExit):  # noqa: BLE001 - search is a convenience, not the sync
        stats["index_failed"] = 1
    else:
        try:
            stats["recall_triggers"] = recall.recall(vault)["triggers_with_memories"]
        except (Exception, SystemExit):  # noqa: BLE001
            stats["recall_failed"] = 1
        # Then a few minutes of the vector index, newest first, when the embedding model runs.
        try:
            if vectors.available():
                stats |= vectors.update(vault, seconds=VECTOR_SECONDS)
        except (Exception, SystemExit):  # noqa: BLE001
            stats["vectors_failed"] = 1
    # How close the twin's replies came to what was sent: no model, and cheap.
    try:
        stats |= fidelity.measure(vault)
    except (Exception, SystemExit):  # noqa: BLE001
        stats["fidelity_failed"] = 1
    # Then the outbox, after the measure it goes by: off unless the user switched it on.
    try:
        stats |= outbox.run(vault)
    except (Exception, SystemExit):  # noqa: BLE001
        stats["outbox_failed"] = 1
    # Chats newly waiting on the user get a reply drafted as they come in. Only with a key, and
    # only chats with no draft yet, so a sync with nothing new waiting costs nothing.
    if llm.configured():
        try:
            stats["replies_drafted"] = work.replies(vault)["drafts_written"]
        except (Exception, SystemExit) as e:  # noqa: BLE001 - drafts are extra, not the sync
            stats["replies_failed"] = 1
            print(f"sync: replies failed ({' '.join(str(e).split())[:200]})", file=sys.stderr)
        # Then the tasks, so a plan made today reaches the calendar and a draft someone else
        # made moot leaves Drafts before the night run. After fidelity: a draft that went out is
        # marked sent, not overtaken.
        try:
            if tasks.due(vault):
                done = tasks.plan(vault, days=tasks.SYNC_DAYS)
                stats |= {"tasks_new": done["new"], "drafts_overtaken": done["overtaken"]}
                stats["plans"] = done["plans"]
        except (Exception, SystemExit) as e:  # noqa: BLE001 - tasks are extra, not the sync
            stats["tasks_failed"] = 1
            print(f"sync: tasks failed ({' '.join(str(e).split())[:200]})", file=sys.stderr)
    # Without a task run, the plans again with no model, so a booking in the mail reaches the
    # calendar on every sync.
    try:
        if "plans" not in stats:
            stats["plans"] = plans.refresh(vault)
    except (Exception, SystemExit):  # noqa: BLE001 - the calendar is extra, not the sync
        stats["plans_failed"] = 1
    return stats


def consolidate(vault: Path) -> dict[str, int]:
    notes = sorted((vault / "observations").glob("**/*.md"), key=lambda p: (p.stem, str(p)))
    if not notes:
        return {"self_files_written": 0}
    person = env("NAME", "the person")
    self_dir = vault / "self"
    current = {name: _read(self_dir / f"{name}.md") for name in SELF_FILES}

    # The newest months that fit the model: the current self-model carries what the older ones said.
    texts = [note.read_text(encoding="utf-8") for note in notes]
    room = llm.fit(sum(map(len, texts)), overhead=60_000)
    while len(texts) > 1 and sum(map(len, texts)) > room:
        texts.pop(0)
    left_out = len(notes) - len(texts)
    heading = "# Observations, oldest first"
    if left_out:
        heading += f" (the {left_out} oldest left out, to fit)"
    prompt = [heading + "\n", *texts]
    if any(current.values()):
        prompt.append("\n# The current self-model\n")
        prompt += [f"## {name}.md\n{text}" for name, text in current.items() if text]
    reactions = _recent_reactions(vault)
    if reactions:
        prompt.append("\n# Their recent reactions to their digital twin's picks\n" + reactions)

    answer = llm.ask(
        "\n\n".join(prompt),
        system=_CONSOLIDATE_SYSTEM.format(
            person=person,
            files="\n".join(f"- {name}: {what}" for name, what in SELF_FILES.items()),
        ),
        schema=_SCHEMA,
        effort="high",
        max_tokens=64000,
    )

    written = proposed = 0
    (self_dir / "proposals").mkdir(parents=True, exist_ok=True)
    for name in SELF_FILES:
        text = answer[name].strip() + "\n"
        if text.strip() == current[name].strip():
            continue
        if name in SLOW and current[name]:
            (self_dir / "proposals" / f"{name}.md").write_text(text, encoding="utf-8")
            proposed += 1
        else:
            (self_dir / f"{name}.md").write_text(text, encoding="utf-8")
            written += 1
    today = datetime.now().strftime("%Y-%m-%d")
    with (self_dir / "CHANGELOG.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## {today}\n\n{answer['changelog'].strip()}\n")
    _commit(vault, f"consolidate {today}")
    return {"self_files_written": written, "self_files_proposed": proposed}


def accept(vault: Path) -> dict[str, int]:
    accepted = 0
    for proposal in sorted((vault / "self" / "proposals").glob("*.md")):
        proposal.replace(vault / "self" / proposal.name)
        accepted += 1
    if accepted:
        _commit(vault, f"accept {accepted} proposal(s)")
    return {"accepted": accepted}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _recent_reactions(vault: Path, days: int = 30) -> str:
    feedback = vault / "tracker" / "feedback.jsonl"
    if not feedback.exists():
        return ""
    titles = {}
    for month_file in (vault / "tracker" / "items").glob("*.jsonl"):
        for line in month_file.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            titles[item["id"]] = f"{item['title']} [{item.get('interest') or '?'}]"
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    lines = []
    for line in feedback.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["action"] != "open" and event["ts"] >= cutoff and event["item_id"] in titles:
            lines.append(f"- {event['action']}: {titles[event['item_id']]}")
    return "\n".join(lines)


def _commit(vault: Path, message: str) -> None:
    """Commit self/ and observations/ in the vault's own local git repo (never pushed). Without
    git on this computer (Windows has none unless installed) the history is skipped, not the run."""
    if shutil.which("git") is None:
        return

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(vault), *args], check=False, capture_output=True, text=True
        )

    if not (vault / ".git").exists():
        git("init", "-q")
        (vault / ".gitignore").write_text("/*\n!/.gitignore\n!/self/\n!/observations/\n")
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode:
        # Commit as you when git knows who you are, else as Proxenos: this history never leaves
        # the vault, and a computer with no git identity set (most people's) would refuse.
        known = git("config", "user.email").returncode == 0
        identity = (
            [] if known else ["-c", "user.name=Proxenos", "-c", "user.email=proxenos@localhost"]
        )
        subprocess.run(
            ["git", "-C", str(vault), *identity, "commit", "-q", "-m", message],
            check=False,
            capture_output=True,
            text=True,
        )


_SCHEMA = {
    "type": "object",
    "properties": {name: {"type": "string"} for name in [*SELF_FILES, "changelog"]},
    "required": [*SELF_FILES, "changelog"],
    "additionalProperties": False,
}

_CONSOLIDATE_SYSTEM = """\
You maintain the self-model of {person}: the single source of truth that every part of their \
digital twin reads before it thinks, chooses or writes on their behalf. You are given dated \
observations from several sources (each written from {person}'s own messages, mail, \
listening and activity), possibly the current self-model, and their recent reactions to \
items picked for them.

Write each of these files as markdown:
{files}

Rules:
- Evidence only. Each claim should be traceable to observations; say how confident you are \
when evidence is thin, and put real uncertainty in open_questions.
- Time matters. Recent months describe who they are now. When older evidence conflicts, \
keep the present view and note the shift ("until early 2025 ..., since then ...").
- Their reactions outrank inference: an item marked not_me is strong evidence against that \
interest as the self-model understood it.
- Be specific to {person}. Generic traits that would fit anyone add nothing.
- Refer to them as {person} and don't assume pronouns. No sensitive inferences about other \
people.
- changelog: a short bullet list of what changed compared with the current self-model, or \
"Initial build" if there is none."""
