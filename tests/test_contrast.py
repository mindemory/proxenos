"""The page's colour tokens against WCAG 2.2 AA, read from web/src/app/globals.css: each text
colour on the grounds it's used on at 4.5:1, and what has to be seen to be used (control
borders, the graph's relations and clusters) at 3:1, in the dark and light themes and with more
contrast in each. The dark set's control borders and hairlines are quiet by design (about 1.6:1)
and stay as they were; more contrast takes them to 3:1, so only the other sets are held to it."""

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[1] / "web" / "src" / "app" / "globals.css"

SETS = {
    "dark": ":root,\n.dark-ground {",
    "light": ':root[data-theme="light"] {',
    "dark, more contrast": ':root[data-contrast="more"]:not([data-theme="light"]),\n'
    ':root[data-contrast="more"] .dark-ground {',
    "light, more contrast": ':root[data-theme="light"][data-contrast="more"] {',
}

TEXT = [
    ("ink", "bg"),
    ("ink", "surface"),
    ("ink", "surface-2"),
    ("muted", "bg"),
    ("muted", "surface"),
    ("muted", "surface-2"),
    ("faint", "bg"),
    ("faint", "surface"),
    ("accent", "bg"),
    ("accent", "surface"),
    ("accent-ink", "accent"),
    *[(f"{s}-ink", g) for s in ("ok", "warn", "bad") for g in (f"{s}-bg", "bg", "surface")],
    ("bg", "bad-ink"),  # a destructive button: the ground's colour on bad-ink
]

SEEN = [
    *[(f"rel-{r}", "bg") for r in ("met", "know", "read")],
    *[(f"cluster-{c}", "bg") for c in ("1", "2", "3", "4", "other", "none")],
]

BORDERS = [("line-strong", "bg"), ("line-strong", "surface")]


def tokens(header: str) -> dict[str, str]:
    """The --c-* colours one block of globals.css sets."""
    text = CSS.read_text()
    start = text.index(header) + len(header)
    block = text[start : text.index("\n}", start)]
    return dict(re.findall(r"--c-([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_ratio_matches_wcags_own_examples():
    assert ratio("#000000", "#ffffff") == pytest.approx(21)
    assert ratio("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


@pytest.mark.parametrize("name", SETS)
def test_every_set_names_every_colour(name):
    # So none of them leans on another's colour for a ground it was never checked on.
    assert len(tokens(SETS["dark"])) == 29
    assert set(tokens(SETS[name])) == set(tokens(SETS["dark"]))


@pytest.mark.parametrize("name", SETS)
def test_text_reaches_aa_on_every_ground_it_is_used_on(name):
    c = tokens(SETS[name])
    low = [
        f"{fg} on {bg}: {ratio(c[fg], c[bg]):.2f}" for fg, bg in TEXT if ratio(c[fg], c[bg]) < 4.5
    ]
    assert low == []


@pytest.mark.parametrize("name", SETS)
def test_what_has_to_be_seen_reaches_three_to_one(name):
    c = tokens(SETS[name])
    pairs = SEEN + (BORDERS if name != "dark" else [])
    low = [
        f"{fg} on {bg}: {ratio(c[fg], c[bg]):.2f}" for fg, bg in pairs if ratio(c[fg], c[bg]) < 3
    ]
    assert low == []


@pytest.mark.parametrize("name", ["dark, more contrast", "light, more contrast"])
def test_more_contrast_also_draws_hairlines_at_three_to_one(name):
    c = tokens(SETS[name])
    assert ratio(c["line"], c["surface"]) >= 3 and ratio(c["line"], c["bg"]) >= 3
