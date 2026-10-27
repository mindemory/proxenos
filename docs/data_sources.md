# Data sources

Decided 2026-10-27: everything is in bounds. That covers all three email accounts, WhatsApp, Slack, Facebook, Instagram, Strava, Spotify, and the rest.

Two things this data can't do on its own:
- **It records what I did and said, not why.** Reasons, doubts, and the things I thought but never wrote down only come from the interview and the morning reactions. Those stay in the plan.
- **Most of it is who I *have been*.** A 2016 message is evidence about 2016-me. Every record keeps its date. The self-model is always "as of" some date, and recent evidence counts for more. The upside is that the twin can model the *trajectory*, not just a snapshot.

## Build status (2026-10-27)

| Source | Command | State |
|---|---|---|
| WhatsApp | `twin ingest whatsapp` | Running on real data. The Mac app holds only recent years; older chats live on the phone. |
| Spotify | `twin ingest spotify` | Running on real data from an Extended Streaming History export |
| Strava | `twin ingest strava` | Running on real data. `twin auth strava` gets a token with activity access. |
| Slack | `twin ingest slack` | Built and tested; needs `SLACK_USER_TOKEN` |
| Email | `twin ingest email --account NAME --mbox PATH` | Built and tested; waiting on mbox exports |
| Facebook, Instagram, Paperpile, blog, notes, Mac activity, AI conversations | | Not built yet |

## Every source needs two paths

- **Backfill:** a one-time pull of all history.
- **Daily sync:** the nightly delta.

Some sources only offer a bulk export. Those get refreshed by re-requesting the export now and then.

| Source | What it tells the twin | Backfill | Daily sync | Notes |
|---|---|---|---|---|
| **Gmail** (personal) | Personal life, plans, relationships. Sent mail is the voice. | Google Takeout → Mail (mbox) | Gmail API, read-only scope, `after:` query | Add Calendar, Chrome history, and YouTube history to the same Takeout request. |
| **University email** | Work, research, professional voice | Export from the mail client to mbox | Microsoft Graph or IMAP, whichever the university allows | Institutional account, see ground rules. |
| **Third email** | ? | ? | ? | Provider TBD |
| **WhatsApp** | Closest thing to my unfiltered voice. Relationships. | The Mac app's local SQLite (`~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite`) | Same DB, new rows since the last run | Reading it needs Full Disk Access for the terminal. The desktop app may not hold full history (the phone does), so check how far back it goes. |
| **Slack** | Work-casual voice, collaborations | Members' workspace exports cover public channels only. My DMs need the API with a user token. | Slack API, same token | Installing a token-bearing app may need workspace admin approval. The workspace owns the data. |
| **Facebook + Instagram** | Older social self, interests, how I present publicly | Accounts Center → Download your information → JSON, all time, include messages | None. No API for personal messages, so re-request quarterly. | Mostly past-me |
| **Strava** | Routine, discipline, physical life | Settings → My Account → request archive (activities + GPX) | `twin ingest strava` (API) | |
| **Spotify** | Taste, mood, daily rhythm | Extended Streaming History export. Re-request it now and then; it takes up to 30 days. | Web API recently-played (last 50 tracks only) | 50 tracks is a few hours, so either poll several times a day or accept gaps and patch them from the next extended export. |
| **Paperpile** | What I read for research | `.bib` already auto-exported to GitHub (`notion_paperpile`) | `git pull` | |
| **Blog** | Long-form voice and thinking | `mindemory.github.io` repo | `git pull` | |
| **Notes** | Personal writing | `Notes/*.pages` | Watch the folder | Needs conversion: Pages can export text via AppleScript. |
| **Mac activity** | How I actually spend time | `phronesis` DB | Same DB | |
| **AI conversations** | What I'm curious about, and how I think out loud | Claude and ChatGPT data exports; Claude Code transcripts in `~/.claude/projects` | Re-export periodically | Not mentioned yet, but high signal. |

## Start these today (they take hours to weeks)

1. **Google Takeout:** Gmail, Calendar, Chrome, YouTube.
2. **Meta Download Your Information**, once each for Facebook and Instagram. Use JSON format, all time, messages included.
3. **Spotify Extended Streaming History.** This takes up to 30 days.
4. **Strava** full archive.
5. **Claude and ChatGPT** data exports.

Downloads go in `$TWIN_VAULT/raw/<source>/<export-date>/`. They never go anywhere inside this repo, because it's public.

## Ground rules for this much data

1. **Raw data stays on this Mac, outside this repo.** The repo is public on GitHub, so the vault lives elsewhere (`TWIN_VAULT`, default `~/twin_vault`). It shouldn't be under Desktop or Documents either, since iCloud may sync those. FileVault should be on.
2. **Other people are in this data.** I can consent for myself, not for the people I've talked to. The twin models *me*: my side of conversations and how I relate to people. It does not build profiles of others. Their words are kept as context, not as subjects.
3. **University email and Slack are institutional.** They may contain student or research-participant information. Check the institution's policy on sending this to an external model, and filter if needed.
4. **Raw data never goes to an API model wholesale.** Years of email is tens of millions of tokens, mostly newsletters and notifications. Filter and distill locally first. Sent mail and my own messages come first; received mail is context.
5. **Secrets** (API tokens, OAuth credentials) go in `.env`, which is already ignored.

## Ingestion order

1. **What I wrote:** sent email, my WhatsApp and Slack messages, the blog, notes. This gives voice and beliefs.
2. **What I read and watched:** Paperpile, browser history, YouTube, AI conversations. This gives interests and taste.
3. **How I live:** Calendar, Strava, Spotify, Phronesis. This gives routine and rhythm.

Voice comes in registers: professional (email), work-casual (Slack), and personal (WhatsApp). `voice.md` should keep them apart rather than averaging them.
