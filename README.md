# Proxenos

[![checks](https://github.com/mindemory/proxenos/actions/workflows/checks.yml/badge.svg?branch=main)](https://github.com/mindemory/proxenos/actions/workflows/checks.yml)
![macOS](https://img.shields.io/badge/platform-macOS-lightgrey)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
[![MIT license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Local-first](https://img.shields.io/badge/local--first-your%20data%20stays%20on%20your%20computer-6e56cf)
[![GitHub stars](https://img.shields.io/github/stars/mindemory/proxenos?style=social)](https://github.com/mindemory/proxenos/stargazers)
[![XERJ Corpus Hub contributor](https://hub.xerj.org/contributors/mindemory/badge.svg)](https://hub.xerj.org/contributors/mindemory)

**A free, open-source personal memory toolbox, for anyone: it keeps your own records private on your computer and drafts the next step for you. Built first for people getting through the health care system.**

Your life is spread across mail, chats, calendars, notes and documents, and keeping up with it is work of its own. Proxenos reads what you already have, keeps track of where things stand, and writes the reply, the plan, the call script or the brief, in your own voice. You stay in charge: it drafts, and you press send. It started with health care, where the hard part is often everything around the care: referrals that go quiet, portals, bills that don't match, forms, and the same story told again at every visit. The same memory serves your replies, tasks, projects and papers, a diary of your life, and whatever else you keep up with.

![Home for Joe Bloggs, a made-up person: the sidebar with every view by group (Today, Ask and think, Work, Your life), a morning greeting, and today's agenda beside the drafts to send](docs/images/home-desktop.png)
*The home page of `proxenos demo`, a made-up person with made-up records. More [below](#what-it-looks-like).*

It grew out of one person's weeks of getting through the system while unwell. The story is [Try anything, but don't fall sick](https://mrugankdake.substack.com/p/try-anything-but-dont-fall-sick), and more on the project is at [mindemory.io/proxenos](https://www.mindemory.io/proxenos).

> **Status: working, and used every day by its author.** It runs on a Mac (Apple Silicon), and every check passes on macOS and Windows on every push: about 83,000 lines of Python, TypeScript, Swift and JavaScript, with 30,000 more in 1,113 tests. Today you run it from source, or build the desktop app for Mac and Windows, which bundles its own Python but is unsigned for now. A one-click download waits on three things ([docs/everyone.md](docs/everyone.md)): signing the app, so your computer trusts it on first open; Proxenos's own sign-in apps for Google, Microsoft, Slack, Strava and Spotify, so nobody has to make a developer account; and a small local model that comes with it. Expect rough edges, and readers that assume a particular export format.
>
> **Help of any kind is welcome:** code, an issue, or an idea over a message or a call. Health care is where it started, so people with medical training are especially welcome. Knowing what's worth tracking and what to ask is what would make this preventive, not just a way through the system. Good places to start are in [CONTRIBUTING.md](CONTRIBUTING.md#good-first-contributions). If you'd like Proxenos to exist for more people, a star helps others find it.

> **Not medical advice.** Proxenos organizes your own records and drafts messages. It doesn't diagnose or recommend treatment: the care view restates what your records say, and anything that matters belongs with your care team.

Proxenos gathers your own data (messages, email, calendar, notes, documents, activity) into one private vault on your computer. From that it keeps a written model of who you are, and runs small agents ("clones") that work for you:
- a feed of new papers and news, ranked for you;
- your open tasks, pulled from your conversations and from what you tell it, kept up through the day, with the plans among them (a lunch at 12, a call at 9) put on your own calendar, and taken off it when they're called off;
- a journal of each day, so you never have to narrate it: what got done, where you wrote, what moved in your projects, what's waiting on others and what's next, with a few sentences on how it went;
- a diary of your life by month and day, years back: for each month, a short abstract, an essay of the month in your own voice and an entry for each day that mattered (care and medical visits, big conversations, decisions, trips, how you were doing), only as your records and words show it, with what you told Proxenos that month as its milestones, and yours to edit or mark not true; and for each day, whom you wrote to, your calendar, what you wrote down, your health records by title, and your walks, listening and photos, from everything already in the vault;
- your weeks over time, side by side, across listening, movement and messages: how much you listened and in what genre and mood, how far you rode, ran and walked, and how many messages you sent and got on each channel, a week, two weeks or a month at a time, with what stands out in plain words;
- where your health care stands, in plain words: a timeline, what's still open, what to say on the phone, and a one-page brief for your next appointment;
- the forms you're handed (a PDF application, an intake form) filled from your records, leaving the ID numbers, account numbers and signature to you;
- advice grounded in your own patterns;
- once a week, what's worth taking on (a call for papers, a fellowship, a talk, a piece of writing, with a first step drafted) and what's worth letting go of (a meeting, a thread, an invitation, with the decline drafted), by your own goals;
- where each of your long-running projects stands, from your messages and its code on every branch, and, given its code, the next step of its work done on a branch of its own for you to accept;
- a map of the people you know and how they connect;
- a searchable memory that brings the right past messages and notes to mind, by their words and by their meaning;
- a place to think anything through with Proxenos, grounded in your own goals and records: a decision, a message to send for yourself or someone else, a project, a day, or a thought, over as many turns as it takes, each answer with what your goals, notes and records say bears on it, questions to sit with and optional next steps, never deciding for you;
- drafts of replies, emails and plans, written in your voice: a reply for each chat waiting on you, in the way you write to that person, after reading any link they sent.

It drafts; by default it never sends, posts or buys anything by itself. You copy a draft or open it in its app with the text filled in, and press send yourself; once your reply shows up in that chat, the draft is marked sent. Chats that need no answer (thanks, a receipt, an auto-reply) get no draft. A draft you changed before sending, or rewrote on the page with "Write my own", is shown, beside what you sent, to the drafts written for you after it. Each night, once five or more of those are new, short rules about how you write are learned from them, each kept only where your own sent messages bear it out, and proposed in `self/proposals/voice_rules.md`; once you accept them (`proxenos master accept`), every draft follows `self/voice_rules.md`, which you can edit. A draft your messages since made moot (someone else did it, or the plan changed) is folded away with why. What you tell it on the home page shapes every draft: a fact your messages don't show ("I'm not going on Tuesday"), kept for two weeks, or a rule kept until you remove it ("keep replies to my manager short"). Drafts never leave a blank for you to fill in. An outbox you switch on per app lets replies go out on their own, only where that app's drafts have gone out nearly unchanged many times, with a window to cancel each one, never to someone new, and never with a link, an address or a number the chat didn't already have ([docs/memory.md](docs/memory.md)). It places a phone call only when you press Call: it waits on hold, says it's an automated assistant calling for you, and rings you when a person answers ([docs/calls.md](docs/calls.md)). The longer-term plan, moving from drafting to acting on approval to acting within rules you set, is in [docs/roadmap.md](docs/roadmap.md).

A Privacy view on the page shows what stays on your computer, every call to a model in the last 30 days and where it ran (on your computer or at Anthropic), what's read from elsewhere, and whether notices go to your phone. Other people's words go into prompts marked as data, never as instructions.

The page is made to be easy to read when reading is hard. Aa at the top of every view (and Settings, Reading) sets larger text, a typeface made for low vision (Atkinson Hyperlegible Next), more space between lines and words, a light theme, more contrast and less motion, kept on each device. Listen reads Home's day, Care's summary and items, and each draft aloud, with a natural voice or your own, made on your Mac (Kokoro and Qwen3-TTS, with the optional `speech` extra on Apple silicon), or with your computer's own voice, and care's summaries come in plain words, with each medical term explained ([docs/everyone.md](docs/everyone.md#easier-to-read-and-to-hear)).

*The name: in the Greek city-states, a proxenos was the citizen who formally acted on someone else's behalf.*

## What it looks like

These come from `proxenos demo` (see [Quick start](#quick-start)), like the home page at the top: a made-up person, Joe Bloggs, and his made-up records. None of it is real.

| Care: where things stand, what's yours to do, what to say | Errands: carried as far as they go, one tap short of sending |
|---|---|
| ![Care for a made-up person: where his eye exam, new glasses and their bill stand, and the next step, with a due date and a script for the call](docs/images/care-desktop.png) | ![Errands for a made-up person: a message to a recruiter with the CV attached, ready to send, with how the address was found](docs/images/errands-desktop.png) |
| **Drafts: replies and documents in your voice, ready to send** | **Tasks: what was asked of you, pulled from your conversations** |
| ![Drafts for a made-up person: a WhatsApp reply and an email reply to send, with each app's track record and the outbox, off](docs/images/drafts-desktop.png) | ![Tasks for a made-up person: tasks from email and WhatsApp, with who asked, when, and when each is due](docs/images/tasks-desktop.png) |
| **Projects & papers: each one where it stands, and its next step on a branch** | **Jobs: every lead, whether to apply, with which CV and through whom** |
| ![Projects & papers for a made-up person: three cards, a paper with a step waiting on him, an analysis in code and a project of notes](docs/images/projects-desktop.png) | ![Jobs for a made-up person: two leads to apply for, one from a recruiter with a draft and an errand to start, one he looks to have applied to already](docs/images/jobs-desktop.png) |
| **Life: a diary of each month, in your own voice** | **Rhythms: your weeks side by side, and a card for each month** |
| ![Life for a made-up person: October's abstract and essay, a paragraph for each thing the month was about, each one his to edit or mark not true](docs/images/life-desktop.png) | ![Rhythms for a made-up person: a month's card, how it felt in his own writing, the genres and moods of what he listened to, and how much he wrote on each channel](docs/images/rhythms-desktop.png) |

**Journal: the day, written down, from what Proxenos already tracks**

![Journal for a made-up person: a brief on yesterday, the next three things to do, and the replies sent, what's waiting on others and what's next](docs/images/journal-desktop.png)

On a phone, over `proxenos phone`:

<p>
  <img src="docs/images/home-phone.png" width="19%" alt="Home on a phone, for a made-up person">
  <img src="docs/images/care-phone.png" width="19%" alt="Care on a phone: where a made-up person's new glasses and their bill stand">
  <img src="docs/images/errands-phone.png" width="19%" alt="Errands on a phone: a made-up person's message to a recruiter, ready to send">
  <img src="docs/images/drafts-phone.png" width="19%" alt="Drafts on a phone: a made-up person's replies to send">
  <img src="docs/images/tasks-phone.png" width="19%" alt="Tasks on a phone: what was asked of a made-up person, and when it's due">
</p>
<p>
  <img src="docs/images/journal-phone.png" width="19%" alt="Journal on a phone: a made-up person's day, written down">
  <img src="docs/images/projects-phone.png" width="19%" alt="Projects and papers on a phone: a made-up person's three projects as cards">
  <img src="docs/images/life-phone.png" width="19%" alt="Life on a phone: a month's essay in a made-up person's voice">
  <img src="docs/images/rhythms-phone.png" width="19%" alt="Rhythms on a phone: a made-up person's month card, its mood and music">
  <img src="docs/images/jobs-phone.png" width="19%" alt="Jobs on a phone: a made-up person's job leads">
</p>

## How Proxenos compares

Many tools keep a memory for you or act for you. They differ in where your data lives, what they read, whether they act or draft, whether they keep a model of you, and whether anything checks how close they come to you. This was checked against each project's own README, licence file, site or help pages on November 3, 2026; [docs/landscape.md](docs/landscape.md#what-people-have-built) has more of them, with links.

| Kind | Tool | Your data lives | It reads | Acts or drafts | Models you | Measures how close it comes to you | Licence |
|---|---|---|---|---|---|---|---|
| Personal memory toolbox | **Proxenos** | Your computer, in plain files | Your mail, chats, calendars, notes, documents, health records, activity and exports: about 30 sources | Drafts, and you press send (apart from an outbox you switch on per app, and calls you start) | A written self-model you read and correct | Yes: how much of each draft you sent, and blind picks between models on replies held out | MIT |
| Self-hosted AI workspace | [Odysseus](https://github.com/odysseus-dev/odysseus) | Your machine | Files you add, the web, an IMAP inbox, CalDAV calendars, notes | Acts: agents with a shell and MCP, scheduled tasks; drafts email replies | A memory built from your chats | No | AGPL-3.0 |
| Self-hosted AI workspace | [Open WebUI](https://github.com/open-webui/open-webui), [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm), [LibreChat](https://github.com/danny-avila/LibreChat) | Your server or desktop | Documents you upload, the web | Acts through tools, agents and MCP | Facts about you, where memory is on | No | Open WebUI License (BSD-3 with a branding clause); MIT; MIT |
| Self-hosted AI workspace | [Khoj](https://github.com/khoj-ai/khoj) | Your server, or Khoj's cloud | Your notes and documents (Markdown, org-mode, PDF, Notion), the web | Answers, and runs research on a schedule and emails it to you | Long-term memories | No | AGPL-3.0 |
| Notes with AI | Obsidian with [Smart Connections](https://github.com/brianpetro/obsidian-smart-connections) or [Copilot](https://github.com/logancyang/obsidian-copilot) | Your notes folder (Copilot's paid tier uses its own hosted models) | Your notes | Smart Connections finds related notes; Copilot's agents edit them | No | No | Smart Plugins License (source-available); AGPL-3.0 |
| Notes with AI | [Mem](https://get.mem.ai/), [Notion AI](https://www.notion.com/product/ai) | The vendor's cloud | Your notes or workspace, and mail, calendar, Slack or Drive once connected | Acts: agents that write, plan and run on a schedule | Memories of you that you can edit | No | Proprietary |
| Lifelogging and recall | [Screenpipe](https://github.com/mediar-ai/screenpipe) | Your computer | Your screen, your microphone and computer's audio, and what you type and click | Acts: scheduled "pipes" | No | No | Screenpipe Commercial License, free for personal use (MIT until June 2026) |
| Lifelogging and recall | [Microsoft Recall](https://support.microsoft.com/en-us/windows/retrace-your-steps-with-recall-aa03f8a0-a78b-4b3e-b0a1-2eb8ac48701c) | Your PC, encrypted | Snapshots of your screen every few seconds | No: search and a timeline | No | No | Proprietary, in Windows 11 on Copilot+ PCs |
| Meeting memory | [Granola](https://www.granola.ai/) | Granola's cloud | Your meetings' audio, and your calendar | Notes, and drafts of follow-up emails | No | No | Proprietary |
| Agent memory framework | [Letta](https://github.com/letta-ai/letta-code), [Mem0](https://github.com/mem0ai/mem0), [Zep and Graphiti](https://github.com/getzep/graphiti), [LangMem](https://github.com/langchain-ai/langmem), [Cognee](https://github.com/topoteretes/cognee) | Wherever a developer runs it, or the vendor's cloud | The chat turns and documents an app passes it | No: memory for other agents (Letta runs agents too) | Facts about a user: memory blocks, extracted facts, a graph of facts over time | Recall of facts on benchmarks (LoCoMo, LongMemEval), not likeness to a person | Apache-2.0; LangMem MIT |
| Always-on personal agent | [OpenClaw](https://github.com/openclaw/openclaw) | Your computer | Your chats on WhatsApp, Telegram, Slack, iMessage and more, and the tools you add | Acts: jobs on a schedule (every 30 minutes by default) that check in and use tools | `MEMORY.md` and `USER.md`, in plain Markdown | No | MIT |
| Hosted assistant | [ChatGPT](https://openai.com/index/memory-and-new-controls-for-chatgpt/), [Claude](https://support.claude.com/en/articles/11817273), [Gemini](https://blog.google/innovation-and-ai/products/gemini-app/personal-intelligence/), [Manus](https://manus.im/) | The vendor's cloud | Your chats, and Gmail, Calendar or Drive once connected | Acts: scheduled tasks and agents, mostly asking before sending or buying | Saved memories you can see and edit | No | Proprietary |
| Personal digital twin | [Second Me](https://github.com/mindverse/Second-Me) | Your computer | Notes and files you give it | Answers as you, and talks with other people's Second Me | A model trained on you, with a biography | Partly: a model judged its answers on one person's notes | Apache-2.0 |
| Personal digital twin | [Delphi](https://www.delphi.co/), [Personal.ai](https://www.personal.ai/) | The vendor's cloud | What you upload or post (writing, video, podcasts), and Gmail or Drive on Personal.ai | Answers others as you; Personal.ai can reply for you, on its own or once you approve | A persona from your content | Personal.ai scores replies against the persona; its method isn't published | Proprietary |
| Personal data store | [HPI](https://github.com/karlicoss/HPI), [promnesia](https://github.com/karlicoss/promnesia), [Solid](https://solidproject.org/), [Perkeep](https://perkeep.org/) | Your computer, your server, or a Solid pod you choose | Exports from many services; promnesia, your browser history | No: they keep your data and help you search it | No | No | MIT; MIT; MIT (Community Solid Server); Apache-2.0 |

What Proxenos does that these don't, all at once: it reads the whole of your own records on your computer, mail, chats, calendars and health records included; keeps a model of you in text you can read and correct; drafts the next step in your voice for you to send; and measures how close those drafts come to what you actually sent. Of the tools above, only Second Me and Personal.ai try to measure likeness to you, one with a model as the judge on one person's notes and one with a score whose method isn't published. Stanford's agents built from two-hour interviews ([Park et al.](https://arxiv.org/abs/2411.10109)), a research study, measure it against people's own answers. Proxenos also lists, for each part of it, what reaches a model, and logs every model call where you can see it.

What others do better: Odysseus, Open WebUI and LibreChat are fuller workspaces, for more people and more models. OpenClaw reaches you on every chat app and acts on its own, and the hosted assistants know you with no setup and keep running while your computer is off. Screenpipe and Recall capture everything on your screen with no reader per source, and Granola captures meetings far better. The memory frameworks are built for developers at scale, with published benchmarks, and Zep's graph knows when each fact was true. Second Me trains a model of you on your own machine. HPI and Perkeep reach services Proxenos doesn't, and Solid gives apps a standard way to share your data with your permission. Proxenos is young: its measures come from one person so far, it runs best on a Mac (the desktop app for Mac and Windows isn't signed yet), and its readers assume particular export formats.

## How it works

```
your sources ──ingest──▶ vault/raw ──observe──▶ notes ──consolidate──▶ self-model
                              │                                             │
                              └──index──▶ memory (full-text search)         ▼
                                                        clones: feed, tasks, advice,
                                                        choices, jobs, watch,
                                                        network, recall, projects, project
                                                        steps, errands, drafts,
                                                        journal, life, rhythms
                                                                │
                                                        local page (127.0.0.1)
```

- **Ingesters** pull each source into the vault as monthly files. Re-running one is always safe.
- **Observers** read one month of one source (only your own side of conversations) and write notes about you.
- **The master** merges the notes into a single self-model: identity, interests, taste, voice, routines and open questions. Slow-changing parts change only through proposals you accept.
- **Clones** read the self-model and each do one job. The page shows their output and records your reactions, which feed back into the next run.

More detail: [architecture](docs/architecture.md), [memory](docs/memory.md), [data sources](docs/data_sources.md), [the feed and the page](docs/tracker.md), [a voice model trained on your own writing](docs/voice-model.md), [related work](docs/landscape.md).

## Privacy

- **Code and data are separate.** This repository holds code only. Everything personal lives in a private vault outside the repo (picked on the first-run setup page, or `PROXENOS_VAULT`; default `~/proxenos_vault`). The vault keeps its own local git history of how the self-model changes.
- **What reaches the model:** observers send the model only your side of conversations, never other people's messages. Clones send your self-model, plus public items such as papers and news. The rest send only the records their job needs, picked out in code:
  - **tasks:** conversations you're part of, with the title and opening of each draft waiting on you, and what you've told Proxenos on the home page;
  - **care:** only records about getting health care, with people in chats replaced by labels and phone, account and member numbers blanked;
  - **drafts:** the recent conversation in each direct chat, or Slack thread that mentions you or that you're in, waiting on your reply, with what your memory holds about that person and what the chat depends on (the newest records naming them, the results of the searches the model asks for, and, for up to three records a round it asks to open, the records around them in their conversation), what you've told Proxenos (your rules, and recent notes) and your calendar for the coming week (each event's time and title);
  - **compare** (`proxenos compare`, or Settings' "Which writes like you?"): only to the two models you compare, for each of your recent replies, what its draft would have been sent just before you replied: the conversation before it, your own writing from before then, your rules, notes and calendar as they stood then, with the same blanking; never the reply itself or anything after it, and not what memory finds;
  - **writing rules:** the drafts you changed before sending, each beside what you sent instead, with where it went and whom to, and some of your own sent messages to check each rule on; never other people's messages;
  - **choices:** the mail and Slack posts that announce an opening (a call, a fellowship, a talk), with who sent each, the openings you kept from Ask (what it read in the post you shared: the role, who offers it, where, the pay, the deadline and the link, with its verdict and why), and what your time goes to: meetings, unanswered invitations, and the last message of each chat that has waited on you for over a week;
  - **jobs:** the job leads that reached you: LinkedIn's job alerts and message notices, Work at a Startup's notices of founders' messages, recruiters' emails and LinkedIn chats about a role, job boards' mail and receipts of applications, list and Slack posts announcing positions, each with who sent it and its links, and the job posts you shared to Ask as Ask read them; then, to judge each job, your self-model, the text of your newest CV and résumé, and the names of the people you know at that company with how you know them; and, for a first step, the job, the newest message about it, the CV chosen, your earlier records with the person it goes to, and your own writing to draft like. Your sent mail and receipts are matched to jobs in code, with no model;
  - **projects:** the records that name each project or come from its people, and its code's commit messages and changed documents; a project's steps also give its code and data to the runner that takes the step, which can't read the vault, your keys and other tools' credentials, your mail and messages or your browsers' profiles, and runs commands only inside Claude Code's sandbox ([docs/architecture.md](docs/architecture.md));
  - **errands:** the newest records naming the person to reach, your earlier emails with a CV attached, and the CV;
  - **ask:** what you type or paste, its screenshots, and the records memory finds for it;
  - **think:** what you write in a thread and its last turns, what it started from (a draft, a project's status, a day's digest, what memory holds on a person, or a note of yours), your self-model (not how you write), what you've told Proxenos, the journal's last three briefs, and the records memory finds for it;
  - **network:** the people you know by name, how you know each and what you share, and your notes' titles;
  - **watch:** the films you've logged and how you rated them;
  - **journal:** the day's lines, to write its brief: the titles of tasks closed, waiting and due, the names of the chats you wrote in and the drafts sent, what you told Proxenos that day, your projects' commit messages, the next day's calendar and care's open items;
  - **life:** for a month's diary, what you marked not true in it on the page and what's true in your words, your own abstract and essay where you edited it, what you told Proxenos that month (its milestones), care's timeline events from that month (with people only by role), the observers' notes about you from that month (not Strava's or Spotify's) and a digest of each of its days: the names of the people and chats you wrote to, with counts and the opening of your own words, and of those who wrote to you, your events, the titles of your notes and documents, your activity (what you watched, photos' albums and the people tagged, and walks, runs, rides and listening only as counts a week), your health records' titles, counts of anything else, and the journal's briefs; never other people's messages, which aren't read out of memory at all;
  - **rhythms:** the names of the artists you listen to, to label each with a genre and moods; the weeks themselves are counted with no model. For the month cards, and only to a model on this computer, never a hosted one: your own messages and what you wrote in the mail you sent (not what you quoted or forwarded), a month's days in one call, the most charged sentences of each, to name each day's feelings, and the month's numbers and artists' names, to write its card. The valence of your writing is scored on this computer with no model (VADER); with a hosted model the feelings are left out and the card is written from the numbers in code. Other people's messages are never read for it;
  - **forms** (`proxenos form`): the form's labels and the records memory finds for them, never a line for an SSN, an account number or a signature;
  - **calls:** on a phone call you start, what the other side says goes to the call's model to decide what the assistant says next, and the call's audio goes through Twilio, which transcribes it ([docs/calls.md](docs/calls.md)).

  Other people's words in a draft's, care's, an ask's, a job's or a thread's prompt (their messages, the pages they link to, the records memory finds) go inside a tag drawn fresh for that prompt, which the model is told holds data, never instructions; your own messages stay outside it. A month's days and its health records' titles, whose chat names and titles others may have written, go inside one too.

  Before any prompt goes to a hosted model, the card and Social Security numbers, one-time codes, passwords, API keys and tokens, IBANs and bank account numbers in it are blanked (`proxenos.redact`), while dates, prices, phone numbers and the like stay. With a local model none of this leaves your computer, apart from a call's audio: a model through another app's server is reached only at this computer's own address (`localhost`, `127.0.0.0/8` or `::1`), through no proxy and following no redirect, and any other address is refused. Every model call leaves one line in the vault's `state/model-calls.jsonl`: when, which part of Proxenos asked, the model, whether it ran on this computer or at Anthropic, how much went in and came back and how many numbers and secrets were blanked, never the words. The page's Privacy view adds them up for the last 30 days.
- **Notices on your phone** are off until you save an ntfy topic in Settings. Then, when a sync or the night finds more waiting on you than before, one short notice goes through [ntfy](https://ntfy.sh), an open-source push service (its server, a third party, unless you name your own), outside quiet hours (22:00 to 08:00 unless you change them). It's not sent as you: it goes to you. ntfy receives the topic, the title "Proxenos" and how many drafts to send, care items, project steps to review and tasks due soon wait on you ("2 drafts to send and 1 care item wait on you."), and, as with any request, your computer's internet address; never a name, a message's words, a subject or a health detail. On ntfy.sh anyone who knows the topic can read what's sent to it, so it's kept as a secret and should be long and random.
- **Listen** reads aloud on this computer, whichever voice it uses: the browser's own voices, only those marked as on the device, or the natural voice and your own voice made on your Mac by `proxenos speech`, whose server listens only on 127.0.0.1 and answers only the page. Nothing read aloud leaves the computer, health text included; only the models' weights come from Hugging Face, once, when you ask for them. **Your voice** is made from a clip of you reading a short passage, which you record (or pick) in Settings, Listening. It's kept in the vault at `state/speech/clip.wav`, readable only by you, with when and what it says in `clip.json`; it's never sent anywhere or shown back, and Delete in Settings removes both and stops the speech server.
- **Music genres** come from [MusicBrainz](https://musicbrainz.org)'s open data: each night the artists you play most that it hasn't been asked about yet (120 a night, one request a second) are looked up there by name, one name a request, and every 90 days its list of genres is fetched. Only the artist's name goes, never a track, a time, a count or anything about you, and like any request it carries your computer's internet address. What comes back is kept in the vault (`clones/rhythms/musicbrainz.json`), so each artist is asked once. `PROXENOS_MUSICBRAINZ=off` stops it; the Privacy view says whether it's on and how many have been looked up.
- **Google Docs** is off until you sign in for it (`proxenos auth gdocs NAME ADDRESS`, or the Connect page), with a sign-in that sees only the files Proxenos makes in your Drive (`drive.file`), never the rest of it. The manuscript's text goes to your own Google Drive only when you click Open in Google Docs (or ask for a fresh copy), as a doc no one else can open until you share it from Docs, and comes back when you click Bring back its changes. Nothing is shared or deleted for you. What your co-authors change in it reaches your manuscript only as a step on a branch of its own, once you accept it. Its comments are read when you bring its changes back or click Read comments, and kept in the vault (`clones/projects/<id>/gdocs/`) for the Manuscript view: they're other people's words, shown on the page and never sent to a model.
- **Project folders** are off until you choose a folder for them (Settings, or `PROXENOS_PROJECT_FOLDER`). Then each night each project's manuscript, where it stands (which sums up what your messages and mail say about it), its brief and its open drafts are written to that folder as Word files, made by pandoc on this computer, and nowhere else: your cloud drive uploads them as it does the rest of the folder, and who sees them is up to you. Proxenos shares nothing and sends none of it to a model. In that folder it reads only the files it wrote, to see whether you changed them, and what you changed in a Markdown manuscript reaches the manuscript only as a step on a branch of its own, once you accept it. What it wrote, and from what, is kept in the vault (`clones/folders/`).
- **Links in messages** are fetched only for a chat waiting on your reply, and only from hosts on the public internet, never this computer or your local network. Each name is looked up once and the connection goes to the address that was checked, on port 80 or 443 and through no proxy, so a name can't pass the check and then point somewhere local.
- **The page is local only.** It binds to 127.0.0.1 and rejects requests from other sites. The one way in from elsewhere is `proxenos phone`: your Mac's private address on your own Tailscale network, answered only for your own Tailscale login. Nothing is opened to the internet, except, if you set up calls, one port Tailscale Funnel opens for Twilio, which answers only during a call and only requests Twilio signed.
- **Credentials** stay on your computer: in its own secure store, one item each (the macOS Keychain, Windows Credential Manager, or the Secret Service on Linux), or in `.env` (which git ignores) when you run from source with one. The page shows whether each is set, never what it is.
- **Found a security problem?** Please report it privately: see [SECURITY.md](SECURITY.md).

## Quick start

**One command**, on a Mac with [Homebrew](https://brew.sh):

```bash
git clone https://github.com/mindemory/proxenos && cd proxenos && scripts/install.sh
```

It installs what's missing (Node, Ollama's own app, and Miniforge if there's no conda), sets up the `proxenos` env and the page's packages, and pulls a local model that fits your Mac's memory. Then `conda activate proxenos && proxenos web`. Add `--start-at-login` to keep the page and a sync running from login on, or `--no-model` to use a hosted model instead. Running it again only adds what's missing.

**By hand**, step by step. Requirements: macOS, Python 3.12 (conda shown here), Node 22+, and a model for the steps that use one: an open model on your Mac through [Ollama](https://ollama.com) (no key, nothing leaves the computer; `gemma4:26b` fits a 32 GB Mac), or an Anthropic API key. Use Ollama's own app, not Homebrew's `ollama` formula, whose build can't hold a model to the JSON shape a step asks for. Another app that serves OpenAI's API on this computer works too: LM Studio, llama.cpp's `llama-server`, Jan, LocalAI or vLLM, as `PROXENOS_MODEL=local:<name>` at `PROXENOS_LOCAL_URL` (LM Studio's `http://127.0.0.1:1234/v1` unless you set another, such as `llama-server`'s `http://127.0.0.1:8080/v1` or vLLM's `http://127.0.0.1:8000/v1`). Load the model there with a context of 65,536 tokens. Search by meaning still embeds through Ollama.

```bash
git clone https://github.com/mindemory/proxenos && cd proxenos
CONDA_SUBDIR=osx-arm64 conda env create -f environment.yml
conda activate proxenos
pip install -e ".[dev]"
brew install --cask ollama-app && open -a Ollama && ollama pull gemma4:26b   # the local model
ollama pull qwen3-embedding:0.6b   # search memory by meaning (optional)
proxenos web                    # http://127.0.0.1:4747; leave it open, and use another window below
```

The first time, the page asks three things: your name, where the vault lives (`~/proxenos_vault` unless you pick another folder; it warns about folders iCloud syncs), and a model, either one on this computer, through Ollama or another app's server, or an Anthropic API key, checked with one small call. It lists the local models it finds with their sizes, marks the ones too big for this computer's memory and suggests the largest that fits; with none yet, it says what size to get. The model can wait: sources still sync and search still works, but nothing is drafted. Then it opens Connect for a first source. Settings go to `~/Library/Application Support/Proxenos/settings.json` and keys and tokens to the macOS Keychain, one item each; change them later in Settings. (On Windows they go to `%APPDATA%\Proxenos\settings.json` and Credential Manager; on Linux, to `~/.config/proxenos/settings.json` and the Secret Service.)

Prefer a file? `cp .env.example .env` and fill it in. Running from source, `.env` is read before the settings file and the Keychain, and with one there, changes from the page are written to it.

**Try it without your data:** `proxenos demo` writes a vault of made-up records (the one in the pictures above) to a temporary folder, with no model and no `.env`, and prints the command that opens the page on it, on port 4848 so it can run beside your own. Nothing is ever sent from it.

Add data in any order. Each source works on its own:

```bash
proxenos ingest whatsapp        # reads the WhatsApp Mac app's local store
proxenos import ~/Downloads/takeout-*.zip   # Google Takeout: mail, calendar, Drive, YouTube, ...
proxenos sync                   # imports anything dropped into data/, refreshes every source
```

Then build the model and the clones:

```bash
proxenos master                 # notes per month, then the self-model
proxenos clone tracker          # also: tasks, care, advisor, network, choices, jobs, watch, recall, projects, work
```

Your long-running projects are a list you keep in the vault, `clones/projects/projects.json`: each with an id, a name, what it's about, its people and the words that name it, and a group if you like ("PhD", "Postdoc"), which the page lists them under. A `brief.md` in the project's folder says what's known around it, the question and the first analyses; the night reads it, and the project's page shows it. Each night Proxenos writes where each one stands, from what your messages say and, given its code's folder, the commits on every branch since the last run. Give one its data folders too, and it also does the work, a step a night, on a branch of its own, and brings it back for you to accept on the page's Projects view:

```json
{"id": "calls-paper", "name": "The calls paper", "about": "...", "people": ["Ana Lee"],
 "repo": "~/code/calls", "data": ["~/data/calls"], "python": "~/envs/calls/bin/python",
 "notes": "F*.py make the paper's figures.",
 "manuscript": {"path": "docs/paper/paper.md", "branch": "paper"}}
```

A project with code also has its manuscript one click away: **Manuscript** on the Projects view shows the paper's old version and its new one, the changes between them marked (what came in highlighted, what went struck through, word by word), and a picker for any two versions. It's the file `"manuscript"` names, else the newest `paper.md`, `manuscript.md` or `main.tex` (or a `.tex` under `paper/` or `manuscript/`) on any branch, read with git, so the draft can be on a branch your checkout isn't on. Change it there in either of two ways: ask for a change in your words, which a step does on a branch from the manuscript's, or edit the text and save, which commits it on a branch of its own, `proxenos/<project>-edit-<when>`. Either waits on you as a step, with **See the changes** beside Accept and Discard, and **Revise this step** to ask for more on top of it. Accept merges into the manuscript's branch, once your checkout is on it. Nothing touches your checkout until then, and nothing is pushed. `proxenos project manuscript ID` prints the same as JSON.

To write with co-authors the way you already do, sign in to Google Docs once and press **Open in Google Docs** on the manuscript: it goes to your own Drive as a Google Doc, yours alone until you share it from Docs, and opens in a new tab. Edit, comment and share it as usual. **Bring back its changes** puts what changed in the doc on a branch of its own, from the version it was made from, and it waits on you as a step like any other edit: only the paragraphs changed in Docs change, and the rest keeps its own Markdown or LaTeX to the byte. The doc's comments show beside it, with who said what about which passage. Git stays the source of truth ([docs/data_sources.md](docs/data_sources.md#a-manuscript-in-google-docs)).

To keep every project in a cloud drive you already sync on this computer (Google Drive for desktop, Dropbox, OneDrive or iCloud Drive), set its folder in Settings, under Projects (or `PROXENOS_PROJECT_FOLDER`), and install pandoc (`brew install pandoc`), which makes the Word files. Each night each project gets a folder there, under its group: its manuscript at its branch's tip as a `.docx`, with its PDF when one is committed beside it, where it stands, what's known and the question, its open drafts, and what it's about. Read, edit, comment on and share them in Word or Google Docs. What you change in a Markdown manuscript comes back the next night as a step on a branch of its own, only the paragraphs you changed changed; a LaTeX one is made with its citations and references written out, so it goes one way. Nothing you changed is written over: a note you edited stays as you left it, and when the paper moves on in git, your copy moves to `Earlier/` with the date before the newer one is written ([docs/data_sources.md](docs/data_sources.md#your-projects-in-a-cloud-drive)).

To keep it running without a terminal, run `scripts/install-app.sh`: the page and a sync every 15 minutes then start at login. `scripts/build-mac-app.sh` then builds Proxenos.app into ~/Applications: the page in a window of its own, with a Dock icon and menus, no browser. `desktop/build.sh` builds the coming one-download app instead: an Electron app with its own Python inside, a menu-bar menu (Open, Sync now, Pause, Quit) and the sync and night built in, as a Mac `.dmg` or a Windows installer. It's unsigned until the owner's signing accounts exist, so macOS asks you to allow it under Privacy & Security first ([docs/apps.md](docs/apps.md)). To reach it from your phone, put [Tailscale](https://tailscale.com/download) on both, signed in to the same account, and run `proxenos phone`: the page gets a private address only your own devices can open, and Chrome on the phone can add it to the home screen.

`proxenos night` runs the whole loop. `scripts/install-night.sh` schedules it every night with launchd.

`proxenos schedule` does the same on any computer, with no launchd: a sync every 15 minutes and the night at 01:30, run once on waking if the computer slept through either, and never two at once (nor beside one launchd or a terminal started). Leave it running in a window, or start it at log-on with Task Scheduler on Windows or a systemd user unit on Linux ([docs/apps.md](docs/apps.md#keeping-it-running-from-source)); the coming Mac and Windows apps will run it themselves. `proxenos schedule --once` runs whatever is due and exits.

`px` is a short alias for `proxenos`.

Some sources read a folder on your computer: a folder of documents, your website's repo, a Spotify export, slackdump runs. Set them in Settings, or in `.env` as `PROXENOS_DOCS_DIRS`, `PROXENOS_WEBSITE_REPO`, `PROXENOS_SPOTIFY_EXPORT` and `PROXENOS_SLACKDUMP_DIR`. To have plans from your messages land on one of your calendars, set `PROXENOS_PLANS_CALENDAR` to its name in the Mac's Calendar app, which syncs it to its account (Google, Exchange, iCloud); otherwise subscribe to the page's `/api/plans.ics`. `.env.example` lists every setting.

## Sources

| Source | How it gets in |
|---|---|
| WhatsApp | The Mac app's local database (`proxenos ingest whatsapp`) |
| Slack | [slackdump](https://github.com/rusq/slackdump) (`proxenos auth slackdump WORKSPACE`, then kept current every sync), or a user token |
| Gmail, Google Calendar, Drive, Photos metadata, Keep, Tasks, YouTube, Chrome | Google Takeout zips (`proxenos import`) |
| Email (any) | mbox exports; Gmail over IMAP with an app password or a Google sign-in (`proxenos auth gmail`) |
| Microsoft 365, Outlook.com | Mail and calendar through Microsoft Graph, with a read-only sign-in to your own app registration (`proxenos auth microsoft NAME ADDRESS`), then kept current every sync. No mail app needed, so it works on any computer |
| Google Calendar, live | The Calendar API with a read-only Google sign-in, apart from Gmail's (`proxenos auth gcalendar NAME ADDRESS`), then kept current every sync |
| Apple Mail | Every account in the Mac's Mail app (Gmail, Google Workspace, Microsoft 365, Outlook), with no sign-in of its own: add the accounts in System Settings, Internet Accounts, keep Mail open (or set to open at login) so it fetches, and give the Python that runs Proxenos Full Disk Access. `proxenos sync` then reads it every run. |
| Health records | Apple Health's export (Health Records from your providers), or the FHIR files a patient portal lets you download (`proxenos import`, or `proxenos ingest healthrecords --export PATH`): results, conditions, medications, visits and reports, for the care view |
| Spotify | Your latest plays live, once you sign in through your own Spotify app (`proxenos auth spotify`); your whole history from the Extended Streaming History export |
| LinkedIn, X, Instagram, Facebook, Threads | Each service's data export; Instagram, Messenger, X and LinkedIn chats live through [Beeper Desktop](https://www.beeper.com) (free for up to five accounts) |
| Bluesky | Public posts by handle |
| Notion, Obsidian, PDFs | Exports or folders |
| Letterboxd | Data export, and your public diary feed by username (`PROXENOS_LETTERBOXD_USER`), which sync reads every run so new logs come in without one |
| ChatGPT, Claude | Each one's data export (ChatGPT: Settings, Data controls, Export data; Claude: Settings, Privacy, Export data); drop the zip in `data/` |
| Calendar, live | Any account in the Mac's Calendar app (Google, Exchange, iCloud), read every sync once Proxenos's Python has Full Disk Access |
| Personal website, papers and mentions | A local site repo; OpenAlex and news search |
| Strava (optional) | API (`proxenos auth strava`): walks, runs and rides, the least of what Proxenos reads |

See [docs/data_sources.md](docs/data_sources.md) for each one's details.

## Commands

| Command | What it does |
|---|---|
| `proxenos ask [QUESTION]` | Ask your twin: a question, a pasted message or screenshots (from the page's Ask view), answered from your memory the way you'd think it through, with a reply drafted when it's a message to you |
| `proxenos think "TEXT" [--thread ID] [--context-kind KIND --context-id ID]` | Think anything through with Proxenos (also the page's Think view, and "Think it through" on a draft, a project or a day): a reply in its own plain voice from your goals, notes, last few days and memory, with what matters here and where each point comes from, questions to sit with and optional next steps. It never decides for you. `--thread` goes on with a thread; `--context-kind` (`draft`, `project`, `day` or `person`) starts one from something. `--list` and `--show ID` print threads as JSON |
| `proxenos phone` | Open the page to your own phone over Tailscale |
| `proxenos speech status` / `get natural\|own` / `say TEXT -o FILE.wav [--engine natural\|own] [--voice V]` / `serve` / `clip save\|delete` | Listen's natural voice (Kokoro-82M) and your own (Qwen3-TTS, from a clip of you reading), made on a Mac with Apple silicon once `pip install -e ".[speech]"` is in; also in Settings, Listening. `get` downloads a model once, `serve` keeps them loaded for the page on 127.0.0.1 only and stops itself after 15 idle minutes, `clip save` reads `{"wav", "text"}` on stdin. Nothing is sent anywhere |
| `proxenos notify test` | Send a test notice to your phone through ntfy (also Settings' Send a test), and say whether it got through. With a topic saved, `sync` and `night` send one when more waits on you, counts only, held through quiet hours |
| `proxenos call start NAME` / `stop NAME` / `list` | Place a phone call from a call sheet (also from the page's Calls view), through your own Twilio account: it waits on hold, says it's an automated assistant calling for you, and rings you when a person answers, or asks for what the sheet lists. It never agrees to pay. See [docs/calls.md](docs/calls.md) |
| `proxenos web [--port N]` | The local page: a landing, then the app, whose views the sidebar groups as Today (Home, Drafts, Tasks, Care, Errands, Calls), Ask and think (Ask, Think, Advice, Choices), Work (Projects & papers, Jobs, Feed, Saved, Watch), Your life (Journal, Life, Rhythms, Network, Memory, Profile) and Setup (Connect, Settings, Privacy, Status), after a short setup the first time |
| `proxenos compare start --model X [--against Y] [-n 10]` / `pick ROUND ITEM A\|B\|both\|neither` / `results [ROUND]` | Which of two models writes replies most like you (also in Settings, "Which writes like you?"): both redraft your replies in your 10 most recent conversations as they stood just before you answered, never seeing those replies, and you pick blind between A and B; which wrote which, and what you sent, shows after. `--against` defaults to the drafting model set up; `voice` or `voice:mlx` names a voice model. Results give each model's share of picks won with a 95% interval, and how close its drafts came to what you sent. Nothing is sent to anyone. Prints JSON for the page |
| `proxenos privacy` | What stays on this computer (the vault by folder, whether a cloud syncs it, FileVault, the secrets kept, by name), what went to a model in the last 30 days (calls by where they ran and by part, from the calls log, never the words), what's read from elsewhere and whether notices go to your phone, as JSON for the page's Privacy view |
| `proxenos demo [PATH]` | A vault of made-up records to try the page on, with no model, and the command that opens it. PATH must be new, empty or an earlier demo |
| `proxenos form PATH` | A PDF form filled in from your records, beside it as `-filled.pdf`, with what it filled, where each answer came from and what's left for you. It never fills an SSN or another ID, an account or card number, or a signature, and keeps only answers your records show |
| `proxenos sync` | Import new downloads and refresh every source that needs no model, noting when each was checked so a source with nothing new still shows as fresh; update the memory index and today's recall. With a model, also draft replies to chats newly waiting on you (at most five a run), and, at most hourly when something new was said, update the task list, put new plans on your calendar and fold away drafts made moot. With an ntfy topic saved, last of all a notice to your phone when more waits on you |
| `proxenos import [PATH ...]` | Recognize and import downloaded exports |
| `proxenos ingest <source>` | Pull one source into the vault |
| `proxenos auth strava` / `slack` / `slackdump WORKSPACE` / `gmail NAME ADDRESS` / `gcalendar NAME ADDRESS` / `gdocs NAME ADDRESS` / `microsoft NAME ADDRESS` / `beeper` | One-time sign-ins: tokens go to the Keychain (to `.env` when running from source with one); slackdump keeps its own. Most can also be done from the app's Connect page. `gdocs` sees only the files Proxenos makes in your Drive |
| `proxenos observe [--dry-run]` | Per-month notes on what each source says about you |
| `proxenos master [accept]` | Sync, observe and update the self-model; `accept` applies proposed changes |
| `proxenos index [--rebuild]` | Full-text memory index over the whole vault, no model |
| `proxenos clone <name>` | Run one clone: `tracker`, `tasks`, `care`, `advisor`, `network`, `choices`, `jobs`, `watch`, `recall`, `projects`, `steps`, `folders`, `work`, `journal`, `life` or `rhythms` |
| `proxenos clone journal [--date DAY]` | The day, written down (also from the page's Journal view): what got done, where you wrote, what moved in your projects, what's waiting and what's next, with a short brief. The night writes the day that just ended; `--date today` writes today so far |
| `proxenos clone life [--month YYYY-MM] [--day YYYY-MM-DD]` | A diary of your life by month and day, years back (also on the page's Life view). `--month` writes that month's diary now, from what you marked not true or edited in it, what you told Proxenos, its care timeline, the observers' notes and its days; `--day` prints a day's digest as JSON, with no model. The night writes the month that just ended, the current one once a week, any month you told Proxenos about or marked not true since it was written, and four older months with no diary (or one from before there was an essay), newest first, so years fill in over a few weeks; never a month you edited |
| `proxenos clone rhythms [--weeks N] [--label N] [--look-up N] [--month YYYY-MM] [--earlier N\|all] [--json]` | Your weeks over time (also on the page's Rhythms view), each ISO week in local time with no model: listening hours, plays, artists and the genre and mood mix, rides, runs, hikes and walks, messages sent and received by channel and how many people you wrote to, and calendar events. Only the month files that changed are counted again. `--label` asks the model for up to N more artists' genre and moods, from their names alone, the most played first (300 a night); `--look-up` asks MusicBrainz for up to N more artists' genres, by name alone (120 a night). Then the month cards that are due: how each month felt in your own writing, what you listened to and wrote, and how your mood and music moved together. `--month` makes one month's card now, and `--earlier` the earlier months' cards that are due, newest first, N of them or all, where the night makes six; `--json` prints the series and the cards made for the page, with no model and no lookups; `--weeks` keeps to the last N weeks |
| `proxenos clone steps --project ID` | A step of a project's own work (also from the page's Projects view): the next analysis, fix, figure or section, done on a new branch of the project's code in a worktree of its own, by Claude Code where it's installed or else the local model, and reported. Accept on the page merges it into your checkout; Discard deletes the branch. Nothing is pushed |
| `proxenos project manuscript ID [--base REV] [--head REV] [--step STEP_ID]` | A project's manuscript as JSON for the page, read with git and no model: where it is, its versions, and one version's text with its changes since another, word by word; with `--step`, every file a step changed. `--edit` saves text read from stdin on a branch of its own, as a step waiting on you |
| `proxenos project gdocs ID [open\|fresh\|pull\|comments] [--account NAME]` | The manuscript as a Google Doc in your own Drive (also the Manuscript view's Open in Google Docs and Bring back its changes), as JSON for the page. With no action, the doc and its comments as the vault keeps them, nothing fetched. `open` makes it from the manuscript at its branch's tip the first time, then gives its link; `fresh` makes a new one; `pull` brings back what changed in it as a step waiting on you, only the paragraphs changed in Docs changed, and reads its comments; `comments` reads them alone. Comments are never sent to a model. Needs `proxenos auth gdocs` |
| `proxenos clone folders [--project ID] [--pull-only]` | Each project as a folder in your cloud drive (`PROXENOS_PROJECT_FOLDER`), `<group>/<name>/`, of Word files pandoc makes: the manuscript at its branch's tip (and its committed PDF), where it stands, its brief, its open drafts, what it's about and what the folder is. What you changed in a Markdown manuscript there comes back first, as a step waiting on you with only the paragraphs you changed changed, and another waits until that one is decided; LaTeX goes one way. A note you changed is never written over, and your copy of an older manuscript moves to `Earlier/` first. The night runs it after the steps; `--pull-only` only brings changes back. No model |
| `proxenos clone choices [--force]` | The week's choices: what's worth taking on and what's worth letting go of. The night runs it once a week; `--force` runs it now |
| `proxenos clone jobs [--days N]` | Every job lead in one place (also on the page's Jobs view): LinkedIn's job alerts and recruiters' messages, Work at a Startup's notices of founders' messages, recruiters' emails, job boards, lists, Slack and the job posts you shared to Ask, each job once however many places it came from, with a verdict and why, the best way in, the CV that fits, whom to contact and the first step drafted in Drafts. Applied is suggested from the applications in your sent mail and the receipts, for you to confirm. The night runs it; `--days` reads further back than the last run |
| `proxenos clone watch [--force]` | What to watch next: films and shows you haven't seen, picked from what you loved on Letterboxd, and the films on your watchlist that suit this week. The night runs it once a week; `--force` runs it now |
| `proxenos clone errands "GOAL"` | An errand (from the page's Errands view): something to get done, such as reaching someone about a role with your CV, carried as far as it goes and stopped one tap short, with every step it took. Nothing goes out until you press Send on it |
| `proxenos night` | Everything above, in order, for a schedule |
| `proxenos schedule [--once] [--sync-every MIN] [--night-at HH:MM]` | Keep everything current until stopped, on any computer: `sync` every 15 minutes and `night` at 01:30 (or `PROXENOS_SYNC_EVERY` and `PROXENOS_NIGHT_AT`), each in a process of its own with its output in `<vault>/logs/`, once on waking after a missed slot, and never two runs at once. `--once` runs what's due and exits. Where it stands (the last and next run of each, and what's running) is in `<vault>/state/schedule.json`, for the page |

## Development

```bash
pytest                                   # tests use synthetic data only
ruff check src tests
npm --prefix web run lint && npm --prefix web run build
```

The same checks run on GitHub for every push and pull request.

`scripts/screenshots.sh` retakes the pictures under [What it looks like](#what-it-looks-like), from the demo vault with headless Chrome (it needs Google Chrome and a Python with Pillow). Open each one before committing it.

For AI coding agents, [AGENTS.md](AGENTS.md) maps the repo, its commands and its rules, and [llms.txt](llms.txt) indexes the docs.

## Built on

Proxenos stands on other people's open-source work: Next.js, React, Tailwind, Ollama, slackdump, Beeper's local API, OpenAlex, mlx-lm and more. Each is credited, with its licence, in [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md). Code taken from elsewhere keeps its licence and copyright notice, and is listed there too.

## License

[MIT](LICENSE)
