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
