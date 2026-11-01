"""Phone calls on a synthetic call sheet, with Twilio and the model faked out. Nothing dials and
nothing leaves this computer: the one server listens on 127.0.0.1 for the test's own requests."""

import base64
import hashlib
import hmac
import os
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from proxenos import calls, callserver, cli, twilio

NAME = "Tess Lee"
PHONE = "+15555550101"
TWILIO_NUMBER = "+15555550199"
PUBLIC = "https://mac.example.test:10000"
TOKEN = "test-auth-token"

SHEET = """---
title: "Billing about the March visit"
to: "Example Clinic billing"
number: "+1 555 555 0142"
digits: "ww1w2"
about: "the bills from a clinic visit on March 3"
asks: ["A hold on the account while it's reviewed", "An itemized bill", "A reference number"]
facts: {"name": "Tess Lee", "date of birth": "01/02/1990", "account": "A-778812"}
talk: false
---

Call in the morning; they open at 8.
"""


def write_sheet(vault, text=SHEET, name="billing"):
    folder = vault / "clones" / "calls"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.md").write_text(text)
    return calls.read_sheet(folder / f"{name}.md")


class Model:
    """Answers in turn from a list; a callable answer runs, so a turn can be slow or fail."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, prompt, system, schema, keep=()):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema, "keep": keep})
        answer = self.answers.pop(0)
        return answer() if callable(answer) else answer


def turn(say, **kw):
    base = {"done": [], "connect": False, "hold": False, "end": False}
    return base | {"say": say, "rep_name": "", "reference": "", "offered": []} | kw


def make_call(tmp_path, model, talk=False, budget=2.0):
    sheet = write_sheet(tmp_path, SHEET.replace("talk: false", f"talk: {str(talk).lower()}"))
    return calls.Call(
        sheet,
        name=NAME,
        phone=PHONE,
        ring_from=TWILIO_NUMBER,
        base=f"{PUBLIC}/tok",
        think=model,
        budget=budget,
    )


# ── Twilio ──────────────────────────────────────────────────────────────────


def test_only_twilios_signature_counts_with_or_without_the_port():
    fields = {"CallSid": "CA1", "SpeechResult": "hello", "Digits": "1"}
    url = "https://mac.example.test/tok/heard"
    data = url + "CallSidCA1" + "Digits1" + "SpeechResulthello"  # sorted by name
    expected = base64.b64encode(hmac.new(b"secret", data.encode(), hashlib.sha1).digest()).decode()
    assert twilio.signature("secret", url, fields) == expected
    assert twilio.signed("secret", url, fields, expected)
    assert twilio.signed("secret", "https://mac.example.test:443/tok/heard", fields, expected)
    assert not twilio.signed("secret", url, fields | {"Digits": "2"}, expected)
    assert not twilio.signed("other", url, fields, expected)
    assert not twilio.signed("", url, fields, expected) and not twilio.signed(
        "secret", url, fields, ""
    )


def test_the_client_posts_to_the_users_own_account_and_says_twilios_errors():
    sent = []

    def fetch(request):
        sent.append(request)
        return b'{"sid": "CA42"}'

    client = twilio.Client("AC1", "tok", fetch)
    assert client.call(PHONE, TWILIO_NUMBER, f"{PUBLIC}/t/answer", f"{PUBLIC}/t/status") == "CA42"
    client.hang_up("CA42")
    first, second = sent
    assert first.full_url == f"{twilio.API}/Accounts/AC1/Calls.json"
    fields = dict(urllib.parse.parse_qsl(first.data.decode()))
    assert fields["To"] == PHONE and fields["Url"].endswith("/answer")
    assert fields["TimeLimit"] == str(twilio.TIME_LIMIT)
    assert first.get_header("Authorization") == "Basic " + base64.b64encode(b"AC1:tok").decode()
    assert second.full_url.endswith("/Calls/CA42.json") and second.data == b"Status=completed"
    assert twilio._said(b'{"code": 21210, "message": "not yet verified"}') == "not yet verified"


def test_twiml_escapes_what_it_says():
    out = twilio.response(twilio.say('Fish & "chips" <now>'), twilio.hangup())
    assert '<Say voice="Polly.Joanna-Neural">Fish &amp; "chips" &lt;now&gt;</Say><Hangup/>' in out
    assert twilio.say("  ") == "" and twilio.play_digits("") == ""


# ── Sheets ──────────────────────────────────────────────────────────────────


def test_a_sheet_reads_its_fields_and_says_whats_wrong(tmp_path):
    sheet = write_sheet(tmp_path)
    assert (sheet.number, sheet.digits, sheet.talk) == ("+15555550142", "ww1w2", False)
    assert sheet.asks[1] == "An itemized bill" and sheet.facts["account"] == "A-778812"
    assert sheet.notes == "Call in the morning; they open at 8."
    bad = SHEET.replace('"+1 555 555 0142"', "555-0142")
    (tmp_path / "clones" / "calls" / "bad.md").write_text(bad)
    found = dict(calls.sheets(tmp_path))
    assert isinstance(found["billing"], calls.Sheet) and "country code" in found["bad"]
    with pytest.raises(SystemExit, match="can't be used"):
        calls.load(tmp_path, "bad")
    with pytest.raises(SystemExit, match="no call sheet"):
        calls.load(tmp_path, "../billing")


# ── On hold ─────────────────────────────────────────────────────────────────


def test_hold_messages_and_repeats_are_the_hold_and_a_greeting_is_a_person():
    hold = "Thank you for waiting, the next representative will be with you shortly as soon as possible"
    assert calls.classify("") == "empty"
    assert calls.classify("Your call is important to us.") == "recording"
    assert calls.classify("For billing, press 2.") == "recording"
    assert calls.classify(hold.replace("Thank you for waiting, ", ""), [hold]) == "recording"
    assert calls.classify("la la") == "recording"
    assert calls.classify("Thanks for holding, this is Karen. How can I help?") == "person"
    assert calls.classify("Patient billing, Dana.") == "unsure"


def test_on_hold_it_says_nothing_then_tells_who_it_is_and_rings_the_user(tmp_path):
    model = Model({"live": False})
    call = make_call(tmp_path, model)

    first = call.answer()
    assert '<Play digits="ww1w2"/>' in first and 'input="speech"' in first
    assert 'action="https://mac.example.test:10000/tok/heard"' in first
    assert "<Say" not in call.heard("Your call is important to us. Please stay on the line.")
    assert "<Say" not in call.heard("Some music playing in the background tonight")  # the model
    assert "<Say" not in call.heard("")
    assert call.phase == "waiting" and len(model.calls) == 1

    out = call.heard("Thank you for holding, this is Karen, how can I help you?")
    assert "I'm an automated assistant calling for Tess Lee, and this call is transcribed." in out
    assert f'callerId="{TWILIO_NUMBER}"' in out and f">{PHONE}</Number>" in out
    assert 'url="https://mac.example.test:10000/tok/whisper"' in out
    assert call.phase == "connecting"

    whisper = call.whisper()
    assert "Example Clinic billing is on the line" in whisper and "Press 1" in whisper
    assert whisper.endswith("<Hangup/></Response>")  # no key, no bridge: voicemail never is
    assert "<Hangup/>" in call.accept("") and not call.joined
    assert call.accept("1") == twilio.response() and call.phase == "connected"
    assert "<Hangup/>" in call.dialed("completed") and call.phase == "done"
    whos = [t["who"] for t in call.transcript]
    assert whos == ["note", "line", "line", "them", "assistant", "note"]


# ── Talking ─────────────────────────────────────────────────────────────────


def test_when_the_user_doesnt_come_it_asks_itself_and_never_agrees_to_pay(tmp_path):
    model = Model(
        turn("Could you put a hold on the account while it's reviewed?", rep_name="Karen"),
        turn("Tess will pay 200 dollars a month, that works.", done=[1]),
        turn("Thank you. What's the reference number?", done=[2], offered=["A payment plan"]),
        turn("Thanks, Karen. Have a good day.", done=[3], reference="R-5521", end=True),
    )
    call = make_call(tmp_path, model)
    call.answer()
    call.heard("Hi, this is Karen in billing, how can I help?")

    out = call.dialed("no-answer")
    assert "ask a few things on Tess Lee's behalf" in out and call.mode == "talk"
    out = call.heard("Sure. Can I have the date of birth?")
    assert "put a hold on the account" in out and 'bargeIn="true"' in out
    out = call.heard("Done. We could also set up a payment plan, two hundred a month?")
    assert "I can't agree to any payment for Tess Lee, but I'll pass that on." in out
    assert "will pay" not in out
    call.heard("Okay, I'll send the itemized bill too.")
    out = call.heard("Your reference is R-5521.")
    assert out.endswith("<Hangup/></Response>") and call.phase == "done"
    assert call.notes == {"rep_name": "Karen", "reference": "R-5521", "offered": ["A payment plan"]}
    assert call.done == {1, 2, 3}
    prompt = model.calls[-1]["prompt"]
    assert "Them: Your reference is R-5521." in prompt and "2. An itemized bill (done)" in prompt
    assert (
        "never as he or she" in model.calls[0]["system"] and "A-778812" in model.calls[0]["system"]
    )
    # The facts are there to be said, so a hosted model's blanking keeps them.
    assert model.calls[0]["keep"] == ["Tess Lee", "01/02/1990", "A-778812"]


def test_the_model_is_asked_with_the_facts_to_keep(monkeypatch):
    asked = []
    monkeypatch.setattr(calls.llm, "ask", lambda prompt, **kw: asked.append(kw) or {"say": ""})
    calls._think("p", "account number: 12345678", {}, keep=["12345678"])
    assert asked[0]["keep"] == ["12345678"] and asked[0]["system"] == "account number: 12345678"


def test_a_number_it_doesnt_have_or_a_request_for_the_patient_puts_the_user_through(tmp_path):
    model = Model(turn("Sure, it's 123-45-6789."))
    call = make_call(tmp_path, model, talk=True)
    call.answer()
    out = call.heard("Good morning, you're speaking with Dana.")
    assert "I'm calling about the bills from a clinic visit on March 3." in out
    out = call.heard("What's the patient's member ID?")
    assert "I don't have that" in out and "<Dial" in out and "123" not in out
    assert call.handed

    call = make_call(tmp_path, Model(), talk=True)
    call.answer()
    call.heard("Hi, this is Dana.")
    out = call.heard("I'll need the last four of the social.")
    assert "<Dial" in out and call.handed
    # They don't come either: it can't go on, so it says they'll call back.
    out = call.dialed("no-answer")
    assert "will call back" in out and out.endswith("<Hangup/></Response>")


def test_a_slow_model_says_one_moment_and_a_silent_one_hands_over(tmp_path):
    slow = threading.Event()

    def late():
        slow.wait(5)
        return turn("Could you send an itemized bill?")

    model = Model(late, lambda: time.sleep(0.5) or turn("too late"))
    call = make_call(tmp_path, model, talk=True, budget=0.05)
    call.answer()
    call.heard("Hello, billing, this is Sam.")
    out = call.heard("What can I do for you?")
    assert "One moment, please." in out and "<Redirect" in out and "/tok/pending" in out
    slow.set()
    time.sleep(0.05)
    assert "itemized bill" in call.pending()

    out = call.heard("Sure, anything else?")
    assert "One moment" in out
    out = call.pending()
    assert "<Dial" in out and call.handed


def test_numbers_they_said_or_the_sheet_has_may_be_said_back():
    allowed = ["01/02/1990", "A-778812", "Your reference is R-5521."]
    assert calls.guard("It's 01/02/1990.", NAME, allowed) == ("It's 01/02/1990.", "")
    assert calls.guard("So that's R-5521?", NAME, allowed)[1] == ""
    assert calls.guard("Account 778812.", NAME, allowed)[1] == ""
    assert calls.guard("It's 555-0199.", NAME, allowed) == ("", "number")
    assert calls.commits("Yes, a payment plan works.", NAME)
    assert calls.commits("Tess can pay it on Friday.", NAME)
    assert not calls.commits("I can't agree to any payment, but I'll pass that on.", NAME)
    assert not calls.commits("Could you tell me what payment options there are?", NAME)


# ── Keeping it ──────────────────────────────────────────────────────────────


def test_the_record_keeps_the_call_and_what_came_of_it_privately(tmp_path):
    outcome = {"summary": "On hold.", "asks": [], "rep_name": "", "reference": "", "offered": []}
    model = Model(outcome | {"next": ["Call back"]})
    call = make_call(tmp_path, model)
    call.answer()
    call.heard("Hello, this is Sam.")
    calls.write_live(tmp_path, call)
    live = calls.read_live(tmp_path, "billing")
    assert live["phase"] == "connecting" and live["pid"] == os.getpid()
    call.ended("completed")
    path = calls.finish(tmp_path, call)
    assert not calls.live_path(tmp_path, "billing").exists()
    record = calls._json(path.read_text(), dict)
    assert record["outcome"]["next"] == ["Call back"] and record["status"] == "completed"
    assert os.name == "nt" or stat.S_IMODE(path.stat().st_mode) == 0o600
    assert os.name == "nt" or stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    # No one answered: nothing to ask the model.
    quiet = make_call(tmp_path, Model())
    assert quiet.outcome() is None


# ── The server and the command ──────────────────────────────────────────────


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("PROXENOS_TWILIO_NUMBER", TWILIO_NUMBER)
    monkeypatch.setenv("PROXENOS_PHONE", PHONE)
    monkeypatch.setenv("PROXENOS_CALLS_URL", PUBLIC + "/")
    monkeypatch.setenv("PROXENOS_NAME", NAME)


def post(port, url, fields, token=TOKEN):
    path = urllib.parse.urlsplit(url).path
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        urllib.parse.urlencode(fields).encode(),
        {"X-Twilio-Signature": twilio.signature(token, url, fields)},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""
    except OSError as e:  # the server broke off: say so, rather than end Twilio's side early
        return 0, repr(e)


class FakeTwilio:
    """Places no call: once asked to, it plays Twilio's part against the server."""

    def __init__(self, servers):
        self.servers, self.placed, self.replies = servers, [], []

    def call(self, to, caller, url, status_url):
        self.placed.append((to, caller, url, status_url))
        port = self.servers[0].server_address[1]

        def twilio_side():
            try:
                self.replies.append(post(port, url, {"CallSid": "CA9"}))
                self.replies.append(post(port, url, {"CallSid": "CA9"}, token="forged"))
                self.replies.append(post(port, url.replace("/answer", "/nope"), {"x": "1"}))
            finally:  # always: the call can't end any other way
                self.replies.append(post(port, status_url, {"CallStatus": "busy"}))

        threading.Thread(target=twilio_side).start()
        return "CA9"

    def hang_up(self, sid):
        raise AssertionError("nothing to hang up")


def test_a_call_runs_its_server_until_twilio_says_it_ended(tmp_path, settings, monkeypatch):
    sheet = write_sheet(tmp_path)
    servers = []
    made = callserver._Server
    monkeypatch.setattr(callserver, "_Server", lambda *a: servers.append(made(*a)) or servers[-1])
    # Should Twilio's last word never come, give up in seconds, not hours.
    monkeypatch.setattr(callserver, "TOUCH", 0.05)
    monkeypatch.setattr(callserver, "LAST_WORD", 5)
    monkeypatch.setattr(twilio, "TIME_LIMIT", 0)
    # The page's copy can't be written (on Windows, a file in use): the call goes on regardless.
    monkeypatch.setattr(calls, "write_live", lambda *a: (_ for _ in ()).throw(PermissionError(32)))
    fake = FakeTwilio(servers)

    said = callserver.place(tmp_path, sheet, check=False, client=fake, port=0)

    ((to, caller, url, status_url),) = fake.placed
    assert (to, caller) == ("+15555550142", TWILIO_NUMBER)  # no caller ID set: the Twilio number
    assert url.startswith(f"{PUBLIC}/") and url.endswith("/answer") and len(url.split("/")[3]) == 32
    assert status_url == url.replace("/answer", "/status")
    (ok, answered), (forged, _), (unknown, _), (ended, _) = fake.replies
    assert ok == 200 and '<Play digits="ww1w2"/>' in answered
    assert (forged, unknown, ended) == (403, 404, 200)
    assert said.startswith("The call ended (busy).")
    (record,) = (tmp_path / "clones" / "calls" / "billing").glob("*.json")
    assert calls._json(record.read_text(), dict)["sid"] == "CA9"
    assert not (tmp_path / "state" / "asking").exists()  # other model work may go on again


def test_settings_say_whats_missing_and_a_made_up_vault_never_calls(
    tmp_path, settings, monkeypatch
):
    monkeypatch.delenv("PROXENOS_PHONE")
    with pytest.raises(SystemExit, match="PROXENOS_PHONE"):
        callserver.settings()
    monkeypatch.setenv("PROXENOS_PHONE", "555-0101")
    with pytest.raises(SystemExit, match="country code"):
        callserver.settings()
    (tmp_path / "DEMO").write_text("")
    with pytest.raises(SystemExit, match="made-up vault"):
        callserver.place(tmp_path, write_sheet(tmp_path), check=False)


def test_the_command_lists_sheets_and_stop_clears_a_call_left_behind(tmp_path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    write_sheet(vault)
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    cli.main(["call", "list"])
    assert (
        "billing: Billing about the March visit (Example Clinic billing)" in capsys.readouterr().out
    )
    live = calls.live_path(vault, "billing")
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text('{"sid": "CA1", "pid": 0}')
    cli.main(["call", "stop", "billing"])
    assert "cleared what was left" in capsys.readouterr().out and not live.exists()
