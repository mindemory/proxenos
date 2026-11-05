// What a draft can open once it's approved: the app it was written for, with the text filled
// in. Pure functions with no server or browser APIs, so the server builds the links and the
// page reads the same pieces back. Nothing here sends anything: every link ends at a compose
// window, a chat picker or a clipboard, and the reader presses send.
//
// The only things that ever go into a link are the draft's own text (and its subject) and the
// recipient: an email address, or the number of the WhatsApp chat a reply answers. Never an id,
// a vault path, or anything else from the vault.

import type { Draft, DraftOpen, DraftOpenStep, OpenTarget } from "./types";

/** Outlook.com's own domains: a mailbox there is a personal one, and opens on outlook.live.com. */
const OUTLOOK_PERSONAL_DOMAINS = new Set(["outlook.com", "hotmail.com", "live.com", "msn.com"]);

/** The most a link may carry of the draft's text, counted as it's written in the link. */
export const MAX_URL_BODY = 6000;

const GMAIL = "https://mail.google.com/mail/";
const OUTLOOK_WORK = "https://outlook.office.com/mail/deeplink/compose";
const OUTLOOK_PERSONAL = "https://outlook.live.com/mail/0/deeplink/compose";
const LINKEDIN_FEED = "https://www.linkedin.com/feed/";
const INSTAGRAM_INBOX = "https://www.instagram.com/direct/inbox/";
const MESSENGER = "https://www.messenger.com/";
const X_MESSAGES = "https://x.com/messages";

/** These are written for the reader, not for anyone to send. */
const NOT_MESSAGES = new Set(["doc", "plan", "checklist", "blocked"]);

/** Which app a draft opens in, from its channel and kind. Anything unknown becomes a file. */
export function openTarget(d: Pick<Draft, "channel" | "kind">): OpenTarget {
  if (NOT_MESSAGES.has(d.kind)) return "file";
  switch (d.channel) {
    case "email":
    case "gmail":
      return "email";
    case "whatsapp":
      return "whatsapp";
    case "slack":
      return "slack";
    case "linkedin":
      return "linkedin";
    case "instagram":
      return "instagram";
    case "messenger":
      return "messenger";
    case "x":
      return "x";
    case "":
      return d.kind === "email" ? "email" : "file";
    default:
      return "file";
  }
}

// ── Recipients ──────────────────────────────────────────────────────────────

const ADDRESS = /^[^\s@<>(),;:"[\]\\]+@[^\s@<>(),;:"[\]\\]+\.[^\s@<>(),;:"[\]\\]+$/;
const NAMED_ADDRESS = /^(.*?)\s*<([^<>\s]+)>$/;

export function isAddress(text: string): boolean {
  return ADDRESS.test(text) && text.length <= 254;
}

/** A name as the vault lookup compares it: one line, lower case. */
export function normName(name: string): string {
  return name.replace(/\s+/g, " ").trim().toLowerCase();
}

/** "Name <a@b.c>" or "a@b.c" as [name, address], or null for anything else. */
export function parseAddress(text: string): [string, string] | null {
  const t = text.trim();
  if (isAddress(t)) return ["", t.toLowerCase()];
  const m = t.match(NAMED_ADDRESS);
  if (m && isAddress(m[2])) return [m[1].replace(/^"|"$/g, "").trim(), m[2].toLowerCase()];
  return null;
}

/** A draft's `to` as the people it names: the whole thing first, then its parts if it lists several. */
function recipientParts(to: string): string[] {
  const parts = to
    .split(/\s*(?:[;,&]|\band\b)\s*/i)
    .map((p) => p.trim())
    .filter(Boolean);
  return parts.length > 1 ? parts : [];
}

/** The names in a draft's `to` that need looking up in the vault: none of them already an address. */
export function recipientQueries(to: string): string[] {
  const out = new Set<string>();
  for (const name of [to, ...recipientParts(to)]) {
    if (name && !parseAddress(name)) out.add(normName(name));
  }
  return [...out];
}

/**
 * The address (or comma-joined addresses) a draft's `to` stands for: one already written in it,
 * or the vault's answer for its name. "" when nobody matches, so the compose window opens with
 * the To line empty rather than with a guess.
 */
export function recipientAddress(to: string, found: ReadonlyMap<string, string>): string {
  const one = (name: string): string | null => parseAddress(name)?.[1] ?? found.get(normName(name)) ?? null;
  const whole = one(to);
  if (whole) return whole;
  const addresses = recipientParts(to).map(one).filter((a): a is string => a !== null);
  return [...new Set(addresses)].join(",");
}

// ── Subject and body ────────────────────────────────────────────────────────

const SUBJECT_LINE = /^\s*(?:\*\*|__)?subject\s*(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*(.+?)\s*$/i;

/**
 * An email's subject and the text under it. The subject is the "Subject:" line the draft starts
 * with (one of its first few lines), which is taken out of the text; else the draft's title.
 */
export function splitSubject(d: Pick<Draft, "title" | "body">): { subject: string; body: string } {
  const lines = d.body.split("\n");
  let seen = 0;
  for (let i = 0; i < lines.length && seen < 3; i++) {
    if (!lines[i].trim()) continue;
    seen++;
    const m = lines[i].match(SUBJECT_LINE);
    if (!m) continue;
    const subject = m[1].replace(/(?:\*\*|__)\s*$/, "").replace(/\s+/g, " ").trim();
    if (!subject) break;
    const rest = [...lines.slice(0, i), ...lines.slice(i + 1)].join("\n");
    return { subject: subject.slice(0, 300), body: rest.replace(/^(?:[ \t]*\n)+/, "").trimEnd() };
  }
  return { subject: d.title.replace(/\s+/g, " ").trim().slice(0, 300), body: d.body };
}

/** The text a draft puts on the clipboard when it's copied as part of opening: an email's has no subject line. */
export function openText(d: Pick<Draft, "channel" | "kind" | "title" | "body">): string {
  return openTarget(d) === "email" ? splitSubject(d).body : d.body;
}

/** The draft as a markdown file for download: its title over its text, unless the text starts with one. */
export function markdownFile(d: Pick<Draft, "title" | "body">): { filename: string; text: string } {
  const slug = d.title
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/, "");
  const text = /^\s*#\s/.test(d.body) ? d.body : `# ${d.title}\n\n${d.body}`;
  return { filename: `${slug || "draft"}.md`, text: text.trimEnd() + "\n" };
}

// ── Links ───────────────────────────────────────────────────────────────────

/** Replace what encodeURIComponent would throw on: a half of a surrogate pair. */
function wellFormed(text: string): string {
  let out = "";
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < text.length && text.charCodeAt(i + 1) >= 0xdc00 && text.charCodeAt(i + 1) <= 0xdfff) {
      out += text[i] + text[i + 1];
      i++;
    } else out += c >= 0xd800 && c <= 0xdfff ? "�" : text[i];
  }
  return out;
}

/** Everything but letters, digits and "-_.~" is escaped, so nothing in the text can end or reshape a link. */
function enc(text: string): string {
  return encodeURIComponent(wellFormed(text)).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
}

/** An address as it's written in a link: "@" stays readable, anything else unusual is escaped. */
function encAddress(addresses: string): string {
  return addresses.split(",").map((a) => enc(a).replace(/%40/g, "@")).join(",");
}

/** A mailto: link wants CRLF line breaks. */
function crlf(text: string): string {
  return text.replace(/\r?\n/g, "\r\n");
}

/** The text as it'd sit in a link, or null when it's too long for one. */
function fits(text: string, encode: (t: string) => string = enc): string | null {
  const e = encode(text);
  return e.length <= MAX_URL_BODY ? e : null;
}

/** Gmail's thread id (X-GM-THRID, decimal) as the hex its web address uses, or null for anything else. */
export function gmailThreadHex(chat: string): string | null {
  if (!/^\d{1,24}$/.test(chat)) return null;
  // Decimal to hex a digit at a time: ids are past what a number holds exactly.
  let digits = chat.split("").map(Number);
  let hex = "";
  while (digits.some((d) => d !== 0)) {
    let rest = 0;
    const next: number[] = [];
    for (const d of digits) {
      const n = rest * 10 + d;
      const q = Math.floor(n / 16);
      rest = n % 16;
      if (next.length > 0 || q > 0) next.push(q);
    }
    hex = rest.toString(16) + hex;
    digits = next;
  }
  return hex || "0";
}

/**
 * Whose mail an email draft is. "google" and "outlook" are mailboxes whose provider is known;
 * "unknown" is one the draft names but whose provider no record settles; "legacy" is a draft
 * written before drafts recorded their mailbox, which opens in Gmail as they always did.
 */
export type MailKind = "google" | "outlook" | "unknown" | "legacy";

export function mailKind(d: Pick<Draft, "fromProvider" | "fromAddress" | "fromAccount">): MailKind {
  if (d.fromProvider === "gmail" || d.fromProvider === "google-workspace") return "google";
  if (d.fromProvider === "outlook") return "outlook";
  return d.fromAddress || d.fromAccount ? "unknown" : "legacy";
}

/** The way into the default mail app: a mailto link, which can't say which account it goes from. */
function mailAppStep(d: Draft, to: string, su: string, body: string): DraftOpenStep {
  const mailBody = fits(body, (t) => enc(crlf(t)));
  const mailUrl = `mailto:${to}?subject=${su}${mailBody === null ? "" : `&body=${mailBody}`}`;
  const from = d.fromAddress ? ` Check it goes from ${d.fromAddress}.` : "";
  return mailBody === null
    ? {
        label: "Copy & open mail app",
        hint: `The text is too long for a link: copies it, and opens your mail app with the recipient and subject filled in.${from}`,
        url: mailUrl,
        copy: true,
        note: `Copied, and your mail app is open: paste the text in, then press send.${from}`,
      }
    : {
        label: "Open in mail app",
        hint: `Opens your default mail app with the recipient, subject and text filled in. You press send.${from}`,
        url: mailUrl,
        copy: false,
        note: `Your mail app is open with your draft: press send there.${from}`,
      };
}

/** A compose window on the web, in Gmail or Outlook, with the recipient and subject filled in and the text too when it fits. */
function composeStep(name: string, url: (body: string) => string, inBody: string | null, from: string): DraftOpenStep {
  const where = from ? ` for ${from}` : "";
  return inBody === null
    ? {
        label: `Copy & open ${name}`,
        hint: `The text is too long for a link: copies it, and opens ${name}${where} with the recipient and subject filled in. Paste it in, then press send.`,
        url: url(""),
        copy: true,
        note: `Copied, and ${name} is open: paste the text in, then press send`,
      }
    : {
        label: `Open in ${name}`,
        hint: `Opens a ${name} compose window${where} with the recipient, subject and text filled in. You press send.`,
        url: url(inBody),
        copy: false,
        note: `${name} is open with your draft: press send there`,
      };
}

/**
 * The ways to open an email, in the mailbox its thread is on. A Gmail or Google Workspace one opens
 * in that account (authuser), and a reply in a Gmail thread opens that thread so the answer stays in
 * it. An Outlook one opens Outlook on the web, never Gmail. A mailbox of unknown kind still gets the
 * mail app, and only a draft that predates the record gets Gmail with no account.
 */
function emailSteps(d: Draft, address: string): { main: DraftOpenStep; alt: DraftOpenStep } {
  const { subject, body } = splitSubject(d);
  const to = encAddress(address);
  const su = enc(subject);
  const inBody = fits(body);
  const bodyParam = (b: string) => (b ? `&body=${b}` : "");
  const mailApp = mailAppStep(d, to, su, body);
  const from = d.fromAddress;
  const kind = mailKind(d);

  if (kind === "outlook") {
    const personal = OUTLOOK_PERSONAL_DOMAINS.has(from.slice(from.lastIndexOf("@") + 1));
    const hint = from ? `&login_hint=${encAddress(from)}` : "";
    const url = (b: string) => `${personal ? OUTLOOK_PERSONAL : OUTLOOK_WORK}?to=${to}&subject=${su}${bodyParam(b)}${hint}`;
    return { main: composeStep("Outlook", url, inBody, from), alt: mailApp };
  }
  if (kind === "unknown") {
    // Nothing says which web mail it is: the mail app, and the text to paste into any other.
    const copy: DraftOpenStep = {
      label: "Copy the text",
      hint: "Copies the text, to paste into the mailbox it belongs in.",
      url: null,
      copy: true,
      note: "Copied: paste it into the mailbox it belongs in",
    };
    return { main: mailApp, alt: copy };
  }

  const account = kind === "google" && from ? `&authuser=${encAddress(from)}` : "";
  const compose = composeStep("Gmail", (b) => `${GMAIL}?view=cm&fs=1${account}&to=${to}&su=${su}${bodyParam(b)}`, inBody, kind === "google" ? from : "");
  const hex = kind === "google" && from && d.thread?.source === "email" ? gmailThreadHex(d.thread.chat) : null;
  if (hex === null) return { main: compose, alt: mailApp };
  // The thread itself: the answer is pasted under its last message, so it stays in the thread.
  const thread: DraftOpenStep = {
    label: "Copy & open the thread in Gmail",
    hint: `Copies the text and opens the conversation in Gmail for ${from}. Press reply, paste it in, then press send: it stays in the thread.`,
    url: `${GMAIL}u/${encAddress(from)}/#all/${hex}`,
    copy: true,
    note: "Copied, and the thread is open in Gmail: press reply, paste the text in, then press send",
  };
  return { main: thread, alt: { ...compose, label: compose.label.replace("Open in", "New message in") } };
}

/**
 * The action for one draft. `address` is the recipient's address for an email (or several,
 * comma-joined), "" when it isn't known. Links carry the draft's text and subject and that
 * address, nothing else.
 */
export function draftOpen(d: Draft, address: string, phone = ""): DraftOpen {
  const target = openTarget(d);
  switch (target) {
    case "email": {
      const { main, alt } = emailSteps(d, address);
      return { target, ...main, alt };
    }
    case "whatsapp": {
      const text = fits(d.body);
      if (/^\d{7,15}$/.test(phone)) {
        // The chat itself, not the picker: the reader reads it over and presses send.
        return {
          target,
          label: text === null ? "Copy & open the chat" : "Open the chat",
          hint:
            text === null
              ? `Copies the text and opens your chat with ${d.to}. Paste it, then press send.`
              : `Opens your chat with ${d.to} with the text filled in. Read it over, then press send.`,
          url: text === null ? `whatsapp://send?phone=${phone}` : `whatsapp://send?phone=${phone}&text=${text}`,
          copy: text === null,
          note: text === null ? "Copied, and the chat is open: paste it in and press send" : "The chat is open: press send when it reads right",
          alt: null,
        };
      }
      return {
        target,
        label: text === null ? "Copy & open WhatsApp" : "Open in WhatsApp",
        hint:
          text === null
            ? "The text is too long for a link: copies it, and opens WhatsApp. Paste it into the chat, then press send."
            : "Opens WhatsApp's chat picker with the text filled in. Choose the chat, then press send.",
        url: text === null ? "whatsapp://send" : `whatsapp://send?text=${text}`,
        copy: text === null,
        note: text === null ? "Copied, and WhatsApp is open: choose the chat and paste" : "WhatsApp is open: choose the chat, then press send",
        alt: null,
      };
    }
    case "slack":
      return {
        target,
        label: "Copy & open Slack",
        hint: "Copies the text and opens Slack. Paste it where it goes, then press send.",
        url: "slack://open",
        copy: true,
        note: "Copied, and Slack is open: paste it in and press send",
        alt: null,
      };
    case "linkedin":
      return {
        target,
        label: "Copy & open LinkedIn",
        hint: "Copies the text and opens LinkedIn. Paste it where it goes, then press send.",
        url: LINKEDIN_FEED,
        copy: true,
        note: "Copied, and LinkedIn is open: paste it in and press send",
        alt: null,
      };
    case "instagram":
      return {
        target,
        label: "Copy & open Instagram",
        hint: "Copies the text and opens your Instagram messages. Paste it into the chat, then press send.",
        url: INSTAGRAM_INBOX,
        copy: true,
        note: "Copied, and Instagram is open: paste it into the chat and press send",
        alt: null,
      };
    case "x":
      return {
        target,
        label: "Copy & open X",
        hint: "Copies the text and opens your X messages. Paste it into the chat, then press send.",
        url: X_MESSAGES,
        copy: true,
        note: "Copied, and X is open: paste it into the chat and press send",
        alt: null,
      };
    case "messenger":
      return {
        target,
        label: "Copy & open Messenger",
        hint: "Copies the text and opens Messenger. Paste it into the chat, then press send.",
        url: MESSENGER,
        copy: true,
        note: "Copied, and Messenger is open: paste it into the chat and press send",
        alt: null,
      };
    default:
      return {
        target: "file",
        label: "Download",
        hint: "Saves the draft as a markdown file.",
        url: null,
        copy: false,
        note: "Downloaded as a markdown file",
        alt: null,
      };
  }
}
