# Proxenos for everyone

Today Proxenos needs a terminal, conda, Node and a hand-edited `.env`. Track 2 of the [roadmap](roadmap.md) removes all four. This is the plan for its first three steps: one download, connecting instead of configuring, and a clear privacy screen. Four pieces are built: the Connect page, setup with settings and the Keychain in place of `.env`, the privacy screen, apart from Delete everything, and a first, unsigned desktop app (see [the end](#built-so-far)). For Windows and Android, see [apps.md](apps.md).

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
- **Python:** python-build-standalone with the `proxenos` wheel installed, under `Contents/Resources/python`. The shell sets `PROXENOS_PYTHON` to it and the page runs `python -m proxenos`, since the `proxenos` script pip writes names the Python it was installed with and can't move with the app.
- **The menu bar:** Open Proxenos, Sync now, Last synced …, Pause, Quit. No Dock icon.
- **Nights:** the app opens at login and runs `proxenos schedule` (built), which runs `proxenos night` at 01:30 and a sync every 15 minutes, replacing the launchd jobs from `scripts/install-night.sh` and `scripts/install-app.sh` ([apps.md](apps.md#keeping-it-running-from-source)).
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
| **Microsoft 365 and Outlook** | *Built.* Like Gmail: a short name and the address, then **Sign in with Microsoft**, against the person's own app registration (`MICROSOFT_CLIENT_ID`). Mail and calendar, read-only, on any computer. |
| **Google Calendar** | *Built.* Like Gmail, with a sign-in of its own that only reads the calendar. |
| **Drive** | The same Google sign-in with read-only drive access, instead of a Takeout import. |
| **Slack** | **Sign in with Slack** to Proxenos's own read-only app, instead of a configuration token and a pasted user token. A workspace admin may still need to approve it. |
| **Strava** | **Sign in with Strava**: today's flow with Proxenos's own Strava app, so there's nothing to paste. |
| **Bluesky, mentions** | One field each: your handle, your full name. |
| **Downloads** (LinkedIn, X, Instagram, Facebook, Threads, Google Takeout, Spotify, Letterboxd) | A page per service: a link to its download page, which options to pick (JSON, all time, include messages), how long it takes, and a drop zone. A dropped zip goes to `<vault>/inbox/` and `proxenos import` runs. The page remembers when you asked and reminds you to check your mail. |
| **Folders** (Notion or Obsidian notes, PDFs, a website repo, slackdump runs) | A folder picker from the menu-bar app (a web page can't learn a folder's path), saved as the setting. |

Every step ends the same way: a first read in the background, its progress on the page, then the source marked connected with its last read time.

## The privacy screen

*Built, apart from Delete everything* ([below](#the-privacy-screen-1)). One screen with three lists, drawn from what the code does:
- **Stays on this computer:** the vault (raw data, notes, the self-model, drafts, the memory index), with its location and size, and the secrets in the Keychain.
- **Sent to the model** (Anthropic, under your key): what each observer and clone sends, in plain words (the list in the README's [Privacy](../README.md#privacy) section), and the last 30 days of calls: when, which clone, how many tokens. *Built:* `llm.py` logs one line per call to `<vault>/state/model-calls.jsonl` (when, which part asked, the model, where it ran, characters and tokens in and out, seconds, whether it worked), never the words.
- **Fetched from elsewhere:** the services you connected, read with your sign-in, and the pages linked in chats waiting on you (public hosts only).

**Delete everything** (not built yet) sits at the bottom:
- It lists what it removes: the vault folder with its git history, every Proxenos item in the Keychain, the settings, logs and caches. It also revokes each sign-in where the service allows it (Google, Slack and Strava each have a revoke call).
- You type `delete` to confirm. It's permanent: nothing goes to the Trash.
- It says what it can't reach: your accounts' own data (your mail stays in Gmail), what was already sent to Anthropic (their retention applies), and backups of the vault, Time Machine included.
- Afterwards the app is back at first-run setup. `proxenos forget` does the same from a terminal.

## Order of work

1. **The Connect page** (built): every source's status, Gmail sign-in, Read WhatsApp now.
2. **Settings and the Keychain** behind `config.env()`, the setup page and Settings (built).
3. The privacy screen and the call log (built), and delete everything.
4. More connect steps: downloads with drop zones, Slack and Strava sign-in, folders.
5. The Electron shell and the bundled runtime (built, unsigned), then signing, notarization and updates.

## Built so far

### The desktop app

*Built, unsigned.* `desktop/` is the menu-bar app the recommendation above describes, for macOS on Apple silicon and Windows x64:
- **The shell** (`desktop/main.js`): one copy at a time. It picks a loopback port (last launch's when it's free, so the page keeps its address), starts the page's standalone server in a utility process with Electron's own Node, and opens a window once it answers. Links to other sites open in the browser, and `mailto:`, `whatsapp:` and `slack:` links in their apps; downloads go to Downloads. On a Mac there's no Dock icon until the window shows.
- **The menu:** Open Proxenos, Sync now (`python -m proxenos sync`, its output in the vault's `logs/sync.log`), Last synced (from `<vault>/state/schedule.json`), Pause or Resume syncing, and Quit.
- **The schedule:** `python -m proxenos schedule` runs while the app is open, once a vault is set up; it starts again on the new vault when setup moves it. When another `proxenos schedule` already keeps the vault (one from source), the menu says so and it tries again every five minutes. Quit stops it cleanly (SIGTERM, then SIGKILL after 30 seconds; on Windows it ends at once, which is safe).
- **Its own files:** Chromium's storage, the page's and the scheduler's logs, and the port, in `desktop/` inside the settings folder (`~/Library/Application Support/Proxenos` on a Mac), private like the rest. Nothing is sent anywhere: no telemetry, and no updates yet.
- **How the page finds things in it:** `PROXENOS_HOME` is the folder holding the page as `web/` (the app's resources; from source, the repo), `PROXENOS_PYTHON` the Python to run `-m proxenos` with (else `PROXENOS_BIN` or `proxenos` on the PATH, as before), and `PROXENOS_PORT` the page's port, which `proxenos phone` and `proxenos web` follow too. `PROXENOS_STANDALONE=1` makes `npm run build` write the standalone server.
- **Building it:** `desktop/build.sh`, on the computer it's for, with git, curl, Node 22.12 or newer and npm. It downloads a pinned python-build-standalone CPython 3.12 from its GitHub releases and checks its SHA-256, installs a wheel of this checkout into it, builds the page from the checkout's tracked files, and runs electron-builder: a `.dmg` and a `.zip` on a Mac, a per-user installer on Windows, in `desktop/dist`. `desktop/smoke.sh` then tries the built app's Python and page on a demo vault. The [desktop workflow](../.github/workflows/desktop.yml) does both on GitHub's Mac and Windows machines, by hand or for a `v*` tag, and keeps the installers as the run's artifacts.
- **Not yet:** signing and notarizing with an Apple Developer ID, signing on Windows with Artifact Signing, and updates (a TODO for electron-updater from GitHub releases), which wait on the owner's accounts ([apps.md](apps.md#what-only-the-owner-can-do)); `desktop/electron-builder.config.js` says which variables turn signing on. Until then a downloaded copy opens only once it's allowed in System Settings, Privacy & Security (Open Anyway), and Windows SmartScreen warns about the installer. Also not yet: opening at login, and the menu bar's folder picker.

### The Connect page

- `proxenos connect` prints every source as JSON: whether it's connected, when it was last read, and what's missing. It reports names, addresses and handles, never a token, password or key.
- `GET /api/connect` runs it. `POST /api/connect/gmail`, `/microsoft` and `/gcalendar` start `proxenos auth gmail|microsoft|gcalendar NAME ADDRESS` and `POST /api/connect/whatsapp` starts `proxenos ingest whatsapp`, each in the background and one at a time; the page follows them through `GET /api/connect/jobs`, and `POST /api/connect/cancel` stops one. A job reports only the command's last line, with anything that looks like a token blanked.
- Every route answers only the page itself: a loopback host and the same origin.

### Setup and Settings

- **Where things are read from**, first to last: the process's environment; the repo's `.env`, only when running from source (a checkout has `pyproject.toml`); `~/Library/Application Support/Proxenos/settings.json`; the macOS Keychain. `config.load` puts what the last three hold into the environment once per process, never over a variable that's already set, so every reader sees the same order and code that reads `os.environ` directly keeps working.
- **The settings file** holds `PROXENOS_<NAME>` settings by their lower-case name (`{"name": ..., "vault": ..., "model": ..., "docs_dirs": ...}`) and, under `"keychain"`, the names (never the values) of the secrets kept in the Keychain. It and its folder are private to you (0600, 0700).
- **The Keychain** (`keychain.py`) keeps one generic password per secret: service `Proxenos`, account the variable's name. Everything goes through the `security` command. A value never goes on a command line: it's written through `security -i`, which reads its commands from stdin, as hex, and read back to check it was saved.
- **Saving:** `config.save_secret(name, value)` writes to `.env` when running from source with one, else to the Keychain, and only accepts Proxenos's secrets (`ANTHROPIC_API_KEY`, `GMAIL_*`, `GCALENDAR_*`, `MICROSOFT_*`, `SLACK_USER_TOKEN*`, `STRAVA_*`, `GOOGLE_CLIENT_*`, `BEEPER_ACCESS_TOKEN`). `config.save_setting` does the same for settings, with the settings file in place of the Keychain. Every `proxenos auth` sign-in and `proxenos phone` use them.
- **`proxenos setup`** prints where things stand as JSON: the settings and where each comes from, the vault (whether it exists, whether a cloud syncs it), the model, Ollama's pulled models, and whether each secret is set and where. `proxenos setup --apply` makes one change read as JSON from stdin: settings (the vault folder is made, private, and refused inside the repo), an Anthropic key (checked by asking for the model it will use, which costs no tokens), a local model (checked against Ollama), or a secret replaced or removed.
- **The page:** `/app` sends a first run (no name and no vault set anywhere) to `/setup`, which goes through the four steps above. The Settings view (the "You" group) changes the name, the vault, the model, the folders read on every sync, and each secret, which it shows only as set or not and where it's kept, with Replace and Remove. `GET` and `POST /api/setup` run `proxenos setup`; a key or token goes to it on stdin and nowhere else, and no answer holds one. The route answers only the page itself, as the others do: a loopback host, the same origin, and a JSON body.

### The privacy screen

- **`proxenos privacy`** (`privacy.py`) prints the screen as JSON, in three parts. It holds paths, names, addresses, counts and dates, never a message, a prompt, a token or a key: each call's line is copied field by field, a source by its names and addresses, a secret by its name.
  - **Stays here:** the vault's path and size, by folder (raw, memory, clones, self, observations, state, and the rest); whether a cloud syncs it (setup's check); whether FileVault is on (`fdesetup status`, on a Mac only); and the secrets that are set, by name, with where each is kept.
  - **Sent to a model:** the model and where it runs, and the last 30 days of the calls log (`llm.calls`), totalled by where each call ran and by the part that asked (calls, failures, characters and tokens in and out), with the newest 50 one by one. Beside them, what each part sends, in plain words: the README's Privacy list as data, with the parts of the log each covers, the one place the page reads it from.
  - **Fetched from elsewhere:** the connected sources from `proxenos connect`, by name and address, and whether links in chats are read (whenever a model is set up, as replies are then drafted; public hosts only).
- **The page:** the Privacy view (the "You" group) shows the three, a table of the month's calls by part and the newest calls. When every call ran here it says so: "Nothing went to a hosted model in the last 30 days." `GET /api/privacy` runs the command and reads its answer field by field; it answers only the page itself, as the other routes do.
- **Not built:** Delete everything and `proxenos forget`.
