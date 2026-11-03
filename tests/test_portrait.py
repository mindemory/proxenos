"""The month cards on a synthetic vault: the mood of the user's own writing a day at a time and
its roll-up, artists' genres from MusicBrainz cached and asked by name alone, how mood and music
moved together, the card's JSON, and other people's words never scored or sent. The network and
the model are faked out; no real data."""

import json
import math
import os
import stat
import time
import urllib.parse
from datetime import UTC, datetime, timedelta

import pytest

from proxenos import cli, llm, memory, mood, musicbrainz, privacy
from proxenos.clones import portrait, rhythms

NOW = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
# Someone else's words, as dark as can be: if they were scored, the days would turn heavy.
THEIRS = "PRIVATE-THEIRS I hate this, it is awful, terrible and miserable news."
BRIGHT = ["I love this, so happy today!", "Thanks so much, this is wonderful.", "Great news!"]
HEAVY = ["I am so tired and sad today.", "This is awful, I hate it.", "Ugh, a terrible day."]


def jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def wa(n, ts, text, me, chat="Asha"):
    return {
        "id": f"m{n}", "ts": ts, "chat_id": f"{chat}@s.whatsapp.net", "chat_name": chat,
        "chat_type": "direct", "from_me": me, "sender_id": None if me else "1",
        "sender_name": None if me else chat, "kind": "text", "wa_type": 0, "text": text,
    }  # fmt: skip


def play(n, ts, artist, minutes):
    return {"id": f"p{n}", "ts": ts, "kind": "track", "ms_played": minutes * 60_000,
            "incognito": False, "artist": artist, "track": "A Song"}  # fmt: skip


def bright(day):
    """Days of March whose words are bright: every other one, and a run in the third week."""
    return day % 2 == 1 or 15 <= day <= 18


@pytest.fixture
def new_york(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("the time zone is set through tzset, which Windows doesn't have")
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def vault(tmp_path, monkeypatch, new_york):
    """March 2026 up to the 20th: three messages a day of the user's own, bright or heavy, an
    hour of upbeat music on bright days and of melancholic music on heavy ones, someone else's
    dark words every day, mail with a quoted reply, a note and a document; and a message in each
    of the three months before, for the usual month."""
    monkeypatch.setenv("PROXENOS_NAME", "Sam Doe")
    monkeypatch.setenv("PROXENOS_EMAILS", "me@example.com")
    v = tmp_path / "vault"
    raw = v / "raw"
    messages, plays = [], []
    for day in range(1, 21):
        ts = f"2026-03-{day:02d}T15:00:00Z"
        said = BRIGHT if bright(day) else HEAVY
        messages += [wa(day * 10 + k, ts, text, True) for k, text in enumerate(said)]
        messages.append(wa(day * 10 + 9, ts, THEIRS, False))
        plays.append(play(day, ts, "Sunny Days" if bright(day) else "Grey Rain", 60))
    jsonl(raw / "whatsapp" / "messages" / "2026-03.jsonl", messages)
    for month, n in (("2025-12", 40), ("2026-01", 60), ("2026-02", 50)):
        jsonl(
            raw / "whatsapp" / "messages" / f"{month}.jsonl",
            [wa(month, f"{month}-10T15:00:00Z", " ".join(["word"] * n), True)],
        )
    jsonl(raw / "spotify" / "plays" / "2026-03.jsonl", plays)
    jsonl(
        raw / "email" / "personal" / "2026-03.jsonl",
        [
            {"id": "e1", "ts": "2026-03-03T16:00:00Z", "from_me": True,
             "from_address": "me@example.com", "to": ["ben@example.com"], "subject": "Re: news",
             "body_new": "Lovely to hear, congratulations!",
             "body": f"Lovely to hear, congratulations!\n\nOn Mon, Ben wrote:\n> {THEIRS}"},
            {"id": "e2", "ts": "2026-03-04T16:00:00Z", "from_me": True,
             "from_address": "me@example.com", "to": ["ben@example.com"], "subject": "Fwd",
             "body_new": "", "body": THEIRS},  # all forwarded: nothing of theirs to score
            {"id": "e3", "ts": "2026-03-05T16:00:00Z", "from_me": False,
             "from_address": "ben@example.com", "to": ["me@example.com"], "subject": "Hi",
             "body_new": THEIRS, "body": THEIRS},
        ],
    )  # fmt: skip
    jsonl(
        raw / "keep" / "notes" / "2026-03.jsonl",
        [{"id": "k1", "ts": "2026-03-06T12:00:00Z", "from_me": True, "title": "Garden",
          "text": "Plant the beans after the frost"}],
    )  # fmt: skip
    jsonl(
        raw / "drive" / "docs" / "2026-03.jsonl",
        [
            {"id": "d1", "ts": "2026-03-07T12:00:00Z", "path": "Essay.docx", "ext": "docx",
             "title": "Essay", "text": "An essay", "words": 1200},
            {"id": "d2", "ts": "2026-03-07T12:00:00Z", "path": "Paper.pdf", "ext": "pdf",
             "title": "Paper", "text": "A paper someone wrote", "words": 9000},
        ],
    )  # fmt: skip
    rhythms._save(
        rhythms._labels_path(v),
        {
            "artists": {
                "Sunny Days": {"genre": "pop", "moods": ["upbeat"]},
                "Grey Rain": {"genre": "folk/acoustic", "moods": ["melancholic"]},
            }
        },
    )
    memory.build(v)
    return v


@pytest.fixture
def hosted(monkeypatch):
    """A hosted model set up: the user's words must never reach it."""
    monkeypatch.setattr(llm, "current", lambda: "claude-opus-5-5")
    monkeypatch.setattr(llm, "configured", lambda: True)
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("a hosted model call"))


@pytest.fixture
def local(monkeypatch):
    """A model on this computer, faked: each day's emotions by its words, and a story."""
    monkeypatch.setattr(llm, "current", lambda: "ollama:test")
    monkeypatch.setattr(llm, "configured", lambda: True)
    asked = []

    def ask(prompt, *, system=None, schema=None, **kwargs):
        asked.append((prompt, system, schema))
        if "days" in schema["properties"]:
            days = [b.split("\n")[0] for b in prompt.split("## ")[1:]]
            return {
                "days": [
                    {"day": d, "emotions": ["joyful", "grateful", "dreamy"]}
                    if "love" in block or "Lovely" in block
                    else {"day": d, "emotions": ["Tired", "sad"]}
                    for d, block in zip(days, prompt.split("## ")[1:])
                ]
            }
        return {"text": "  You had a bright month,   with some heavy days. "}

    monkeypatch.setattr(llm, "ask", ask)
    return asked


# The mood of a day, and of a month


def test_a_day_has_a_valence_only_from_enough_sentences_with_a_feeling():
    assert mood.day(["ok", "see you at 5", "on my way"])["valence"] is None  # not middling
    assert mood.day(["I love it!", "Great"])["valence"] is None  # two aren't enough
    found = mood.day(["I love it! Great news.", "So sad and awful. https://x.example/a <@U12>"])
    assert found["scored"] == 3 and found["sentences"] == 3
    each = [mood.score(s) for s in ("I love it!", "Great news.", "So sad and awful.")]
    assert found["valence"] == round(sum(each) / 3, 3)
    assert mood.pieces("one. two!\nthree <!here> www.example.com") == ["one.", "two!", "three"]
    # A day's words are kept only as a hash.
    assert len(mood.digest(["I love it!"])) == 16 and "love" not in mood.digest(["I love it!"])


def test_a_month_rolls_up_into_its_top_moods_arc_and_spread():
    days = [
        # The week of Mar 2: bright and grateful.
        {"day": "2026-03-02", "valence": 0.6, "emotions": ["grateful", "calm"]},
        {"day": "2026-03-03", "valence": 0.5, "emotions": ["grateful"]},
        # The week of Mar 9: heavy and tired.
        {"day": "2026-03-09", "valence": -0.4, "emotions": ["tired", "sad"]},
        {"day": "2026-03-10", "valence": -0.2, "emotions": ["tired"]},
        {"day": "2026-03-11", "valence": 0.1, "emotions": []},
        # One day in a week can't be the brightest or the hardest.
        {"day": "2026-03-16", "valence": 0.9, "emotions": ["joyful"]},
        {"day": "2026-03-17", "valence": None, "emotions": []},
    ]
    found = mood.roll_up(days)
    assert found["days"] == 6 and found["labelled_days"] == 5
    assert found["valence"] == round((0.6 + 0.5 - 0.4 - 0.2 + 0.1 + 0.9) / 6, 3)
    assert [(t["name"], t["days"], t["share"]) for t in found["top"]] == [
        ("grateful", 2, 0.4),
        ("tired", 2, 0.4),  # ties go in EMOTIONS' order
        ("joyful", 1, 0.2),
    ]
    assert [t["bright"] for t in found["top"]] == [True, False, True]
    assert found["tone"] == {"brighter": 3, "mixed": 1, "heavier": 2}
    arc = found["arc"]
    assert [(w["start"], w["days"]) for w in arc["weeks"]] == [
        ("2026-03-02", 2),
        ("2026-03-09", 3),
        ("2026-03-16", 1),
    ]
    assert arc["best"]["start"] == "2026-03-02" and arc["best"]["emotion"] == "grateful"
    assert arc["hardest"]["start"] == "2026-03-09" and arc["hardest"]["valence"] == -0.167
    assert found["variability"]["word"] == "changeable" and found["variability"]["sd"] > 0.22
    assert mood.roll_up(days[:2])["variability"] == {"sd": None, "word": None}


def test_emotions_come_only_from_a_model_on_this_computer(hosted):
    assert mood.local() is False
    assert mood.label({"2026-03-01": BRIGHT}) == {}  # nothing asked, nothing back


def test_the_local_model_labels_a_month_in_one_call_held_to_the_vocabulary(local):
    found = mood.label({"2026-03-01": BRIGHT, "2026-03-02": HEAVY})
    assert len(local) == 1
    prompt, system, schema = local[0]
    fence = system.split("inside <", 1)[1].split(">", 1)[0]
    assert prompt.startswith(f"<{fence}>") and prompt.endswith(f"</{fence}>")
    assert "## 2026-03-01" in prompt and "I love this" in prompt
    assert schema["properties"]["days"]["items"]["properties"]["emotions"]["items"]["enum"] == list(
        mood.EMOTIONS
    )
    # "dreamy" isn't in the vocabulary; "Tired" is, whatever its case.
    assert found == {"2026-03-01": ["joyful", "grateful"], "2026-03-02": ["tired", "sad"]}
    assert mood.held({"days": [{"day": "2026-04-01", "emotions": ["sad"]}]}, {"2026-03-01"}) == {}


# Genres from MusicBrainz


class FakeMusicBrainz:
    """MusicBrainz's genre list and artist search, keeping every request it was sent."""

    def __init__(self, artists):
        self.artists, self.requests = artists, []

    def __call__(self, request):
        self.requests.append(request)
        if "/genre/all" in request.full_url:
            return b"pop\nindie pop\nfolk\nfilmi\n"
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)["query"][0]
        name = json.loads(query.removeprefix("artist:"))
        return json.dumps({"artists": self.artists.get(name, [])}).encode()


def found_artist(name, score, tags, aliases=()):
    return {"id": f"mbid-{name}", "name": name, "score": str(score),
            "aliases": [{"name": a} for a in aliases],
            "tags": [{"name": t, "count": n} for t, n in tags]}  # fmt: skip


def test_genres_are_looked_up_by_artist_name_alone_and_cached(tmp_path, monkeypatch):
    fake = FakeMusicBrainz(
        {
            "Sunny Days": [
                found_artist("Sunny Days", 100, [("indie pop", 5), ("british", 9), ("happy", 2)]),
                found_artist("Sunny Days Band", 95, [("folk", 9)]),
            ],
            'The "Quote" Band': [
                found_artist("Other", 100, [("pop", 3)], aliases=['the  "QUOTE" band'])
            ],
            "Nobody": [found_artist("Nobody", 60, [("pop", 3)])],  # too weak a match
        }
    )
    waited = []
    played = {"Sunny Days": 9e6, 'The "Quote" Band': 5e6, "Nobody": 1e6, "Kiln": 1e5}
    stats = musicbrainz.look_up(tmp_path, played, limit=3, now=NOW, fetch=fake, wait=waited.append)

    assert stats == {"artists looked up": 3}
    urls = [r.full_url for r in fake.requests]
    assert urls[0] == f"{musicbrainz.API}/genre/all?fmt=txt"
    # One name a request, the most played first, and nothing else: no track, time or count.
    for url, name in zip(urls[1:], ["Sunny Days", 'The "Quote" Band', "Nobody"]):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        assert query == {"query": [f"artist:{json.dumps(name)}"], "limit": ["5"], "fmt": ["json"]}
    assert all(r.get_header("User-agent") == musicbrainz.USER_AGENT for r in fake.requests)
    assert len(waited) == 3 and all(0 < w <= musicbrainz.PACE for w in waited)  # one a second

    kept = musicbrainz.genres(tmp_path)
    assert kept == {
        # Tags on the genre list, most voted first; "happy" is a mood.
        "Sunny Days": {"genres": ["indie pop"], "moods": ["upbeat"]},
        'The "Quote" Band': {"genres": ["pop"], "moods": []},  # by its alias
    }
    on_disk = json.loads(musicbrainz.path(tmp_path).read_text())
    assert set(on_disk["unknown"]) == {"Nobody"} and "Kiln" not in json.dumps(on_disk)
    if os.name != "nt":
        assert stat.S_IMODE(musicbrainz.path(tmp_path).stat().st_mode) == 0o600

    # Kept: the next night asks only about the one not asked yet, with the genre list it has.
    fake.requests.clear()
    musicbrainz.look_up(tmp_path, played, limit=10, now=NOW, fetch=fake, wait=waited.append)
    assert [r.full_url for r in fake.requests] == [musicbrainz.query("Kiln")]
    # One with nothing found waits RETRY_DAYS.
    fake.requests.clear()
    later = NOW + timedelta(days=musicbrainz.RETRY_DAYS + 1)
    musicbrainz.look_up(tmp_path, played, limit=10, now=later, fetch=fake, wait=waited.append)
    asked = sorted(r.full_url for r in fake.requests if "/genre/all" not in r.full_url)
    assert asked == sorted([musicbrainz.query("Nobody"), musicbrainz.query("Kiln")])
    assert set(musicbrainz.MOOD_TAGS.values()) <= set(rhythms.MOODS)


def test_lookups_stop_when_switched_off_or_out_of_reach(tmp_path, monkeypatch):
    fake = FakeMusicBrainz({})
    monkeypatch.setenv("PROXENOS_MUSICBRAINZ", "off")
    assert musicbrainz.look_up(tmp_path, {"Sunny Days": 1}, fetch=fake) == {"musicbrainz off": 1}
    assert fake.requests == []
    monkeypatch.delenv("PROXENOS_MUSICBRAINZ")

    def down(request):
        raise OSError("unreachable")

    stats = musicbrainz.look_up(tmp_path, {"Sunny Days": 1}, now=NOW, fetch=down)
    assert stats["musicbrainz stopped"] == 1 and not musicbrainz.path(tmp_path).exists()


def test_the_privacy_screen_says_what_goes_where(tmp_path, monkeypatch):
    fake = FakeMusicBrainz({"Sunny Days": [found_artist("Sunny Days", 100, [("pop", 2)])]})
    played = {"Sunny Days": 2, "Nobody": 1}
    musicbrainz.look_up(tmp_path, played, now=NOW, fetch=fake, wait=lambda seconds: None)
    assert privacy.fetched(tmp_path)["music"] == {"on": True, "artists": 2}
    monkeypatch.setenv("PROXENOS_MUSICBRAINZ", "off")
    assert privacy.fetched(tmp_path)["music"]["on"] is False
    said = {part: (steps, what) for part, steps, what in privacy.SENDS}
    steps, what = said["Rhythms"]
    assert {"rhythms", "portrait", "mood"} <= set(steps)  # each call's step, as llm logs it
    assert "never a hosted one" in what and "Never other people's messages" in what


# How mood and music moved together


def test_correlations_on_a_fixed_example():
    found = portrait.correlate([1, 2, 3, 4, 5], [2, 4, 5, 4, 5])
    assert found["r"] == 0.775 and found["n"] == 5  # 6 / sqrt(60)
    z = math.atanh(6 / math.sqrt(60)) * math.sqrt(2)
    assert found["p"] == round(math.erfc(z / math.sqrt(2)), 3) == 0.145
    assert portrait.correlate([1, 2], [3, 4]) is None  # too few
    assert portrait.correlate([1, 1, 1, 1], [1, 2, 3, 4]) is None  # no spread

    rel = {"kind": "same day", "music": "upbeat", "r": 0.41, "n": 25, "p": 0.04}
    assert portrait.sentence(rel) == (
        "On days your writing was brighter, more of your music was upbeat (r = 0.41, 25 days, "
        "a moderate link). This doesn't say which led."
    )
    lagged = {"kind": "music then mood", "music": "melancholic", "r": -0.22, "n": 12, "p": 0.5}
    assert portrait.sentence(lagged) == (
        "After days more of your music was melancholic, your writing was heavier the next day "
        "(r = −0.22, 12 pairs of days, a weak link). A day apart fits the music shaping your "
        "mood, but doesn't show it. With this few days, it could be chance."
    )
    for text in (portrait.sentence(rel), portrait.sentence(lagged)):
        assert not any(w in text for w in ("because", "caused", "made you", "led to"))


def test_relations_on_days_of_music_and_mood():
    days = []
    for n in range(14):
        up = n % 2 == 0
        days.append(
            {
                "day": f"2026-03-{n + 1:02d}",
                "valence": 0.5 if up else -0.3,
                "music_hours": 1.0 if up else 0.5,
                "upbeat": 0.9 if up else 0.1,
                "melancholic": 0.1 if up else 0.8,
                "played": {"genre:pop": 60} if up else {"genre:folk": 60},
            }
        )
    heard = {"compared": [{"kind": "genre", "name": "pop"}, {"kind": "genre", "name": "folk"}]}
    found = {(r["kind"], r["music"]): r for r in portrait.relations(days, heard)}
    same = found[("same day", "upbeat")]
    assert same["r"] == 1.0 and same["n"] == 14 and same["notable"]
    assert found[("same day", "melancholic")]["r"] == -1.0
    # A day apart, the days alternate: upbeat music is followed by a heavier day.
    assert found[("music then mood", "upbeat")]["r"] == -1.0
    assert found[("music then mood", "upbeat")]["n"] == 13
    pop = found[("with", "pop")]
    assert (pop["with"], pop["without"], pop["days_with"], pop["days_without"]) == (0.5, -0.3, 7, 7)
    assert pop["text"].startswith("On days you played pop (15 minutes or more), your writing was ")
    assert "brighter than on days you didn't (0.50 against −0.30" in pop["text"]
    assert found[("next day with", "folk")]["text"].startswith("The day after you played folk")
    # The notable ones come first.
    notable = [r["notable"] for r in portrait.relations(days, heard)]
    assert notable[0] and notable == sorted(notable, reverse=True)


# The card


def test_the_card_holds_the_months_mood_music_and_writing(vault, hosted):
    card = portrait.make(vault, "2026-03", NOW)

    assert card["month"] == "2026-03" and card["complete"] is False  # March isn't over
    assert [d["day"] for d in card["days"]] == [f"2026-03-{n:02d}" for n in range(1, 21)]
    m = card["mood"]
    assert m["days"] == 20 and m["top"] == [] and m["by_model"] is False  # no local model
    assert m["tone"]["brighter"] == sum(bright(n) for n in range(1, 21))
    assert m["arc"]["best"]["start"] == "2026-03-16"  # the bright run
    assert m["variability"]["word"] == "changeable"

    heard = card["music"]
    assert heard["music_hours"] == 20.0 and heard["labelled"] == 1.0
    assert [g["name"] for g in heard["genres"]] == ["pop", "folk/acoustic"]
    assert {x["name"] for x in heard["moods"]} == {"upbeat", "melancholic"}
    first = card["days"][0]
    assert (first["music_hours"], first["upbeat"], first["melancholic"]) == (1.0, 1.0, 0.0)

    w = card["writing"]
    assert w["channels"][0]["name"] == "WhatsApp" and w["channels"][1]["name"] == "Email"
    assert w["channels"][1] == {"name": "Email", "words": 4, "pieces": 1}  # the new part only
    assert w["notes"] == {"count": 1, "words": 6}
    assert w["documents"] == {"count": 1, "words": 1200}  # the essay, not the paper read
    assert w["words"] == sum(c["words"] for c in w["channels"]) + 6
    assert w["usual"] == 50  # the median of December's, January's and February's

    upbeat = next(
        r for r in card["relations"] if r["kind"] == "same day" and r["music"] == "upbeat"
    )
    assert upbeat["r"] > 0.9 and upbeat["n"] == 20 and upbeat["notable"]
    assert card["relations"][0]["notable"]

    assert card["story"]["by"] == "numbers" and card["waits_on_model"] is True
    story = card["story"]["text"]
    brighter = sum(bright(n) for n in range(1, 21))
    assert story.startswith(f"In your own words, March ran mostly bright: {brighter} brighter days")
    assert "It was brightest in the week of Mar 16 and hardest in the week of " in story
    assert "You listened to 20 hours of music, most of it pop and folk/acoustic" in story
    assert "You wrote about " in story and " words so far, " in story  # beside the usual by now
    assert story.endswith(card["relations"][0]["text"])  # the strongest relation, last

    path = vault / "clones" / "rhythms" / "months" / "2026-03.json"
    assert json.loads(path.read_text()) == card
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    # As the page reads it: no hashes, no bases.
    shown = portrait.shown(card)
    assert "basis" not in shown and "hash" not in shown["days"][0]
    assert "digest" not in shown["story"]


def test_other_peoples_words_are_never_scored_or_sent(vault, local):
    card = portrait.make(vault, "2026-03", NOW)

    # Every day is scored from the user's own words only: bright days stay bright.
    for d in card["days"]:
        n = int(d["day"][-2:])
        own = list(BRIGHT if bright(n) else HEAVY)
        if n == 3:
            own.append("Lovely to hear, congratulations!")  # the new part of their reply
        assert d["valence"] == mood.day(own)["valence"]
        assert d["emotions"] == (["joyful", "grateful"] if bright(n) else ["tired", "sad"])

    sent = "".join(f"{p}{s}" for p, s, _ in local)
    assert "PRIVATE-THEIRS" not in sent and "Ben wrote" not in sent
    assert "PRIVATE-THEIRS" not in json.dumps(card)
    # One call for the month's days, one for its story, which gets numbers and names, no words.
    assert len(local) == 2
    story_prompt = local[1][0]
    assert "I love this" not in story_prompt and "Sunny Days" in story_prompt
    assert card["story"] == {
        "by": "model",
        "digest": card["story"]["digest"],
        "text": "You had a bright month, with some heavy days.",
    }
    assert card["mood"]["top"][0]["name"] in ("joyful", "grateful", "tired", "sad")
    assert card["waits_on_model"] is False


def test_the_night_makes_cards_once_and_again_only_with_new_data(vault, local, monkeypatch):
    stats = portrait.night(vault, NOW)
    assert stats == {"month cards": 4, "months left": 0}  # March, then Feb, Jan and Dec
    assert len(local) == 2 + 3  # March's days and story; the others' stories, with no mood days
    local.clear()

    # Nothing new: nothing made again, nothing asked.
    assert portrait.night(vault, NOW) == {"month cards": 0, "months left": 0}
    assert local == []

    # A new message on the 21st: March again, and only that day's words go to the model.
    path = vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl"
    with path.open("a") as f:
        for k, text in enumerate(BRIGHT):
            f.write(json.dumps(wa(900 + k, "2026-03-21T15:00:00Z", text, True)) + "\n")
    memory.build(vault)
    later = NOW + timedelta(days=1)
    # February too, whose last evening could sit in March's file; its words are as they were.
    assert portrait.night(vault, later)["month cards"] == 2
    days_asked = [p for p, _, schema in local if "days" in schema["properties"]]
    assert len(days_asked) == 1 and days_asked[0].count("## ") == 1
    assert "## 2026-03-21" in days_asked[0]

    # Months older than last month wait their turn, a few a night, newest first.
    for month in ("2025-12", "2026-01", "2026-02"):
        (vault / "clones" / "rhythms" / "months" / f"{month}.json").unlink()
    # Last month is made whatever the backfill; then one older month, the newest.
    assert portrait.night(vault, later, backfill=1) == {"month cards": 2, "months left": 1}
    assert sorted(portrait.cards(vault)) == ["2026-01", "2026-02", "2026-03"]


def test_the_page_gets_the_cards_with_no_model(vault, hosted, monkeypatch, capsys):
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    portrait.make(vault, "2026-03", NOW)
    cli.main(["clone", "rhythms", "--json"])
    data = json.loads(capsys.readouterr().out)
    months = data["months"]
    assert months["held"][0] == "2026-03" and months["local_model"] is False
    assert [c["month"] for c in months["cards"]] == ["2026-03"]
    assert "basis" not in months["cards"][0]
    assert not musicbrainz.path(vault).exists()  # --json looks nothing up

    cli.main(["clone", "rhythms", "--month", "2026-03"])
    assert capsys.readouterr().out.startswith("rhythms: 20 days with a mood, 20 hours of music")
    with pytest.raises(SystemExit, match="YYYY-MM"):
        cli.main(["clone", "rhythms", "--month", "March"])
