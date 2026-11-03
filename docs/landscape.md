# Landscape and approach

What other people have built when they set out to make a digital twin of a person, what the evidence says, and the approach Proxenos takes.

## What the goal actually splits into

"A replica of you that keeps evolving and works while you sleep" is three separable things:

1. **A self-model.** A representation of who you are: interests, beliefs, taste, voice, how you decide.
2. **An agent** that uses the self-model to act for you, e.g. pick and read articles overnight.
3. **A learning loop** that keeps the self-model in sync as you change.

Most existing projects build one of these well and fake the other two.

"Exact replica" isn't a reachable target. "Predicts you well, and you can measure how well" is. The best published number: agents built from a 2-hour interview with each of 1,052 people reproduced their General Social Survey answers at 85% of the consistency people show with *themselves* two weeks later ([Park et al., Stanford/DeepMind](https://www.alphaxiv.org/abs/2411.10109v1), [HAI summary](https://hai.stanford.edu/policy/simulating-human-behavior-with-ai-agents)). That covers attitudes from a single interview. Nobody has a credible number for "does everything you do."

## What people have built

| Approach | Examples | Good at | Breaks on |
|---|---|---|---|
| **Persona + RAG over your content** | [Delphi](https://venturebeat.com/ai/you-can-now-make-an-ai-clone-of-yourself-or-anyone-else-living-or-dead-with-delphi), [Sensay](https://topai.tools/alternatives/sensay), most personal "digital twin" GitHub repos ([example](https://github.com/kavyahj04/My-Digital-Twin)) | Answering "what does X think about Y" from what X has already said | It's a snapshot that doesn't evolve. It has no judgment on new material and hallucinates past its corpus ([Delphi review](https://www.philsimon.com/schwarzenegger-hallucinations-titanic-ai/)). |
| **Fine-tune a model on you** | [Second Me](https://blog.brightcoding.dev/2026/09/18/mindversesecond-me-train-a-local-ai-self-with-hierarchical-memory) (Mindverse): hierarchical memory, SFT + DPO LoRA on Qwen2.5, runs locally | Voice, tone, phrasing | Weak on facts ([style vs knowledge](https://letsdatascience.com/blog/fine-tuning-llms-with-lora-and-qlora-complete-guide)). Every update means retraining. It's opaque, so you can't read or correct what it learned. Small local models fall well short of frontier models at research. |
| **Interview-grounded agents** | Stanford 1,000 people (above); Columbia [Twin-2K-500](https://arxiv.org/abs/2505.17479) (~87% of test-retest) | Attitudes, survey answers, personality | Regresses toward the average: lower variance and fewer extreme answers. Richer personas drift progressive ("blue-shift"). Better at relative differences between people than at precise individual prediction ([Columbia DAPLab](https://daplab.cs.columbia.edu/projects/digitaltwins)). |
| **Lifelogging capture** | Rewind → Limitless → [bought by Meta, Mac capture shut off Dec 2025](https://screenpi.pe/blog/rewind-ai-alternative-2026); [Screenpipe](https://screenpi.pe/about) (open source, local OCR + Whisper); Microsoft Recall | A raw record of what you actually do | It's a firehose, not a model. Around 20 GB/month, heavy on privacy, and it needs a distillation layer on top. |
| **Agent memory systems** | Letta (MemGPT), Mem0, Zep/Graphiti ([comparison](https://dev.to/agdex_ai/letta-vs-zepgraphiti-vs-mem0-choosing-an-ai-agent-memory-architecture-155a)) | Long-running agents that remember across sessions. Zep's temporal graph records *when* a fact was true. | Built to remember facts *about* a user, not to *model* the user. Benchmark results disagree ([LongMemEval: Mem0 49% vs Zep 63.8%](https://vectorize.io/articles/mem0-vs-zep), independent run). |
| **Compiled markdown memory** | Karpathy's "LLM knowledge base" (Apr 2026): immutable `raw/`, an LLM-maintained wiki, a schema file ([write-up](https://blog.pebblous.ai/report/karpathy-llm-wiki/en/)); OpenClaw's `MEMORY.md` + daily logs with promotion ([anatomy](https://agento.host/blog/openclaw-agent-anatomy)) | Readable, editable, diffable, versioned in git. Fits in a frontier model's long context with no vector DB. | Only as good as the schema discipline. It will eventually hit scale limits, though hundreds of thousands of words is fine. |
| **Always-on scheduled agents** | OpenClaw heartbeat ([docs](https://clawdocs.org/architecture/heartbeat)): every 30 min, tasks in natural language; [Khoj](https://docs.khoj.dev/category/features/) automations + `/research`; Claude Code scheduled tasks | The "while you're asleep" part | Without a good self-model, a heartbeat is just a newsletter. |
| **Self-hosted AI workspace** | [Odysseus](https://github.com/odysseus-dev/odysseus) (PewDiePie, May 2026, AGPL-3.0): chat and agents with shell, files and MCP, deep research over a bundled SearXNG, blind model comparison, an IMAP inbox with triage, CalDAV, ntfy notices, ChromaDB memory, and a "Cookbook" that matches models to the hardware | One place on your own machine for everything you'd use ChatGPT for, with local models | It's a workspace you drive, not a model of you: memory is notes and vectors, and nothing measures whether it writes or decides like you. Agents with a shell are a large local attack surface; its own roadmap lists a prompt-injection audit. |

The most directly relevant idea is Letta's **sleep-time compute** ([coverage](https://fastcompanyme.com/technology/why-sleep-time-compute-is-the-next-big-leap-in-ai/)): use idle time to consolidate memory and precompute what you'll probably need. It's explicitly modeled on sleep-dependent consolidation.

## Takeaways that shape the design

1. **Keep the self-model in plain text you can read and edit.** Being able to correct the model is the main way it gets accurate. That rules out fine-tuning as the foundation.
2. **Keep facts separate from voice.** Beliefs and facts go in text. Voice is a style guide plus example passages in the prompt. Fine-tune only if an eval shows prompting can't match your voice.
3. **Make time first-class.** "Evolving" means beliefs carry `since` / `until` / evidence ("thought X until March, now Y") instead of being overwritten. That's Graphiti's idea, done in markdown frontmatter.
4. **Only your own behavior counts as evidence.** Proxenos's outputs must never be fed back in as evidence about you. Tag provenance on everything: written by you, your reaction to something, or made by Proxenos. Without this, the model learns from itself and drifts toward an LLM's average idea of you. It's the most common failure, and it's silent.
5. **Two timescales.** Fast state (what you're into this week) updates nightly. Slow state (values, core beliefs, voice) changes only through proposed diffs that you approve. Hippocampus fast, cortex slow: complementary learning systems.
6. **Measure fidelity with predictions.** Before you read something, Proxenos predicts whether you'd pick it, how you'd rate it, and what you'd think. After you read it, compare. That number over time is the working definition of "replica." A short monthly re-interview gives a test-retest baseline.
7. **Budget for exploration.** A model that only picks what you'd pick builds a filter bubble. And if you read whatever it hands you, you converge on the model instead of the other way round. Reserve a slice (~20%) for adjacent or contrarian material.
8. **Read-only first.** Researching and writing briefs is low-risk. Acting *as* you in the world (emails, posts, replies) is a different risk level and can wait.

## The starting design

This is the shape Proxenos started from. [architecture.md](architecture.md) describes what is built today.

**Two repos.**
- `proxenos/` (this one): code for ingesters, the nightly loop, and evals. Public on GitHub.
- The vault: the self-model and raw data, kept in its own private git repo *outside* this one. Code finds it through `PROXENOS_VAULT` in `.env`. Its `git log` becomes the record of how you changed.

```
vault/
  raw/               immutable sources, by source and date
  self/
    identity.md      roles, current projects, context
    interests.md     topics with weight + last-active date
    beliefs/         one file per claim: stance, confidence, since, evidence
    taste.md         what you read vs. skip, and why
    voice.md         style guide + example passages
    open_questions.md
  journal/           daily logs (fast memory)
  briefs/            nightly research output
  evals/             predictions vs. what you actually did
  CLAUDE.md          schema: how the agent maintains all of this
```

**The nightly cycle.**
1. **Ingest:** pull the day's new signals into `raw/`.
2. **Consolidate:** write the journal entry. Propose changes to `self/`: apply the fast ones, queue the slow ones for review. Flag contradictions, since each one is either real change or noise.
3. **Research:** pick topics from interests, open questions, and the exploration slice. Find and read material. Write a brief with a summary, your likely take, and what would change your mind.
4. **Predict:** for each item, predict your reaction.

**Morning:** you skim the brief and react in a line per item. Those reactions are the highest-quality signal there is. They score the predictions and feed the next night's consolidation.

**Bootstrapping:** a structured ~2-hour interview, Stanford-style, about your life story, values, how you choose what to read, and recent changes of mind, would give the first draft of `self/`. Without one, the first draft comes from the observers' notes on your data.

**Where it runs.** A sleeping laptop runs nothing. The options are:
- the Mac, via launchd plus keep-awake (simplest, data stays local);
- a cloud scheduled agent (needs the vault on a private remote);
- a small VPS.

**Which models.** A frontier API model for consolidation and research quality. A local model only for data that must never leave the machine. A hybrid works well: a local model distills the raw data, and the API only ever sees the distilled self-model.

## Choices the design leaves open

1. **What is the main job?** A research-overnight agent, a talk-to-you clone, or a decision predictor. Proxenos started with the research feed: it's the most direct use of a self-model, and it comes with a daily feedback loop. The other clones followed.
2. **Which data is in bounds?** Yours to decide, source by source. See [data_sources.md](data_sources.md).
3. **Where does it run?** On your Mac by default, with a nightly launchd job. A cloud agent or a VPS would need the vault on a private remote.
4. **Where is the privacy line?** What may be sent to an API model, and what stays local. See the privacy notes in [data_sources.md](data_sources.md#privacy).
5. **Stack.** Python 3.12 for the pipeline and a local Next.js page.

## Ideas to borrow from Engramme

Notes from [Memory is not search](https://www.engramme.com/index/memory-is-not-search). Not a competitor plan; these are the parts that fit Proxenos.

- **Proactive recall, not just search.** Memory should surface what's relevant from the current situation, with no query. For Proxenos, that means a recall clone. Given today's calendar, open tasks and the feed, it would pull the past conversations, notes and people that bear on them, e.g. "you discussed this with X last March". Built: `proxenos index` and `proxenos clone recall`, shown on the page's Home and Memory view.
- **Associative cues.** Useful recall often shares no words with the present. It runs through people, places, times and events. Index raw records by person, place and time, not only by text.
- **Lossy but specific.** Keep the idiosyncratic particulars, like the place or the exact phrase, rather than generic summaries. Observers should favor concrete specifics.
- **Grounding and abstention.** Every recalled memory or claim links to its evidence ids, and recall may return nothing when nothing fits.
- **Right to forget.** Add a `proxenos forget` that removes matching raw records and notes, then re-consolidates.
- **How to judge recall:** timeliness, informativeness, abstention and non-redundancy. Score it with the same useful / not-me reactions the page already collects.

## What's new, and what Proxenos takes from it (November 2026)

Checked against papers, model cards, release notes and the code on November 1, 2026. Each part says what Proxenos took, what's next, and what it leaves out, with why.

### Memory and retrieval

The original LongMemEval is close to saturated, and vendors' scores on it can't be compared. The newer, independent work favours two things that fit Proxenos better than graph or trained memory stacks: searching the stored records themselves, and keeping track of what's true now.

- **Taken:**
  - Word and meaning searches merged by reciprocal rank fusion, so a record several searches rank high comes first ([Cormack et al., 2009](http://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf); [Bruch et al., 2023](https://arxiv.org/abs/2210.11934)).
  - Meaning, not only words, for proactive recall.
  - Planned searches that can carry a date range. Time-aware queries raised recall on time questions by 6.8–11.3% in [LongMemEval](https://arxiv.org/abs/2410.10813).
  - A log of what each research run kept, to tune the merging on real decisions later.
  - Voice rules inferred from drafts the user rewrote and checked against their own sent messages, proposed for them to accept ([PROSE, ICML 2025](https://arxiv.org/abs/2505.23815), which improved on [CIPHER](https://arxiv.org/abs/2404.15269)).
- **Next:**
  - A small local reranker, [Qwen3-Reranker-0.6B](https://github.com/QwenLM/Qwen3-Embedding) (Apache-2.0, through mlx-lm). On Qwen's own table it lifts retrieval from 61.8 to 65.8.
  - Research that opens the records it finds and reads around them. Agents searching raw records scored 69–72% against 48.5% for the best retrieval baseline in [LongMemEval-V2](https://arxiv.org/abs/2605.12493).
  - Tasks that can be cancelled or moved, not only done. Agents fumble cancellations ([ProEvent](https://arxiv.org/abs/2607.17701)), and recording what replaced what helps ([StateMemBench](https://arxiv.org/abs/2608.19652)).
  - Fidelity that scores style apart from content ([StyleDistance](https://huggingface.co/StyleDistance/styledistance)).
- **Left out:**
  - Graph memory servers (Graphiti/Zep, Mem0's graph): they need a database and a model call per message, and break on small local models' JSON. Proxenos borrows their ideas instead: time ranges, and invalidating rather than deleting.
  - ColBERT-style indexes: about 19 GB for a year of messages.
  - A vector database: brute force takes 17 ms over 200,000 units on this Mac.

### Local models on a 32 GB Mac

From Ollama's own log over four days:
- **Speed:** the model reads prompts at about 240 tokens a second and writes at about 23.
- **Where the time goes:** 56% of its busy time was reading prompts, and prompts over 20,000 tokens took over half of all model time.

So what makes nights faster is sending less, not a different engine.

- **Taken:**
  - The schema goes to Ollama as `format`, which holds the model to it as it writes, thinking first or not.
  - Every answer is still checked item by item, so one malformed item is dropped instead of crashing a clone.
  - One line per model call in the vault (`state/model-calls.jsonl`), to find the slow steps.
- **Next:**
  - **Install Ollama from its own app.** Homebrew's build leaves out the grammar library, so `format` falls back to the check alone.
  - **Stop the embedding model pushing the main model out of memory:** a smaller context for embeddings.
  - **Send less in the longest steps,** chosen from the calls log.
  - **Lay prompts out so their start can be reused,** with the phone call as real chat turns.
- **Models:**
  - Stay on `gemma4:26b`: a mixture of experts with 3.8B parameters active per token, Apache-2.0, pretrained on 140+ languages.
  - Dense 27–31B models write at about 6 tokens a second on an M1 Pro.
  - Qwen3.6-35B-A3B is strong but too tight in 32 GB.
- **JAX:** not a fit here. Apple-GPU support for JAX (jax-metal) was last released in October 2024, and nothing in Proxenos is a JAX workload. numpy does the one matrix multiply in vector search, and MLX does the LoRA training and, later, audio.
- **Voice in and out, all local, for bad days:**
  - speech to text with mlx-whisper and whisper-large-v3-turbo (MIT; Hindi and Marathi included);
  - speech with Kokoro-82M through mlx-audio (Apache-2.0), or [Indic Parler-TTS](https://huggingface.co/ai4bharat/indic-parler-tts) for Hindi and Marathi.

### Security and privacy

The consensus has moved. Filters and prompts don't reliably stop prompt injection once an attacker adapts: 12 published defenses fell, most above 90% attack success ([Nasr, Carlini et al., 2025](https://arxiv.org/abs/2510.09023)). What holds is design: no single step should have untrusted text, private data and a way to send out all at once ([Meta's Agents Rule of Two](https://ai.meta.com/blog/practical-ai-agent-security/)). In Proxenos, drafts are safe by design: a person reads them and presses send. The opt-in outbox is the one place all three meet.

- **Taken:**
  - **Outbox limits.** It never answers a first contact, and it holds back any draft carrying a link, address or number the chat didn't have. For email, it sends only when the reply would go to the sender.
  - **Others' words marked as data.** Their messages and fetched pages go into prompts inside a boundary that's random for each call, which cut attacks from over 50% to under 2% in Microsoft's [spotlighting](https://arxiv.org/abs/2403.14720) study. It's one layer, not the gate.
  - **Safer link fetching.** It connects to the address it checked, so DNS rebinding can't point it at this computer or the home network.
  - **A stricter project-step sandbox.** It refuses to run when the sandbox can't start, and hides more of the home folder.
  - **Patched dependencies.** The web framework and the PDF libraries that read forms you receive are at fixed versions.
  - **Hardened CI.** Its actions are pinned to exact commits, and it audits dependencies.
  - **A privacy screen.** The page shows what stays on the computer (with whether FileVault is on), what went to a model in the last 30 days and where, and what's read from elsewhere.
- **Next:**
  - Python dependencies locked with hashes.
  - Numbers and secrets blanked before a hosted model sees other people's messages.
  - Other people's words in the task and voice-model prompts marked off the same way.
- **Left out:**
  - **Encrypting the vault beyond FileVault.** A key kept in the Keychain can be read by any process running as the user, which is the realistic threat once FileVault is on, and a key that needs the user present would stop the nightly run.
  - **Prompt-injection classifiers.** Llama Prompt Guard's licence isn't open, and it only catches explicit "ignore your instructions".
- **Health data:**
  - **The routes:** Apple Health's export (read today), SMART on FHIR patient apps against providers' certified APIs, insurers' Patient Access APIs (prior-authorization data due by January 2027 under CMS-0057-F), and TEFCA Individual Access Services.
  - **The law:** HIPAA covers providers and insurers, not a person's own tool. A hosted Proxenos would likely fall under the FTC's Health Breach Notification Rule.

### One download, for Mac and Windows

The plan in [everyone.md](everyone.md) holds: an Electron shell around a bundled Python, with the page as a standalone Next.js build.
- **Why not Tauri:** it would still need Node beside it, and adds Rust.
- **What it costs the owner:** the Apple Developer Program ($99 a year) and Microsoft's Artifact Signing ($9.99 a month, for individuals in the US and Canada). The Microsoft Store is a free second route on Windows.
- **Taken:** the Windows blockers in the code are cleared ([apps.md](apps.md)).
- **Next:**
  - The seams the shell needs: the page runs `python -m proxenos` and finds the repo from a setting.
  - The shell itself.
  - Unsigned builds from CI.
  - Signing, once the accounts exist.
