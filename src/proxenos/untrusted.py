"""Other people's text in a prompt, marked off so the model reads it as data and never as orders.

A message, a linked page or a record holding someone else's words can say anything, including
"ignore your rules" or a closing tag that ends the block it sits in. So each prompt draws a tag
of its own (`tag`), untrusted- and a random value, and each block of other people's text goes
inside it (`wrap`). Text inside can't close the block, since it would have to guess the value,
and anything in it shaped like such a tag, opening or closing, is defused first anyway. The
system prompt of whatever reads the block says what the tag means.
"""

import re
import secrets

# Anything shaped like the tag, opening or closing, whatever its value.
_LOOKALIKE = re.compile(r"<(\s*/?\s*untrusted)", re.IGNORECASE)


def tag() -> str:
    """A tag for one prompt's blocks: untrusted- and a fresh random value."""
    return f"untrusted-{secrets.token_hex(4)}"


def wrap(text: str, name: str) -> str:
    """`text` inside the tag `name`, with any lookalike of the tag in it defused."""
    return f"<{name}>\n{defuse(text)}\n</{name}>"


def defuse(text: str) -> str:
    """`text` with each "<" that starts something shaped like the tag turned into "‹"."""
    return _LOOKALIKE.sub(r"‹\1", text)
