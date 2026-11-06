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
  observers) reads it as yours; one you changed more stays yours, and teaches the change, if you read it first: copied it, opened it in its app, edited, approved or kept it. A draft nobody opened, beside what you wrote instead, says only that it missed, so it teaches nothing.
- **Judgment:** how often a draft's "needs from you" questions were the ones you actually had to
  answer, and how often you discarded a draft as wrong rather than unneeded.

Acting on your behalf follows the measurements: where drafts to a person or of a kind have gone
out unchanged many times, sending them can move from your approval to a rule you set, with a log
and a window to undo. Where they haven't, it stays a draft.

## The outbox

The first step from drafting to acting is the outbox ([outbox.py](../src/proxenos/outbox.py)),
set on the Drafts page. It is off until you switch it on, and then only per app, and only for
an app whose replies have earned it on the evidence that matches what it sends. It sends drafts
nobody touched, so what counts is that app's measured reply drafts ([fidelity.py](../src/proxenos/fidelity.py))
you didn't act on: not copied, opened in their app, edited, approved, marked sent, kept or
thought through in Think. It would have sent one whose chat you never answered too, so a draft
like that, left untouched for three days with its chat unanswered, counts as one you'd have
changed; the outbox keeps them in `clones/outbox/unanswered.jsonl`, since the draft itself goes
in time. Of them all, the share whose reply went out nearly unchanged (nine tenths or more of the
draft still in what you sent) must be at least 90% with 95% confidence, the lower bound of its
Wilson interval. With every one unchanged, that takes 35 drafts; the page says how
many your setting needs. You can set the bar between 80% (16 drafts at the least) and 99%, never
lower, where a handful of drafts would do. The replies the outbox sent itself never count, so it can't vouch for
itself. A rules file from before keeps its switches, and its bar on the mean is read as the bar
on the share.

What the record can't see: "untouched" means nothing recorded. Copying a draft by selecting its
text by hand rather than with Copy, or using it from the page on your phone without its buttons
(reading it there and writing it out, say), leaves no record, so that draft counts as untouched,
and one you sent nearly as written would count for the app as if the outbox could have sent it
unseen. Copy, Open and Sent keep the record honest. Until drafts are also held back unseen and
measured, the record is drafts you didn't act on in a way the page recorded, which isn't quite
drafts you never saw.

- **Which replies:** a draft nobody touched, to one person you've written to before (never
  someone new's first email), with no blank left and nothing it asks you, while its chat still
  waits on exactly the messages it answers.
- **Never to a group:** a chat goes only when every record of it says it's with one person
  (WhatsApp's, Messenger's, Instagram's and X's chat type, Beeper's for LinkedIn too, or one name
  on a LinkedIn export's messages), and an email only when the mail it answers came from one
  address to you alone. Where the records don't say, it's held.
- **Nothing from outside the chat:** a reply whose prompt held anything beyond its chat is held:
  what memory's research found, the person's records elsewhere, Care's summary of your health
  care, the facts and "right now" note you told Proxenos, or your calendar's week. The drafting
  code writes which into the draft as it builds the prompt (`drew_on`), so it doesn't rest on
  the model saying what it used; a draft made before Proxenos kept that is held too, and so is
  one whose own "found" says it rested on something. Since the self-model and your own writing
  are in every draft, a backstop holds one that mentions health, or a name or a place (a
  capitalised word that isn't a sentence's first) that the chat and your own messages there
  never had, other than a day, a month and your two names. Most replies to someone with records
  elsewhere are held, then: what can't be shown to come from the chat alone stays a draft.
- **What else holds one back:** a link, an email address, a phone number or a run of six or more
  digits that's in neither the chat nor your own earlier messages there, or, for email, mail
  whose Reply-To isn't its sender (or was read before Proxenos kept Reply-To). A held reply
  stays a draft for you, and the log says why.
- **Signed, if you like:** each app has a "say your assistant sent it" switch, off unless you turn
  it on, which puts "(sent by my assistant)" under what goes out.
- **When:** a reply is queued at one sync and goes out at the next, so you have about fifteen
  minutes to cancel it on the page. At most ten go out a day, or the limit you set.
- **How:** email through the Mail app, as a reply in its thread from the account the mail came
  to (the draft's `from_address`; an errand's or an offer's email records the address it will go
  from the same way, the one of your newest email with that person or `PROXENOS_MAIL_FROM`, and
  Mail stops it if it has no account for that address); Instagram, Messenger, X and LinkedIn, and WhatsApp where Beeper has it, through Beeper
  Desktop. Slack has no way yet.
- **The record:** every attempt, sent or not, is a line in `clones/outbox/log.jsonl`, and a reply
  that goes out is marked sent, as if you'd pressed Sent. Nothing goes out from `proxenos demo`.
- **Done without it:** a draft you sent yourself is noticed (marked sent) from the chat or mail that shows it; one the
  conversation has since moved past is marked overtaken, with why ([fidelity.py](../src/proxenos/fidelity.py)); and an
  errand's message is marked sent, `sent_by: "elsewhere"` with the evidence, when your own outgoing records show you
  wrote to that person after it was made. None of these sends anything.
