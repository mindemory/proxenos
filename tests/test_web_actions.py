"""How the page opens an email draft (web/src/lib/actions.ts), run through node on synthetic drafts.
Skipped where node or the page's packages aren't installed. No real data."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
TYPESCRIPT = WEB / "node_modules" / "typescript" / "lib" / "typescript.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    not NODE or not TYPESCRIPT.is_file(), reason="needs node and web/node_modules"
)

DRIVER = """
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
const ts = createRequire(import.meta.url)(process.argv[2]);
const source = readFileSync(process.argv[3], "utf8");
const out = ts.transpileModule(source, { compilerOptions: { module: "esnext", target: "es2020" } });
writeFileSync(process.argv[4], out.outputText);
const { draftOpen, gmailThreadHex } = await import(process.argv[4]);
const drafts = JSON.parse(readFileSync(process.argv[5], "utf8"));
console.log(JSON.stringify({
  plans: drafts.map((d) => draftOpen(d, "ana@x.org")),
  hex: ["1789", "1790000000000000000", "0", "AAQk", "12ab"].map(gmailThreadHex),
}));
"""


def draft(**fields):
    return {
        "id": "reply-1",
        "title": "Reply to Ana",
        "kind": "reply",
        "for": "reply",
        "channel": "email",
        "to": "Ana",
        "body": "Yes, Thursday works.",
        "thread": {"source": "email", "chat": "1789"},
        "fromAccount": "",
        "fromAddress": "",
        "fromProvider": "",
    } | fields


def plans(tmp_path, drafts):
    (tmp_path / "driver.mjs").write_text(DRIVER)
    (tmp_path / "drafts.json").write_text(json.dumps(drafts))
    done = subprocess.run(
        [
            NODE,
            str(tmp_path / "driver.mjs"),
            str(TYPESCRIPT),
            str(WEB / "src" / "lib" / "actions.ts"),
            str(tmp_path / "actions.mjs"),
            str(tmp_path / "drafts.json"),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(done.stdout)


def test_each_kind_of_mailbox_opens_in_its_own_web_mail_and_outlook_never_in_gmail(tmp_path):
    work = draft(fromProvider="outlook", fromAddress="me@corp.com", fromAccount="work")
    personal = draft(fromProvider="outlook", fromAddress="me@outlook.com", thread=None)
    workspace = draft(fromProvider="google-workspace", fromAddress="me@example.com")
    gmail = draft(fromProvider="gmail", fromAddress="me@gmail.com", thread=None)
    unknown = draft(fromAddress="me@corp.com", fromAccount="work", thread=None)
    old = draft(thread=None)
    long = draft(fromProvider="outlook", fromAddress="me@corp.com", body="word " * 4000)

    found = plans(tmp_path, [work, personal, workspace, gmail, unknown, old, long])
    outlook_work, outlook_personal, google_work, google, odd, legacy, too_long = found["plans"]

    for plan in (outlook_work, outlook_personal):  # an Outlook thread never offers Gmail
        steps = [plan, plan["alt"]]
        assert not any("google" in (s["url"] or "") or "Gmail" in s["label"] for s in steps)
        assert "Gmail" not in plan["hint"] and "Gmail" not in plan["note"]
    assert outlook_work["url"].startswith("https://outlook.office.com/mail/deeplink/compose?")
    assert "login_hint=me@corp.com" in outlook_work["url"] and "to=ana@x.org" in outlook_work["url"]
    assert outlook_personal["url"].startswith("https://outlook.live.com/mail/0/deeplink/compose?")
    assert outlook_work["alt"]["url"].startswith("mailto:ana@x.org")

    # Gmail in the account the thread is on, and the thread itself when it has a Gmail id.
    assert google_work["url"] == "https://mail.google.com/mail/u/me@example.com/#all/6fd"
    assert google_work["copy"] is True and "Copy & open the thread" in google_work["label"]
    assert "authuser=me@example.com" in google_work["alt"]["url"]
    assert "authuser=me@gmail.com" in google["url"] and google["label"] == "Open in Gmail"
    assert google["alt"]["url"].startswith("mailto:")

    # A mailbox whose provider isn't known gets the mail app, never a guess at a web mail.
    assert odd["url"].startswith("mailto:") and "me@corp.com" in odd["hint"]
    assert odd["alt"]["url"] is None and odd["alt"]["copy"] is True
    # A draft from before mailboxes were recorded opens in Gmail as it always did.
    assert legacy["url"].startswith("https://mail.google.com/mail/?view=cm") and (
        "authuser" not in legacy["url"]
    )
    # Too long for a link: copied, and still opened in the mailbox it is on.
    assert too_long["copy"] is True and too_long["label"] == "Copy & open Outlook"
    assert "body=" not in too_long["url"] and "google" not in too_long["url"]
    # A Gmail thread id as the hex its web address uses; anything else isn't one.
    assert found["hex"] == ["6fd", format(1790000000000000000, "x"), "0", None, None]
