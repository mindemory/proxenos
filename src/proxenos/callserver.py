"""`proxenos call start|stop|list`: place a call from a call sheet (calls.py), and the small web
server Twilio asks what to do next while it goes.

A call goes through the user's own Twilio account (docs/calls.md). Twilio dials the sheet's
number from PROXENOS_CALLER_ID (the user's own number, verified in Twilio; else the Twilio
number), and rings the user at PROXENOS_PHONE from PROXENOS_TWILIO_NUMBER. Twilio reaches this
Mac at PROXENOS_CALLS_URL, the one public address Proxenos has, which Tailscale Funnel passes on
to 127.0.0.1:PORT. Only while a call goes is anything listening there, and it answers only
requests Twilio signed with the user's token, at paths that start with that call's own random
token. The model on the call is PROXENOS_CALL_MODEL when it's set, else PROXENOS_MODEL; while a
call goes, other model work waits, so a person on the line isn't kept waiting behind it.

The user starts every call, here or from the page, and Ctrl-C or `proxenos call stop` hangs up.
"""

import argparse
import hmac
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from proxenos import calls, llm, lock, outbox, twilio
from proxenos.config import env, env_key

PORT = 4748
MAX_BODY = 64 * 1024  # Twilio's form posts are a few kilobytes
CHECK_TIMEOUT = 15  # seconds to reach this Mac at its public address before calling
TOUCH = 60  # seconds between keeping the mark that holds other model work off fresh
LAST_WORD = 600  # seconds past Twilio's time limit to wait for its word that the call ended
_ENDED = {"completed", "busy", "no-answer", "failed", "canceled"}
_STEPS = ("answer", "heard", "pending", "dialed", "whisper", "accept", "status")
_SETTINGS = {
    "TWILIO_ACCOUNT_SID": "your Twilio account's SID",
    "TWILIO_AUTH_TOKEN": "your Twilio account's auth token",
    "PROXENOS_TWILIO_NUMBER": "the Twilio number that rings you",
    "PROXENOS_PHONE": "your own phone, which it rings",
    "PROXENOS_CALLS_URL": "where Twilio reaches this Mac, from `tailscale funnel`",
    "PROXENOS_NAME": "your name, as the assistant says it",
}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="the call sheets in clones/calls/")
    start = actions.add_parser("start", help="place a call now; Ctrl-C hangs up")
    start.add_argument("id", help="the call sheet, clones/calls/ID.md")
    start.add_argument(
        "--no-check",
        action="store_true",
        help="call without first checking that Twilio can reach this Mac",
    )
    stop = actions.add_parser("stop", help="hang up a call that's going")
    stop.add_argument("id")


def run(vault: Path, args: argparse.Namespace) -> None:
    if args.action == "list":
        for sheet_id, sheet in calls.sheets(vault):
            line = f"{sheet.title} ({sheet.to})" if isinstance(sheet, calls.Sheet) else sheet
            print(f"{sheet_id}: {line}")
        return
    if args.action == "stop":
        print(stop(vault, args.id))
        return
    print(place(vault, calls.load(vault, args.id), check=not args.no_check))


def settings() -> dict[str, str]:
    """What a call needs, or SystemExit naming what's missing."""
    values = {
        "sid": os.environ.get("TWILIO_ACCOUNT_SID", ""),
        "token": os.environ.get("TWILIO_AUTH_TOKEN", ""),
        "number": env("TWILIO_NUMBER"),
        "phone": env("PHONE"),
        "public": env("CALLS_URL").rstrip("/"),
        "name": env("NAME"),
    }
    missing = [k for k, v in zip(_SETTINGS, values.values(), strict=True) if not v]
    if missing:
        lines = "\n".join(f"  {k}: {_SETTINGS[k]}" for k in missing)
        raise SystemExit(f"Calls need these settings (docs/calls.md says how):\n{lines}")
    values["caller"] = env("CALLER_ID") or values["number"]
    for key in ("number", "phone", "caller"):
        if not twilio.NUMBER.fullmatch(values[key]):
            raise SystemExit(
                f"{key} must be a whole number with its country code, like +16035550100"
            )
    if not values["public"].startswith("https://"):
        raise SystemExit("PROXENOS_CALLS_URL must be an https:// address")
    return values


def place(
    vault: Path,
    sheet: calls.Sheet,
    *,
    check: bool = True,
    client: twilio.Client | None = None,
    port: int = PORT,
) -> str:
    """Place the call, answer Twilio's requests until it ends, then keep the record."""
    if outbox.is_demo(vault):
        raise SystemExit("Nothing is called from a made-up vault.")
    if live := _live_pid(vault, sheet.id):
        raise SystemExit(f"A call from {sheet.id} is already going (process {live}).")
    values = settings()
    if model := env("CALL_MODEL"):
        os.environ[env_key("MODEL")] = model
    token = secrets.token_hex(16)
    call = calls.Call(
        sheet,
        name=values["name"],
        phone=values["phone"],
        ring_from=values["number"],
        base=f"{values['public']}/{token}",
    )
    try:
        server = _Server(("127.0.0.1", port), vault, call, token, values)
    except OSError:
        raise SystemExit(f"Port {port} is in use: is another call going?") from None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = client or twilio.Client(values["sid"], values["token"])
    try:
        if check:
            _check(f"{values['public']}/{token}/ping")
        if env("MODEL").startswith(llm.LOCAL):  # load it now, not when someone's on the line
            threading.Thread(target=call.warm, daemon=True).start()
        with llm.foreground(vault):
            try:
                call.sid = client.call(
                    sheet.number, values["caller"], call._url("answer"), call._url("status")
                )
            except twilio.TwilioError as e:
                raise SystemExit(f"The call didn't start: {e}") from None
            with server.lock:  # Twilio may be asking already
                _show(vault, call)
            print(f"Calling {sheet.to}; Ctrl-C hangs up.", flush=True)
            _wait(vault, server, client, call)
    finally:
        server.shutdown()
        server.server_close()
    path = calls.finish(vault, call)
    reference = call.notes.get("reference")
    said = f", reference {reference}" if reference else ""
    return f"The call ended ({call.status or 'hung up'}){said}. Kept in {path}."


def _wait(vault: Path, server: "_Server", client: twilio.Client, call: calls.Call) -> None:
    """Until Twilio says the call has ended, or Ctrl-C hangs up; at most a little past Twilio's
    own time limit, in case its last word never comes."""
    deadline = time.monotonic() + twilio.TIME_LIMIT + LAST_WORD
    try:
        while not server.over.wait(TOUCH):
            _keep(vault)
            if time.monotonic() > deadline:
                break
    except KeyboardInterrupt:
        try:
            client.hang_up(call.sid)
        except twilio.TwilioError as e:
            print(f"Couldn't hang up through Twilio: {e}", file=sys.stderr)
    with server.lock:
        if call.phase != "done" or not call.status:
            call.ended(call.status or "canceled")


def stop(vault: Path, sheet_id: str, client: twilio.Client | None = None) -> str:
    """Hang up the call that's going from this sheet."""
    live = calls.read_live(vault, sheet_id)
    if not live.get("sid"):
        return f"No call from {sheet_id} is going."
    if not _live_pid(vault, sheet_id):
        calls.live_path(vault, sheet_id).unlink(missing_ok=True)
        return f"No call from {sheet_id} is going; cleared what was left of the last one."
    values = settings()
    (client or twilio.Client(values["sid"], values["token"])).hang_up(str(live["sid"]))
    return f"Hung up the call to {live.get('to') or sheet_id}."


def _live_pid(vault: Path, sheet_id: str) -> int | None:
    pid = calls.read_live(vault, sheet_id).get("pid")
    if not isinstance(pid, int) or pid == os.getpid():
        return None
    return pid if lock.alive(pid) else None


def _check(url: str) -> None:
    """Twilio can't call back a Mac it can't reach, so make sure the public address leads here."""
    try:
        with urllib.request.urlopen(url, timeout=CHECK_TIMEOUT) as response:
            if response.read() == b"ok":
                return
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    raise SystemExit(
        "Twilio couldn't reach this Mac at PROXENOS_CALLS_URL. Turn Funnel on for the calls port:\n"
        f"  tailscale funnel --bg --https=10000 http://127.0.0.1:{PORT}\n"
        "then set PROXENOS_CALLS_URL to the https address it prints (docs/calls.md)."
    )


def _show(vault: Path, call: calls.Call) -> None:
    """Write where the call is for the page. Only the page reads it, so the call goes on without
    it when it can't be written (a file in use on Windows, a full disk)."""
    try:
        calls.write_live(vault, call)
    except OSError as e:
        print(f"Couldn't update the page's view of the call: {e}", file=sys.stderr)


def _keep(vault: Path) -> None:
    """Keep the mark that holds other model work off fresh, for a call longer than it lasts."""
    try:
        os.utime(vault / llm._FOREGROUND)
    except OSError:
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, vault: Path, call: calls.Call, token: str, values: dict):
        super().__init__(address, _Handler)
        self.vault, self.call, self.token = vault, call, token
        self.secret, self.public = values["token"], values["public"]
        self.lock = threading.Lock()
        self.over = threading.Event()


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def do_GET(self) -> None:
        if self._step() == "ping":
            self._send(200, "text/plain", "ok")
        else:
            self._send(404, "text/plain", "")

    def do_POST(self) -> None:
        length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
        body = self.rfile.read(length)  # all of it, even to refuse it, so the answer arrives whole
        step = self._step()
        if step not in _STEPS:
            self._send(404, "text/plain", "")
            return
        fields = dict(urllib.parse.parse_qsl(body.decode(errors="replace")))
        given = self.headers.get("X-Twilio-Signature", "")
        if not twilio.signed(self.server.secret, self.server.public + self.path, fields, given):
            self._send(403, "text/plain", "")
            return
        with self.server.lock:
            twiml = respond(self.server.call, step, fields)
            _show(self.server.vault, self.server.call)
        if step == "status" and self.server.call.status:
            self.server.over.set()
        self._send(200, "text/xml", twiml)

    def _step(self) -> str:
        """The step a path asks for, when it starts with this call's token; else ""."""
        parts = urllib.parse.urlsplit(self.path).path.strip("/").split("/")
        if len(parts) == 2 and hmac.compare_digest(parts[0], self.server.token):
            return parts[1]
        return ""

    def _send(self, code: int, kind: str, body: str) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        """Quiet: a request line would put the call's token in the log."""


def respond(call: calls.Call, step: str, fields: dict[str, str]) -> str:
    """The TwiML for one of Twilio's requests."""
    if step == "answer":
        return call.answer()
    if step == "heard":
        return call.heard(fields.get("SpeechResult", ""))
    if step == "pending":
        return call.pending()
    if step == "whisper":
        return call.whisper()
    if step == "accept":
        return call.accept(fields.get("Digits", ""))
    if step == "dialed":
        return call.dialed(fields.get("DialCallStatus", ""))
    status = fields.get("CallStatus", "")
    if status in _ENDED:
        call.ended(status)
    return twilio.response()
