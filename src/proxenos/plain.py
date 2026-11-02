"""Plain language, asked of every clone that writes something for the user to read.

Proxenos was built first for people getting through the health care system, often while unwell
or tired, and some of them find reading hard: low vision, dyslexia, low health literacy.
So what a clone writes for the user to read (care's summary, timeline and open items, the
journal's brief, the advisor's suggestions) is asked for in plain language, as health
communicators write it:

- the most important thing first: the CDC Clear Communication Index's first items are one main
  message, at the top;
- short sentences and common words, about a sixth-grade reading level: AHRQ's Health Literacy
  Universal Precautions Toolkit puts patient materials at a fifth- to sixth-grade level, and the
  Federal Plain Language Guidelines ask for short sentences, everyday words and the active voice;
- a medical or insurance term explained in plain words the first time it comes, as both ask.

It changes how things are said, never what: explaining what a word means isn't saying what it
means for the user, so each clone's own rules (care restates the records, never diagnoses or
advises) still hold, and RULES says so too. What goes out as the user's own words (care's
scripts, every draft) is written as they write instead (proxenos.voice).
"""

RULES = """\
Write {what} in plain language, for someone who may be unwell or tired, or find reading hard:
- The most important thing first.
- Short sentences, one idea each: about 15 words, rarely more than 20. Common, everyday words, \
at about a sixth-grade reading level, and the active voice.
- The first time a medical, insurance or billing term comes up, say what it means in a few \
plain words right after it, as in "a referral (a note from one doctor sending you to \
another)". After that, the term alone. The same for an abbreviation: "an MRI (a detailed scan)".
- Explain what a word means in general, never what it means for {person}: no reading of a \
result, no guess at a cause, no advice the rest of these instructions don't ask for."""


def rules(person: str, what: str) -> str:
    """RULES for `what` a prompt asks for ("the summary and the open items")."""
    return RULES.format(person=person, what=what)
