# Proxenos for everyone

Today Proxenos needs a terminal, conda, Node and a hand-edited `.env`. Track 2 of the [roadmap](roadmap.md) removes all four. This is the plan for its first three steps: one download, connecting instead of configuring, and a clear privacy screen. The first two pieces are built: the Connect page, and setup with settings and the Keychain in place of `.env` (see [the end](#built-so-far)).

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

*Built.* The first launch shows one short setup page:
1. **Your name**, for the notes and the self-model.
2. **Where the vault lives**: `~/proxenos_vault` unless you pick another folder. It warns about folders iCloud syncs (Desktop and Documents by default) and other cloud drives.
3. **A model**: one on this Mac through Ollama (the page checks Ollama is running and lists the models it has pulled), or an Anthropic API key, pasted once and checked with one small call. You can skip this: sources still sync and search works, but nothing is drafted.
4. **Connect a first source**, on the Connect page.

Your email addresses will come from the accounts you connect, not from typing them. That part isn't built: `PROXENOS_EMAILS` is still read from the environment, `.env` or the settings file.

| Today in `.env` | In the app |
|---|---|
| `PROXENOS_VAULT`, `PROXENOS_NAME`, `PROXENOS_EMAILS`, the folder settings | `settings.json` in `~/Library/Application Support/Proxenos/`, changed from a Settings page |
| `ANTHROPIC_API_KEY`, `GMAIL_*`, `SLACK_USER_TOKEN*`, `STRAVA_REFRESH_TOKEN` | The macOS Keychain, one item per secret |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `STRAVA_CLIENT_*` | Shipped with the app: Proxenos's own sign-in clients, so nobody makes a cloud project. Until then, pasted once in Settings and kept in the Keychain |

In code, `config.env()` reads the environment, then `.env` (from source only), then the settings file, then the Keychain, so a developer's `.env` keeps working. `auth.set_env` became one `config.save_secret` that writes to the Keychain in the app and to `.env` from source.

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
2. **Settings and the Keychain** behind `config.env()`, the setup page and Settings (built).
3. The privacy screen, the call log and delete everything.
4. More connect steps: downloads with drop zones, Slack and Strava sign-in, folders.
5. The Electron shell, the bundled runtime, signing, notarization and updates.

## Built so far

### The Connect page

- `proxenos connect` prints every source as JSON: whether it's connected, when it was last read, and what's missing. It reports names, addresses and handles, never a token, password or key.
- `GET /api/connect` runs it. `POST /api/connect/gmail` starts `proxenos auth gmail NAME ADDRESS` and `POST /api/connect/whatsapp` starts `proxenos ingest whatsapp`, each in the background and one at a time; the page follows them through `GET /api/connect/jobs`, and `POST /api/connect/cancel` stops one. A job reports only the command's last line, with anything that looks like a token blanked.
- Every route answers only the page itself: a loopback host and the same origin.

### Setup and Settings

- **Where things are read from**, first to last: the process's environment; the repo's `.env`, only when running from source (a checkout has `pyproject.toml`); `~/Library/Application Support/Proxenos/settings.json`; the macOS Keychain. `config.load` puts what the last three hold into the environment once per process, never over a variable that's already set, so every reader sees the same order and code that reads `os.environ` directly keeps working.
- **The settings file** holds `PROXENOS_<NAME>` settings by their lower-case name (`{"name": ..., "vault": ..., "model": ..., "docs_dirs": ...}`) and, under `"keychain"`, the names (never the values) of the secrets kept in the Keychain. It and its folder are private to you (0600, 0700).
- **The Keychain** (`keychain.py`) keeps one generic password per secret: service `Proxenos`, account the variable's name. Everything goes through the `security` command. A value never goes on a command line: it's written through `security -i`, which reads its commands from stdin, as hex, and read back to check it was saved.
- **Saving:** `config.save_secret(name, value)` writes to `.env` when running from source with one, else to the Keychain, and only accepts Proxenos's secrets (`ANTHROPIC_API_KEY`, `GMAIL_*`, `SLACK_USER_TOKEN*`, `STRAVA_*`, `GOOGLE_CLIENT_*`, `BEEPER_ACCESS_TOKEN`). `config.save_setting` does the same for settings, with the settings file in place of the Keychain. Every `proxenos auth` sign-in and `proxenos phone` use them.
- **`proxenos setup`** prints where things stand as JSON: the settings and where each comes from, the vault (whether it exists, whether a cloud syncs it), the model, Ollama's pulled models, and whether each secret is set and where. `proxenos setup --apply` makes one change read as JSON from stdin: settings (the vault folder is made, private, and refused inside the repo), an Anthropic key (checked by asking for the model it will use, which costs no tokens), a local model (checked against Ollama), or a secret replaced or removed.
- **The page:** `/app` sends a first run (no name and no vault set anywhere) to `/setup`, which goes through the four steps above. The Settings view (the "You" group) changes the name, the vault, the model, the folders read on every sync, and each secret, which it shows only as set or not and where it's kept, with Replace and Remove. `GET` and `POST /api/setup` run `proxenos setup`; a key or token goes to it on stdin and nowhere else, and no answer holds one. The route answers only the page itself, as the others do: a loopback host, the same origin, and a JSON body.
