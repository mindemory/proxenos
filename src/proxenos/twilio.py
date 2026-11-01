"""Twilio, the phone service `proxenos call` dials through: its REST API over urllib, the check
that a request really came from Twilio, and the TwiML that tells a call what to do next.

The account is the user's own: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN, kept with the other
secrets. Twilio signs every request it makes to the call server with the token (X-Twilio-Signature:
HMAC-SHA1 over the URL it asked for and its form fields, sorted by name), and `signed` refuses any
request that isn't. Nothing here keeps a copy of anything.
"""

import base64
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from xml.sax.saxutils import escape, quoteattr

API = "https://api.twilio.com/2010-04-01"
TIMEOUT = 30  # seconds for one request to Twilio
TIME_LIMIT = 4 * 3600  # Twilio ends a call that runs longer; the most it allows
VOICE = "Polly.Joanna-Neural"  # how the assistant sounds: one of Twilio's voices, not the user's
SPEECH_MODEL = "phone_call"  # Twilio's speech recognition tuned for phone audio
NUMBER = re.compile(r"\+[1-9]\d{6,14}")  # a phone number as Twilio takes it (E.164)
DIGITS = re.compile(r"[0-9*#wW]{0,64}")  # keys to press; w waits half a second

Fetch = Callable[[urllib.request.Request], bytes]


class TwilioError(RuntimeError):
    pass


def _fetch(request: urllib.request.Request) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        raise TwilioError(f"Twilio said {e.code}: {_said(e.read())}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise TwilioError(f"couldn't reach Twilio ({e})") from None


def _said(body: bytes) -> str:
    """Twilio's own words for an error, from the JSON it answers with."""
    try:
        return str(json.loads(body).get("message", ""))[:300] or "no reason given"
    except (ValueError, AttributeError):
        return body.decode(errors="replace")[:300]


class Client:
    """The two things Proxenos asks of Twilio: start a call, and end one."""

    def __init__(self, sid: str, token: str, fetch: Fetch = _fetch):
        self.sid, self.fetch = sid, fetch
        self._auth = "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode()

    def call(self, to: str, caller: str, url: str, status_url: str) -> str:
        """Dial `to` from `caller` (a Twilio number or one verified in the account). Twilio asks
        `url` what to do once someone answers and posts to `status_url` when the call ends.
        Returns the call's id."""
        fields = {
            "To": to,
            "From": caller,
            "Url": url,
            "Method": "POST",
            "StatusCallback": status_url,
            "StatusCallbackMethod": "POST",
            "TimeLimit": str(TIME_LIMIT),
        }
        return str(self._post("Calls.json", fields)["sid"])

    def hang_up(self, call_sid: str) -> None:
        self._post(f"Calls/{call_sid}.json", {"Status": "completed"})

    def _post(self, path: str, fields: Mapping[str, str]) -> dict:
        request = urllib.request.Request(
            f"{API}/Accounts/{urllib.parse.quote(self.sid)}/{path}",
            urllib.parse.urlencode(fields).encode(),
            {"Authorization": self._auth, "Content-Type": "application/x-www-form-urlencoded"},
        )
        answer = json.loads(self.fetch(request))
        if not isinstance(answer, dict):
            raise TwilioError("Twilio answered with something other than a JSON object")
        return answer


# ── Signatures ──────────────────────────────────────────────────────────────


def signature(token: str, url: str, fields: Mapping[str, str]) -> str:
    """What Twilio puts in X-Twilio-Signature for a POST of `fields` to `url`."""
    data = url + "".join(name + fields[name] for name in sorted(fields))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def signed(token: str, url: str, fields: Mapping[str, str], given: str) -> bool:
    """Whether `given` is Twilio's signature for this request. Twilio signs a URL on a port of its
    own sometimes with the port and sometimes without, so either counts, as in its own libraries."""
    if not token or not given:
        return False
    return any(
        hmac.compare_digest(signature(token, u, fields), given) for u in _with_and_without_port(url)
    )


def _with_and_without_port(url: str) -> set[str]:
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or {"https": 443, "http": 80}.get(parts.scheme)
    return {
        urllib.parse.urlunsplit(parts._replace(netloc=host)),
        urllib.parse.urlunsplit(parts._replace(netloc=f"{host}:{port}")),
    }


# ── TwiML ───────────────────────────────────────────────────────────────────


def response(*verbs: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(verbs) + "</Response>"


def say(text: str) -> str:
    return _tag("Say", {"voice": VOICE}, escape(text)) if text.strip() else ""


def play_digits(digits: str) -> str:
    return _tag("Play", {"digits": digits}) if digits else ""


def listen(action: str, *inside: str, timeout: int, barge_in: bool = False) -> str:
    """Twilio's speech recognition hears the next stretch of speech, then posts it to `action`
    as SpeechResult, or with none after `timeout` seconds of quiet. With barge_in, speech cuts
    off whatever the assistant is saying inside it."""
    attrs = {
        "input": "speech",
        "action": action,
        "method": "POST",
        "timeout": str(timeout),
        "speechTimeout": "2",
        "speechModel": SPEECH_MODEL,
        "language": "en-US",
        "actionOnEmptyResult": "true",
    }
    if barge_in:
        attrs["bargeIn"] = "true"
    return _tag("Gather", attrs, "".join(inside))


def keypress(action: str, *inside: str, timeout: int) -> str:
    """One key, posted to `action` as Digits."""
    attrs = {"input": "dtmf", "numDigits": "1", "action": action, "method": "POST"}
    return _tag("Gather", attrs | {"timeout": str(timeout)}, "".join(inside))


def dial(number: str, caller: str, action: str, whisper: str, timeout: int) -> str:
    """Ring `number` and put the call through once its `whisper` TwiML lets it; then post how it
    went to `action` as DialCallStatus."""
    inside = _tag("Number", {"url": whisper, "method": "POST"}, escape(number))
    attrs = {"callerId": caller, "timeout": str(timeout), "action": action, "method": "POST"}
    return _tag("Dial", attrs, inside)


def redirect(url: str) -> str:
    return _tag("Redirect", {"method": "POST"}, escape(url))


def hangup() -> str:
    return "<Hangup/>"


def _tag(name: str, attrs: Mapping[str, str], inside: str = "") -> str:
    attributes = "".join(f" {k}={quoteattr(v)}" for k, v in attrs.items())
    return f"<{name}{attributes}>{inside}</{name}>" if inside else f"<{name}{attributes}/>"
