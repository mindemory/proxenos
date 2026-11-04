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
   meaning and by words, anywhere and among that person's records. When the chat points to a
   time ("around the March conference", "last week"), the model also gives the first and last
   day to look in, and every search keeps to them. LongMemEval (Wu and others, ICLR 2025) found
   that this finds more for questions about time. Dates that aren't real are dropped, and two in
   the wrong order are swapped.
3. one list from many: the searches' lists are fused by reciprocal rank (Cormack, Clarke and
   Buettcher, SIGIR 2009). A record scores 1 / (60 + its rank) in each list it is in, summed, so
   one that several searches rank high comes first. Each search's best always stays in.
4. opening what was found: each record found has a number, and a round may open up to three of
   them. An opened record comes back with the three records before and after it in its chat or
   thread, or its fuller text, about 2,000 characters in all. The next round reads it, so there
   are up to three rounds. A snippet often isn't enough: "due by the 7th" says little without
   the question before it. In LongMemEval-V2 (May 2026), agents that searched the stored records
   and opened what they found scored 69 to 72 percent, against 48.5 for the best that only
   retrieved. In Letta's LoCoMo run (August 2025), search and open beat Mem0.
5. a gate: the model marks each record found as needed or a near miss, and only the needed ones
   reach the draft, as Engram's gate does. That stops a long prompt of near misses from drowning
   the one letter that matters. A kept record that was opened brings the record before and after
   it: a few lines, not the whole thread.

What research finds and opens holds other people's words. It goes to the model inside a tag for
them ([untrusted.py](../src/proxenos/untrusted.py)), in research's own prompts and in the draft's.

Each reply's research leaves one line in `memory/research.jsonl`: the searches' words and days,
each list's ids in rank order, the fused order, the ids opened and the ids the gate kept. Ids
only, never what a record says. It is there to tune the searches and the gate. Past 20 MB, its
older half goes.

For today, with nothing asked ([recall.py](../src/proxenos/clones/recall.py)): each coming event,
open task and feed item brings up past records about it. Its title is searched by words and,
when the embedding model runs, by meaning, which finds a record that says the same thing in
other words. The two lists are fused the same way. A record found by words must clear a bm25
bar, and one found by meaning a similarity bar, so a trigger with nothing close brings up nothing.

What it should add, in order:
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
  and per kind of message. Closeness is the share of the draft still in what you sent: Python's
  difflib ratio (Ratcliff/Obershelp) on the words in lower case, the draft first and what you
  sent second, without difflib's autojunk, which would score a text of 200 characters or more
  by another rule than a short chat. The draft is the model's text as you last saw it before
  you acted on it: an edit on the Drafts page writes your text over the draft, so what the edit
  replaced (kept with it in `clones/drafts/feedback.jsonl`) is scored, and a rewrite Think made
  at your asking counts as the model's. A draft edited before the page kept what an edit
  replaced has no score, rather than your edit scored against itself. Each sync measures every
  draft again, and a comparison round's scores are worked out again from its texts whenever
  it's read, so every score follows the measure as it is now. A draft you send nearly
  unchanged (closeness 0.9 or more)
  comes back as your own message, but its words are the model's, so nothing that learns how you
  write (the examples a draft is shown, the checks on writing rules, the voice model, the
  observers) reads it as yours; one you changed more stays yours, and teaches the change.
- **Judgment:** how often a draft's "needs from you" questions were the ones you actually had to
  answer, and how often you discarded a draft as wrong rather than unneeded.

Acting on your behalf follows the measurements: where drafts to a person or of a kind have gone
out unchanged many times, sending them can move from your approval to a rule you set, with a log
and a window to undo. Where they haven't, it stays a draft.

## The outbox

The first step from drafting to acting is the outbox ([outbox.py](../src/proxenos/outbox.py)),
set on the Drafts page. It is off until you switch it on, and then only per app, and only for
an app whose replies have earned it: by default at least five measured, and on average nine
tenths of each draft still in what you sent ([fidelity.py](../src/proxenos/fidelity.py)).

- **Which replies:** a draft nobody touched, to one person (never a group) you've written to
  before (never someone new's first email), with no blank left and nothing it asks you, while
  its chat still waits on exactly the messages it answers.
- **What holds one back:** a link, an email address, a phone number or a run of six or more
  digits that's in neither the chat nor your own earlier messages there, or, for email, mail
  whose Reply-To isn't its sender (or was read before Proxenos kept Reply-To). A held reply
  stays a draft for you, and the log says why.
- **When:** a reply is queued at one sync and goes out at the next, so you have about fifteen
  minutes to cancel it on the page. At most ten go out a day, or the limit you set.
- **How:** email through the Mail app, as a reply in its thread from the account the mail came
  to; Instagram, Messenger, X and LinkedIn, and WhatsApp where Beeper has it, through Beeper
  Desktop. Slack has no way yet.
- **The record:** every attempt, sent or not, is a line in `clones/outbox/log.jsonl`, and a reply
  that goes out is marked sent, as if you'd pressed Sent. Nothing goes out from `proxenos demo`.
