# Apps for Mac, Windows and Android

The goal: anyone can install Proxenos the way they install any app, on a Mac, a Windows PC or an Android phone, and use it without code. This plan extends [everyone.md](everyone.md), which covers the Mac app's design: an Electron shell around the page and a bundled Python. Little here is built yet: so far, the scheduler that will replace launchd ([below](#keeping-it-running-from-source)).

## Where things stand

Proxenos runs today on one kind of machine: a Mac, set up from the code. Most of it already runs anywhere Python and Node run. What ties it to macOS is a short list:

| Mac-only today | What it does | The way across |
|---|---|---|
| `ingest/applemail.py` | reads every account in the Mac's Mail app | sign in to Gmail and Microsoft 365 directly (Gmail API, Microsoft Graph) |
| `ingest/maccalendar.py` | reads the Mac's Calendar app | the same sign-ins, for calendars |
| `ingest/whatsapp.py` | reads the WhatsApp Mac app's local store | Beeper Desktop, already supported, which runs on Mac, Windows and Linux |
| `keychain.py` | keeps secrets in the macOS Keychain | one secrets module over the Keychain and Windows Credential Manager (the `keyring` library does both) |
| `outbox.py` (mail) | sends through the Mail app | send through the same Gmail or Microsoft sign-in |
| `phone.py` | serves the page to your phone over Tailscale | unchanged on Windows; on Android, see below |
| `scripts/install-*.sh` | launchd jobs for the page, the 15-minute sync and the nightly run | the app runs the page itself, and `proxenos schedule` (built) the sync and the night, on every platform |

## The plan, in order

### 1. One core that runs anywhere (a few weeks)

Before any app ships, make the core platform-neutral, so the Mac and Windows apps are the same app:
- A secrets module over the Keychain and Windows Credential Manager.
- Mail and calendar through Google and Microsoft sign-in, beside Apple Mail.
- Paths from the platform's app-data folder, not `~/proxenos_vault` assumptions.
- The nightly run and the 15-minute sync run by the app instead of launchd. *Built:* `proxenos schedule`, below.
- Tests on GitHub's Windows machines as well as macOS.

### 2. The Mac app (a few weeks after 1)

As [everyone.md](everyone.md) describes: Electron, the page as a standalone Next.js build, Python from python-build-standalone with the `proxenos` wheel, a menu-bar icon, and the setup page that's already built.
- **Signed and notarized** so macOS opens it without warnings. This needs an Apple Developer Program membership.
- **Released on GitHub** as `Proxenos.dmg`. The website's download button points at the latest release, which anyone can download with no GitHub account.
- **Updates** from signed GitHub releases.

### 3. The Windows app (weeks, once 1 and 2 exist)

The same Electron app, built for Windows on GitHub's Windows machines.
- **Signed** with Microsoft's Artifact Signing, so Windows' SmartScreen doesn't block it. Individuals in the US and Canada can use it.
- **Messages** through Beeper Desktop. WhatsApp's Windows app doesn't leave a readable store the way the Mac app does.
- **A local model** through Ollama, which runs on Windows; or Claude with the person's own key.

### 4. Android, as a companion to your computer (short)

The phone shows your own computer's Proxenos over a private link, like `proxenos phone` does today.
- Nothing new runs on the phone and nothing leaves your devices.
- First as the page saved to the home screen (it already works); later as a small Play Store app that pairs with the computer by scanning a code, instead of a Tailscale setup.
- **Limit:** it needs a computer that's on. Many people, and many patients, only have a phone.

### 5. Android on its own (the largest piece)

A phone-only Proxenos, care first, for people without a computer.
- **What it can read:**
  - Gmail and Google Calendar, through sign-in;
  - the phone's calendar and contacts, with permission;
  - documents people pick: bills, visit summaries, insurance letters;
  - voice notes;
  - and, with the special notification access Android asks for separately, new messages as they arrive. It can't read message history.
- **The model:** a small one on the phone (Gemma 4 E2B through LiteRT-LM is about 2.6 GB, so newer phones only), or Claude with the person's own key.
- **What it does first:** the care log, open items and bills, call scripts, the visit brief, and drafts. That's the core of what helped most.
- **The cost:** most of Proxenos is Python, and Android apps aren't. This means rewriting the care, errands and drafting logic for the phone (Kotlin), or running Python inside an Android app (possible, but heavy).

## Keeping it running from source

`proxenos schedule` keeps a vault current on any computer: `proxenos sync` every 15 minutes and `proxenos night` at 01:30, local time. The coming Mac and Windows apps will start it themselves when they open at log-on, so nobody sets anything up; until then, people running from source keep it going as below. On a Mac, `scripts/install-app.sh` and `scripts/install-night.sh` stay as they are and do the same with launchd: use either.

How it behaves:
- **Each run is a process of its own** (`python -m proxenos sync`), so a crash in one never stops the schedule. Its output is appended to `<vault>/logs/sync.log` or `night.log`, as the launchd jobs' is, followed by one line from the scheduler: how it ended, when, and how long it took.
- **Catching up:** after the computer sleeps through a slot, or is off, the job runs once when it's back, not once per slot it missed. When both are due, the night goes first, since it begins with a sync.
- **Never two at once:** `sync`, `night` and `master` hold a lock in `<vault>/state/` while they run, whoever started them, so a scheduled run waits for one started by launchd or by hand, and a run of the very job that's due counts as its run. The lock is the operating system's own (`flock`, or `msvcrt.locking` on Windows), so a crash never leaves one behind. A run started by hand while another goes on says which and exits with status 75. A second `proxenos schedule` for the same vault doesn't start.
- **Holding off:** nothing starts while the page is answering a question.
- **Stopping:** Ctrl-C, SIGTERM or Ctrl-Break stops it: a running job is interrupted the way Ctrl-C would, given 20 seconds to finish what it's writing, then ended; a second Ctrl-C ends it at once. A stopped run counts as not having run, so it runs at the next start. Every step of a sync or a night is safe to run twice.
- **Where it stands:** `<vault>/state/schedule.json` has the last run of each (when, and `ok`, `failed (exit 1)`, `stopped` or `started elsewhere`), the next, what's running, and why a job that's due is waiting. The times live there too, so a restart picks up where the last one stopped.
- **Times:** `--sync-every MINUTES` (0 for none) and `--night-at HH:MM` (or `off`), else `PROXENOS_SYNC_EVERY` and `PROXENOS_NIGHT_AT` from `.env` or the settings file. `--once` runs what's due and exits, for trying it or for a scheduler that starts it every few minutes.

**Windows,** with Task Scheduler at log-on. In PowerShell, with the proxenos environment active (`pythonw` runs it without a console window):

```powershell
$action = New-ScheduledTaskAction -Execute (Get-Command pythonw).Source -Argument "-m proxenos schedule"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -MultipleInstances IgnoreNew `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName Proxenos -Action $action -Trigger $trigger -Settings $settings
Start-ScheduledTask -TaskName Proxenos    # now, without logging out
```

`Stop-ScheduledTask -TaskName Proxenos` stops it and `Unregister-ScheduledTask -TaskName Proxenos` removes it. Stopping it this way ends it at once, with no time to tidy up: that's safe, as the lock goes with it and a stopped run runs again. To watch it instead, run `python -m proxenos schedule` in a terminal and press Ctrl-C to stop.

**Linux,** with a systemd user unit, `~/.config/systemd/user/proxenos.service`. `ExecStart` is the proxenos environment's Python (`python -c "import sys; print(sys.executable)"` in it):

```ini
[Unit]
Description=Proxenos: a sync every 15 minutes and the nightly run

[Service]
ExecStart=/home/you/miniforge3/envs/proxenos/bin/python -m proxenos schedule
# SIGTERM to the scheduler alone, which stops a running job cleanly itself.
KillMode=mixed
TimeoutStopSec=60
Restart=on-failure
# Another scheduler already keeps the vault: starting again won't change that.
RestartPreventExitStatus=75

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload && systemctl --user enable --now proxenos
journalctl --user -u proxenos -f    # the scheduler's own lines; each run's output is in <vault>/logs/
loginctl enable-linger "$USER"      # optional: keep it running while you're logged out
```

## What only the owner can do

Each of these needs your identity, your payment, or both. Nothing here can be done on your behalf.

| For | What | Cost |
|---|---|---|
| Mac app | Apple Developer Program membership, for signing and notarizing | $99 a year |
| Windows app | Microsoft Azure account and Artifact Signing, with identity checks | $9.99 a month (Basic) |
| Android app | Android Developer Console account, with government ID; Google now requires verified developers even for apps installed outside Play (four countries since Sept 30, 2026, worldwide from 2027) | $25 once |
| Gmail for everyone | Google's app verification. Reading mail is a restricted scope, which needs a yearly security assessment (CASA); sending only needs verification | about $540 to a few thousand dollars a year; 2 to 8 weeks |

Until Google's verification is done, Gmail keeps today's paths: your own sign-in client, an app password, or Microsoft 365 and Outlook.

## Decisions

1. **Android first:** decided on October 29, 2026: the companion first (fast, private, needs a computer), then the phone-only app.
2. **First release:** the Mac app alone, or Mac and Windows together, at the cost of waiting for both.
3. **Gmail verification:** pay for it now, or start with Microsoft 365, IMAP and your own sign-in client.

## Sources

- Apple Developer Program fee and notarization: [Apple Developer Forums](https://developer.apple.com/forums/thread/121113); check [developer.apple.com](https://developer.apple.com/programs/) for the current price.
- Windows signing: [Microsoft, Artifact Signing pricing](https://azure.microsoft.com/pricing/details/trusted-signing/); [DevClass on eligibility (Jan 2026)](https://www.devclass.com/security/2026/01/14/code-signing-windows-apps-may-be-easier-and-more-secure-with-new-azure-artifact-service/4079554)
- Android developer verification: [Google, Understanding Android developer verification](https://support.google.com/android-developer-console/answer/16561738); [Android Authority, the first wave](https://androidauthority.com/android-sideloading-developer-verification-first-wave-rollout-3717921)
- Gmail verification and CASA: [Unipile, Google OAuth verification (2026)](https://www.unipile.com/integrating-google-oauth-2-0-user-authentication-into-your-app/); [DeepStrike, the CASA assessment](https://deepstrike.io/blog/google-casa-security-assessment-2025)
- On-device models: [Google, LiteRT-LM](https://developers.googleblog.com/en/blazing-fast-on-device-genai-with-litert-lm/); [Gemma on LiteRT, model card](https://huggingface.co/litert-community/Gemma3-1B-IT/blob/main/README.md)
- Notification access on Android: [Android reference, NotificationListenerService](https://developer.android.google.cn/reference/kotlin/android/service/notification/NotificationListenerService?hl=de)
