# Data sources

Every source is optional and works on its own. Start with one or two and add more later, in any order. Each ingester writes monthly files into your vault, and re-running one is always safe: records merge by id, so nothing is duplicated.

## How data gets in

- **Downloads.** Request an export from the service, put the zip (or the unzipped folder) in the repo's `data/` folder or in `<vault>/inbox/`, and run `proxenos import`. It recognizes each export, unpacks it, hands it to the right ingester and files the download away. Exports that arrive in several zips (Google Takeout, Meta) are imported together.
- **Live sources.** WhatsApp (its local store), Gmail (IMAP), Apple Mail (its local store), Slack, Strava, Bluesky and public mentions are read directly, and `proxenos sync` refreshes them. `sync` also imports anything waiting in the inboxes, so one command keeps everything current. The page's Connect view shows every source and whether it's connected, with buttons to sign in to Gmail and to read WhatsApp now.
- **Folders you name.** A Spotify export, a website repo and slackdump runs live wherever you keep them. Point Proxenos at them in `.env` (see [the settings below](#folder-settings)).

The `ingest` commands in the tables are for reading one source by hand. Anything that arrives as a download can go through `proxenos import` instead. Credentials and settings live in `.env`; [.env.example](../.env.example) lists them all.

## Sources

### Messages and social

| Source | What it adds | How to get it | Command |
|---|---|---|---|
| **WhatsApp** | Your messages, your groups and who is in them: your everyday voice and your relationships | The WhatsApp Mac app, signed in. Proxenos reads the app's local database, so the terminal that runs it needs Full Disk Access (System Settings, Privacy & Security). The Mac app may hold less history than your phone. | `proxenos ingest whatsapp` (`--db PATH` for a copy elsewhere) |
| **Slack** (token) | Your work-casual voice and your collaborators | A user OAuth token (`xoxp-...`) as `SLACK_USER_TOKEN` in `.env`, one per workspace (`SLACK_USER_TOKEN_<name>` for more). `proxenos auth slack` can create a read-only app and fetch the token from a configuration token. A workspace admin may need to approve the app, since the workspace owns the data. | `proxenos ingest slack` (`--full` to re-read everything) |
| **Slack** (slackdump) | The same, with no token or app, kept current | Install [slackdump](https://github.com/rusq/slackdump) (`brew install slackdump`) and run `proxenos auth slackdump WORKSPACE` once per workspace (the name in its address, e.g. `acme` for acme.slack.com): you sign in in the browser, and its last 30 days are saved to `data/` without attachments. Each sync then fetches what's new into the newest archive of every signed-in workspace (`slackdump resume`). Archives you made yourself (`slackdump_<date>_<time>/` folders) are read too, from `data/` or `PROXENOS_SLACKDUMP_DIR`. | `proxenos ingest slackdump` (`--root DIR`, `--offline` to skip fetching) |
| **LinkedIn** | Profile, career, posts, comments, messages and connections | Settings, Data privacy, Get a copy of your data | `proxenos ingest linkedin --export DIR` |
| **X / Twitter** | Posts, DMs and likes | Settings, Your account, Download an archive of your data | `proxenos ingest twitter --export DIR` |
| **Instagram**, **Facebook** | Messages, posts and comments (Instagram likes too): how you present yourself and your older social life | Accounts Center, Your information and permissions, Download your information. Choose JSON, all time, and include messages. A big export arrives as several zips; unzip them into one folder. | `proxenos ingest instagram --export DIR`, `proxenos ingest facebook --export DIR` |
| **Threads** | Posts and replies | The same Download your information page, with Threads selected | `proxenos ingest threads --export DIR` |
| **Instagram, Messenger, LinkedIn chats, live** | New messages as they come, so replies get drafted | [Beeper Desktop](https://www.beeper.com), free for up to five accounts: connect only these there (Proxenos reads WhatsApp, Slack and email itself). Turn on its API in Settings, create a token (Settings, Integrations, + by Approved connections) and put it in `.env` as `BEEPER_ACCESS_TOKEN`. Beeper must be running; the first sync reads the last 90 days. | `proxenos ingest beeper` (`--full`) |
| **Bluesky** | Your public posts, replies and reposts | Your handle as `PROXENOS_BLUESKY_HANDLE`. No sign-in needed. | `proxenos ingest bluesky` (`--full`) |

### Email

| Source | What it adds | How to get it | Command |
|---|---|---|---|
| **Email, any provider** | Sent mail is your professional and personal voice. Received mail is context. | An mbox export: Takeout's Mail folder, or one from your mail client. Set `PROXENOS_EMAILS` to all your addresses so Proxenos knows which mail is yours. | `proxenos ingest email --account NAME --mbox PATH` |
| **Gmail over IMAP** | The same, kept current | Turn on IMAP in Gmail's settings. Then either make an [app password](https://myaccount.google.com/apppasswords) (it needs 2-Step Verification) and add `GMAIL_<NAME>=address:app-password` to `.env`, or, where app passwords aren't allowed, sign in with Google: in [Google Cloud](https://console.cloud.google.com/) make a project, turn on the Gmail API, set up the OAuth consent screen (External, add yourself as a test user), create an OAuth client of type *Desktop app*, put its ID and secret in `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, and run `proxenos auth gmail NAME ADDRESS`. One account per name. The first run backfills everything. | `proxenos ingest gmail` (`--account NAME`, `--full`) |
| **Apple Mail** | The same, for every account in the Mac's Mail app, kept current with no sign-in or app of your own | Add each account in System Settings, Internet Accounts (Gmail, Google Workspace and Microsoft 365 or Outlook all work), and keep Mail open, or set it to open at login, so it fetches. Give the Python that runs Proxenos Full Disk Access (System Settings, Privacy & Security): macOS keeps `~/Library/Mail` private until then, and `proxenos ingest applemail` names the Python when it's blocked. Set `PROXENOS_EMAILS` to all your addresses: each Mail account is filed under the one that appears most in its mail, and an account with none is skipped (run `--full` once you've added it). Junk, spam and trash are left out. Proxenos only reads what Mail has downloaded and never changes Mail's files. The first run reads the last 180 days. After that, `proxenos sync` reads what changed on every run. | `proxenos ingest applemail` (`--full` to read everything, `--root DIR` for a copy) |

### Google Takeout

Request one export at [takeout.google.com](https://takeout.google.com) with the products below, then `proxenos import` the zips. For YouTube history, pick JSON if Takeout offers the choice (HTML is read too).

| Product | What it adds | Command |
|---|---|---|
| **Mail** | As above, one stream per address | `proxenos ingest email ...` |
| **Calendar** | Events, guests and repeating events: your schedule and the people you meet. Google Calendar's own export (Settings, Import & export) works too. | `proxenos ingest calendar --export DIR` |
| **Drive** | The text of documents, slides, spreadsheets, PDFs and plain-text files: what you write and work on | `proxenos ingest drive --export DIR` |
| **Google Photos** | Metadata only (dates, places, tagged people, albums). The photos and videos stay in the zip. | `proxenos ingest photos --export DIR` |
| **Keep**, **Tasks** | Your notes and task lists | `proxenos ingest keep --export DIR`, `proxenos ingest gtasks --export DIR` |
| **YouTube and YouTube Music** | What you watch and search for: interests and taste | `proxenos ingest youtube --export DIR` |
| **Chrome** | Browsing history that Chrome synced to your Google account | `proxenos ingest chrome --export DIR` |

### Activity and habits

| Source | What it adds | How to get it | Command |
|---|---|---|---|
| **Strava** | Your training: routine and discipline | Create an app at [strava.com/settings/api](https://www.strava.com/settings/api), put `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` in `.env`, then run `proxenos auth strava` and approve in the browser. The refresh token is saved to `.env`. | `proxenos ingest strava` (`--full`) |
| **Spotify** | What you listen to, when: taste, mood and daily rhythm | Account, Privacy settings, then request your **Extended streaming history**. It can take up to 30 days. Unzip it and set `PROXENOS_SPOTIFY_EXPORT` to the folder holding `Streaming_History_Audio_*.json`. Request a newer export now and then: plays you already have are a no-op, and new ones are added. | `proxenos ingest spotify` (`--export DIR` for another folder) |
| **Letterboxd** | Your diary, ratings, reviews and watchlist | Settings, Data, Export your data | `proxenos ingest letterboxd --export DIR` |

### Writing and reading

| Source | What it adds | How to get it | Command |
|---|---|---|---|
| **Notion**, **Obsidian**, **PDFs** | Your notes and what you read | Notion: Settings, Export, as Markdown & CSV (or PDF). Obsidian: the vault folder. PDFs: any folder of them. | `proxenos ingest notes --export DIR` (`--pdf-dir DIR` for PDFs) |
| **Personal website** | Your long-form voice and thinking: pages, posts and a CV data file if the site keeps one | A local git repo of the site (Jekyll or plain HTML or Markdown). Set `PROXENOS_WEBSITE_REPO` to it. Pages are dated from their front matter, their own markup, their path, or the day git first saw them. | `proxenos ingest website` (`--repo DIR`) |
| **Papers and mentions** | Public mentions of you in the news, your papers on OpenAlex and the papers that cite them | Your name as `PROXENOS_FULL_NAME`. Add `PROXENOS_OPENALEX_ID` if the name search picks the wrong author profile. | `proxenos ingest mentions` |

Services with no API for personal messages (Facebook, Instagram, LinkedIn, X, Spotify's full history) only update when you request a fresh export. Do it every few months and import it; what overlaps is a no-op.

Missing a source? [CONTRIBUTING.md](../CONTRIBUTING.md) shows how to add one.

## Folder settings

Three sources live in folders Proxenos can't guess, so each has a setting in `.env`. A leading `~` is expanded.

| Setting | Points at | When it's not set |
|---|---|---|
| `PROXENOS_SPOTIFY_EXPORT` | The folder holding `Streaming_History_Audio_*.json` | `proxenos ingest spotify` stops and names the setting. `proxenos sync` skips Spotify. |
| `PROXENOS_WEBSITE_REPO` | Your site's local git repo | `proxenos ingest website` stops and names the setting. `proxenos sync` skips the website. |
| `PROXENOS_SLACKDUMP_DIR` | A folder holding `slackdump_*` runs | Only the repo's `data/` folder is searched. |

A path passed on the command line (`--export`, `--repo`, `--root`) always wins over the setting.

## What the data can and can't tell Proxenos

- **It records what you did and said, not why.** Your reasons, doubts and the things you thought but never wrote down only come from what you tell Proxenos directly and from your reactions on the page.
- **Most of it is who you have been.** A message from years ago is evidence about you then. Every record keeps its date, the self-model is always "as of" a date, and recent evidence counts for more. The upside is that Proxenos can model how you change, not just a snapshot.

## Where to start

Voice comes in registers (personal chat, work chat, email), and the self-model keeps them apart instead of averaging them. A good order:

1. **What you wrote:** your messages (WhatsApp, Slack), sent email, your website and notes. This gives voice and beliefs.
2. **What you read and watched:** YouTube, Chrome, notes, papers. This gives interests and taste.
3. **How you live:** Calendar, Strava, Spotify. This gives routine and rhythm.

## Privacy

1. **Raw data stays on your computer, outside this repo.** The repo is public code, so the vault lives elsewhere (`PROXENOS_VAULT`, default `~/proxenos_vault`) and Proxenos refuses a vault inside the repo. Keep it out of folders a cloud service syncs (iCloud syncs Desktop and Documents by default), and turn on FileVault.
2. **Other people are in your data.** You can consent for yourself, not for everyone you've talked to. Proxenos models you: your side of conversations and how you relate to people. It doesn't build profiles of others, and their words are kept as context, not as subjects.
3. **Work and school accounts are institutional.** Mail and chat from them may hold information about colleagues, students, patients or research participants that isn't yours to share. Check your institution's policy on sending it to an external model, and leave those sources out if in doubt.
4. **Raw data never goes to the model wholesale.** Years of email is tens of millions of tokens, mostly newsletters and notifications. Observers read one month of one source at a time and only your own side (sent mail, your messages, your plays). Later steps read the distilled self-model. There are two exceptions. The tasks clone, to find what is asked of you, sends recent conversations you're part of, and leaves newsletters, notifications and promotions out. The care clone sends only records about getting health care (visits, tests, referrals, bills, insurance, records, symptoms), picked out in code by keyword from the last 120 days; people in chats become "contact 1", "contact 2", and phone, account and member numbers, email addresses and links are blanked before anything leaves.
5. **Secrets stay in `.env`,** which git ignores: API keys, tokens and app passwords. Never put them, or any personal data, in an issue or a commit.
