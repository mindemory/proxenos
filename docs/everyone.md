# Proxenos for everyone

Today Proxenos needs a terminal, conda, Node and a hand-edited `.env`. Track 2 of the [roadmap](roadmap.md) removes all four. This is the plan for its first three steps: one download, connecting instead of configuring, and a clear privacy screen. The first piece, the Connect page, is built (see [the end](#the-connect-page-today)).

## One download: a menu-bar app

Three things have to ship together:
- **The Python package** (`src/proxenos`) and its dependencies: the ingesters, the master and the clones.
- **The page** (`web/`): a Next.js app whose API routes read the vault with Node and run the `proxenos` command.
- **A shell:** the menu-bar icon (open the page, sync now, pause, quit), the nightly run and the first-run setup.

### Options

| Piece | Option | For | Against |
|---|---|---|---|
| Python | **py2app** | Mature. Builds a `.app` around a Python program, interpreter included. | Signing and notarizing the result is by hand. No answer for Node. |
| Python | **Briefcase** (BeeWare) | Bundles a standalone Python, and signs and notarizes (`briefcase package macOS`). | Its own app layout and GUI toolkit (Toga). No answer for Node either. |
| Python | **A bundled runtime** ([python-build-standalone](https://github.com/astral-sh/python-build-standalone)) | A relocatable CPython: install the `proxenos` wheel into it at build time and put the folder inside any shell. | The shell must sign every `.so` and `.dylib` in it. |
| Shell | **Electron** | Node is built in, so it runs the page's server with no second runtime. Mature tray, signing (`@electron/osx-sign` signs every binary in the bundle) and notarization. | Chromium makes it large, on the order of 100 MB. |
| Shell | **Tauri** | Small (it uses the system's WebKit), with a tray API, signing and notarization. | The page's server still needs Node, so it ships two sidecar runtimes, Node and Python. Adds Rust to the project. |

### Recommendation: Electron around a bundled Python

- **The page:** `next build` with `output: "standalone"`, run by Electron's own Node (a `utilityProcess`) on a free loopback port picked at launch, not a fixed 4747. The window is an Electron window on that port; the route guard stays as it is.
- **Python:** python-build-standalone with the `proxenos` wheel installed, under `Contents/Resources/python`. The shell sets `PROXENOS_BIN` to its `proxenos`, which the page already honours.
- **The menu bar:** Open Proxenos, Sync now, Last synced …, Pause, Quit. No Dock icon.
- **Nights:** the app opens at login and runs `proxenos night` itself at 01:30, replacing the launchd job from `scripts/install-night.sh`.
- **Signed once, trusted once:** Developer ID, hardened runtime, notarized and stapled, updated from signed GitHub releases. macOS grants Full Disk Access (which WhatsApp needs) to `Proxenos.app` itself, and the commands it starts inherit it. Keeping one signing identity keeps that grant across updates.

Why not the others: py2app and Briefcase solve only the Python half, and Tauri would carry Node anyway. Once the API routes move to Python, the page becomes a static export served by the Python process, and a Tauri or Briefcase shell around one Python sidecar is the smaller app. Revisit then.

`proxenos web` and `Proxenos.command` stay for people running from source.

## Setup replaces `.env`

The first launch shows one short setup page:
1. **Your name**, for the notes and the self-model.
2. **Where the vault lives**: `~/proxenos_vault` unless you pick another folder. It warns about folders iCloud syncs (Desktop and Documents by default).
3. **A model key**: paste an Anthropic API key once; one small call checks it. You can skip this: sources still sync and search works, but nothing is drafted.
4. **Connect a first source**, on the Connect page.

Your email addresses come from the accounts you connect, not from typing them.

| Today in `.env` | In the app |
|---|---|
| `PROXENOS_VAULT`, `PROXENOS_NAME`, `PROXENOS_EMAILS`, the folder settings | `settings.json` in `~/Library/Application Support/Proxenos/`, changed from a Settings page |
| `ANTHROPIC_API_KEY`, `GMAIL_*`, `SLACK_USER_TOKEN*`, `STRAVA_REFRESH_TOKEN` | The macOS Keychain, one item per secret |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `STRAVA_CLIENT_*` | Shipped with the app: Proxenos's own sign-in clients, so nobody makes a cloud project |

In code, `config.env()` reads the environment, then `.env` (from source only), then the settings file, then the Keychain, so a developer's `.env` keeps working. `auth.set_env` becomes one `save_secret` that writes to the Keychain in the app and to `.env` from source.

Shipping our own Google client is allowed for a desktop app (its secret isn't treated as confidential, and the flow already uses PKCE), but Gmail's mail scope is restricted. An app other people use needs Google's verification, which can include a yearly security assessment. Until that's done, the app keeps today's bring-your-own-client path and app passwords.

## Connect, step by step

The Connect page lists every source, whether it's connected and when it was last read. Each source gets one guided step:

| Source | The step |
|---|---|
| **Gmail** | *Built.* A short name and the address, then **Sign in with Google**. The browser opens Google's consent page; Proxenos catches the answer on 127.0.0.1:8723 and saves the token. The page shows the address, never the token. Later: an app-password field as the fallback. |
| **WhatsApp** | *Built.* **Read WhatsApp now** reads the Mac app's local store. If macOS blocks it, the page says so and links to System Settings, Full Disk Access: allow Proxenos there and press again. |
| **Calendar, Drive** | The same Google sign-in with read-only calendar and drive access, instead of a Takeout import. |
| **Slack** | **Sign in with Slack** to Proxenos's own read-only app, instead of a configuration token and a pasted user token. A workspace admin may still need to approve it. |
| **Strava** | **Sign in with Strava**: today's flow with Proxenos's own Strava app, so there's nothing to paste. |
| **Bluesky, mentions** | One field each: your handle, your full name. |
| **Downloads** (LinkedIn, X, Instagram, Facebook, Threads, Google Takeout, Spotify, Letterboxd) | A page per service: a link to its download page, which options to pick (JSON, all time, include messages), how long it takes, and a drop zone. A dropped zip goes to `<vault>/inbox/` and `proxenos import` runs. The page remembers when you asked and reminds you to check your mail. |
| **Folders** (Notion or Obsidian notes, PDFs, a website repo, slackdump runs) | A folder picker from the menu-bar app (a web page can't learn a folder's path), saved as the setting. |

Every step ends the same way: a first read in the background, its progress on the page, then the source marked connected with its last read time.

## The privacy screen

One screen with three lists, drawn from what the code does:
- **Stays on this computer:** the vault (raw data, notes, the self-model, drafts, the memory index), with its location and size, and the secrets in the Keychain.
- **Sent to the model** (Anthropic, under your key): what each observer and clone sends, in plain words (the list in [data_sources.md](data_sources.md#privacy)), and the last 30 days of calls: when, which clone, how many tokens. This needs `llm.py` to log one line per call.
- **Fetched from elsewhere:** the services you connected, read with your sign-in, and the pages linked in chats waiting on you (public hosts only).

**Delete everything** sits at the bottom:
- It lists what it removes: the vault folder with its git history, every Proxenos item in the Keychain, the settings, logs and caches. It also revokes each sign-in where the service allows it (Google, Slack and Strava each have a revoke call).
- You type `delete` to confirm. It's permanent: nothing goes to the Trash.
- It says what it can't reach: your accounts' own data (your mail stays in Gmail), what was already sent to Anthropic (their retention applies), and backups of the vault, Time Machine included.
- Afterwards the app is back at first-run setup. `proxenos forget` does the same from a terminal.

## Order of work

1. **The Connect page** (built): every source's status, Gmail sign-in, Read WhatsApp now.
2. Settings and the Keychain behind `config.env()`, and the setup page.
3. The privacy screen, the call log and delete everything.
4. More connect steps: downloads with drop zones, Slack and Strava sign-in, folders.
5. The Electron shell, the bundled runtime, signing, notarization and updates.

## The Connect page today

- `proxenos connect` prints every source as JSON: whether it's connected, when it was last read, and what's missing. It reports names, addresses and handles, never a token, password or key.
- `GET /api/connect` runs it. `POST /api/connect/gmail` starts `proxenos auth gmail NAME ADDRESS` and `POST /api/connect/whatsapp` starts `proxenos ingest whatsapp`, each in the background and one at a time; the page follows them through `GET /api/connect/jobs`, and `POST /api/connect/cancel` stops one. A job reports only the command's last line, with anything that looks like a token blanked.
- Every route answers only the page itself: a loopback host and the same origin.
