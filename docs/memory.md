# Memory, and how far the twin should be from you

Proxenos's model remembers nothing between calls. Everything it knows about you for a task is
put in front of it, in code, from the vault. So memory here is two questions: what to keep, and
what to bring to mind for the task at hand. A third question sits on top: how close to you the
twin should act.

## What two lines of research suggest

**Separate lookup from thinking.** DeepSeek's Engram ("Conditional Memory via Scalable Lookup",
January 2026) gives a language model a second kind of capacity next to its reasoning: a large
table of remembered patterns looked up in constant time, and a gate, driven by the current
context, that lets a retrieved memory in only when it fits and suppresses it when it conflicts.
Moving part of a model's parameters from reasoning into lookup made it better at both knowledge
and reasoning. The lesson for Proxenos is the same split at a larger scale: the vault and its
indexes are the lookup, the model is the reasoning, and something must gate what gets from one
to the other.

**Keep what surprises, let the rest fade.** Titans ("Learning to Memorize at Test Time", Behrouz and others at
Google, December 2024) adds a long-term memory that keeps learning while the model runs. It writes most where the
input is most surprising, carries surprise forward for a while (momentum), and decays what isn't
reinforced. The lesson: relevance isn't a fixed property of a record. It is how unexpected the
record was when it came in, how recent it is, and whether it keeps being useful.

Neither needs training a model of our own. Both describe how to choose what an ordinary model is
shown.

## The layers

| Layer | In Proxenos | Like |
|---|---|---|
| Everything that happened | `vault/raw/`, every message, mail, note and event, never deleted | episodic memory |
| Cues | the word index (`index.sqlite`) and the meaning index (`vectors.sqlite`) | recall by cue |
| What it means about you | monthly observations, consolidated into the self-model (`self/`) | semantic memory, made during sleep (`proxenos night`) |
| What's open | tasks, care's open items, chats waiting on you, deadlines | prospective memory |
| What's in mind now | the prompt for one task: the chat, the person, the matter, the self-model | working memory |

Nothing is forgotten from the first layer. Forgetting happens in the later ones: what is
consolidated, what is indexed for the last year, what is brought into a prompt.

## What gets brought to mind

For a reply today ([research.py](../src/proxenos/research.py)):
1. the person: who they are to you, and your newest records with them on any channel;
2. the matter: the model asks for what the reply depends on, and each question is searched by
   meaning, then by words, anywhere and among that person's records.

What it should add, in order:
- **A gate.** After retrieval, the model marks each record relevant or not before drafting, and
  only the relevant ones are kept, as Engram's gate does. That stops a long prompt of near misses
  from drowning the one letter that matters.
- **Salience.** Each record scored as it comes in: deadlines, money, health, promises and
  questions to you score high; routine and bulk mail low. Ties are broken by recency, with a slow
  decay, and by use: a record that went into a draft you sent counts for more next time. This is
  Titans' surprise, momentum and decay, done with counts instead of gradients.
- **Open loops.** A promise you made ("I'll check the deadline and get back") or a question left
  unanswered is kept in mind until it's closed, and comes up whenever that person or matter does.

## How far the twin is from you

The twin should be you in what you value, know and sound like, and not you in what limits you on
a bad day: it doesn't forget, doesn't get tired, checks the deadline before answering, and works
on several things at once. It should be more careful than you, not bolder: it decides nothing that
is yours to decide, and says what it would need to.

That distance can be measured, so it doesn't rest on impressions:
- **Voice:** how much of each draft you change before sending. Proxenos sees the draft and, at the
  next sync, what you actually sent in that chat, so it can score how close it came, per person
  and per kind of message.
- **Judgment:** how often a draft's "needs from you" questions were the ones you actually had to
  answer, and how often you discarded a draft as wrong rather than unneeded.

Acting on your behalf follows the measurements: where drafts to a person or of a kind have gone
out unchanged many times, sending them can move from your approval to a rule you set, with a log
and a window to undo. Where they haven't, it stays a draft.
