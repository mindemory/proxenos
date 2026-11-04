# Acknowledgments

Proxenos is built on other people's open-source work and open data. Thank you to everyone behind these. Each keeps its own licence; Proxenos's own code is [MIT](LICENSE).

If you add code or data from another project, keep its licence and copyright notice with it, and add it here. Prefer permissive licences (MIT, BSD, Apache-2.0, CC0, CC-BY). Copyleft code (GPL, AGPL, SSPL, BUSL) needs a decision first, since it would change what others may do with Proxenos.

## The page

| Project | Licence | Used for |
|---|---|---|
| [Next.js](https://github.com/vercel/next.js) | MIT | The local page and its API routes |
| [React](https://github.com/facebook/react) | MIT | The page's interface |
| [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss) | MIT | Styling |
| [Lucide](https://github.com/lucide-icons/lucide) | ISC | Icons |
| [clsx](https://github.com/lukeed/clsx), [tailwind-merge](https://github.com/dcastil/tailwind-merge) | MIT | Class names |
| [node-qrcode](https://github.com/soldair/node-qrcode) | MIT | The QR code that opens the page on a phone |
| [Atkinson Hyperlegible Next](https://github.com/googlefonts/atkinson-hyperlegible-next) and [Atkinson Hyperlegible Mono](https://github.com/googlefonts/atkinson-hyperlegible-next-mono), from the Braille Institute: Copyright 2020-2024 The Atkinson Hyperlegible Next Project Authors | SIL Open Font License 1.1 | The Hyperlegible typeface in Settings, Reading, served with the page through `next/font` and never fetched from Google by the browser |
| [TypeScript](https://github.com/microsoft/TypeScript), [ESLint](https://github.com/eslint/eslint), [eslint-plugin-jsx-a11y](https://github.com/jsx-eslint/eslint-plugin-jsx-a11y) | Apache-2.0, MIT, MIT | Checks, the page's accessibility rules among them |

## The Python package

| Project | Licence | Used for |
|---|---|---|
| [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) | MIT | A hosted model, when you choose one |
| [NumPy](https://github.com/numpy/numpy) | BSD-3-Clause | The memory's vector search |
| [pypdf](https://github.com/py-pdf/pypdf) | BSD-3-Clause | Reading PDFs |
| [pdfminer.six](https://github.com/pdfminer/pdfminer.six) | MIT | Where a PDF form's labels and lines sit, to fill it |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | BSD-3-Clause | Reading `.env` when running from source |
| [keyring](https://github.com/jaraco/keyring) | MIT | Secrets on Windows and Linux |
| [VADER](https://github.com/cjhutto/vaderSentiment) (vaderSentiment), by C.J. Hutto: Hutto and Gilbert, "VADER: A Parsimonious Rule-based Model for Sentiment Analysis of Social Media Text", ICWSM 2014 | MIT | The mood of your own writing a day at a time, on this computer, for Rhythms' month cards |
| [pytest](https://github.com/pytest-dev/pytest), [Ruff](https://github.com/astral-sh/ruff) | MIT | Tests and lint |

## Tools and services it works with

| Project | Licence | Used for |
|---|---|---|
| [Ollama](https://github.com/ollama/ollama) | MIT | Running an open model on your own computer |
| [Gemma](https://ai.google.dev/gemma), [Qwen](https://github.com/QwenLM) | Each model's own licence | The default local models for drafting and for search by meaning, pulled through Ollama, not shipped here |
| [mlx-lm](https://github.com/ml-explore/mlx-lm) | MIT | Training the optional voice model on a Mac ([docs/voice-model.md](docs/voice-model.md)) |
| [mlx-audio](https://github.com/Blaizzy/mlx-audio), by Prince Canuma | MIT | Listen's natural voice and your own, made on a Mac with Apple silicon (`proxenos.speech`, the optional `speech` extra) |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), by hexgrad, as converted by [mlx-community](https://huggingface.co/mlx-community/Kokoro-82M-bf16) | Apache-2.0 (code and weights) | Listen's natural voice. Its weights are downloaded once from Hugging Face when you ask, not shipped here |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), by the Qwen team at Alibaba, as converted by [mlx-community](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit) | Apache-2.0 (code and weights) | Listen in your own voice, from a clip of you reading. Its weights are downloaded once when you ask, not shipped here |
| [misaki](https://github.com/hexgrad/misaki), [spaCy](https://github.com/explosion/spaCy) and its [en_core_web_sm](https://github.com/explosion/spacy-models) model, [num2words](https://github.com/savoirfairelinux/num2words) | Apache-2.0, MIT, MIT, LGPL-2.1 | Reading English text as sounds for Kokoro |
| [espeak-ng](https://github.com/espeak-ng/espeak-ng), through [phonemizer-fork](https://pypi.org/project/phonemizer-fork/) and [espeakng-loader](https://github.com/thewh1teagle/espeakng-loader), which carries espeak-ng's library | GPL-3.0 (espeak-ng, phonemizer-fork), MIT (espeakng-loader's own code) | Sounding out words not in misaki's dictionary, such as a medicine's name. Installed into the env by the `speech` extra and used as a library from there; not included in Proxenos or the desktop app. Kept there by decision (November 2026): without it those words go unsaid |
| [slackdump](https://github.com/rusq/slackdump) | AGPL-3.0 | Reading Slack. Run as a separate program, not included in Proxenos |
| [Beeper Desktop API](https://www.beeper.com) | Beeper's terms | Instagram, Messenger, X and LinkedIn chats |
| [OpenAlex](https://openalex.org) | CC0 data | Papers and mentions, and checking a paper's references by title |
| [Crossref](https://www.crossref.org)'s REST API | Open metadata, no restrictions on reuse | Checking a paper's references by DOI and title (`proxenos preprint refs`) |
| [DataCite](https://datacite.org)'s REST API | CC0 metadata | Checking a reference whose DOI Crossref doesn't hold, such as software or data |
| [arXiv](https://arxiv.org)'s API | CC0 metadata | The research feed, and checking a reference by its arXiv id. Thank you to arXiv for use of its open access interoperability |
| [MusicBrainz](https://musicbrainz.org), from the MetaBrainz Foundation | CC0 core data; tags and genres CC BY-NC-SA 3.0 | Kinds of music for Rhythms, looked up by artist name and kept in your vault for your own use, never shipped here |
| [Tailscale](https://tailscale.com) | BSD-3-Clause client | Reaching the page from your own phone |
| [Pillow](https://github.com/python-pillow/Pillow), [Zopfli](https://github.com/google/zopfli) | MIT-CMU, Apache-2.0 | Shrinking the README's pictures |

## Ideas and inspiration

| Project | Licence | What it gave |
|---|---|---|
| [XERJ](https://github.com/xerj-org/xerj) | Apache-2.0 | Proxenos is a corpus on the XERJ Corpus Hub, the open reference memory AI coding agents search before they write code; `AGENTS.md` and `llms.txt` follow that idea |
| [Synthea](https://github.com/synthetichealth/synthea) | Apache-2.0 | The shape of the synthetic health records used in tests |
| [arxiv_latex_cleaner](https://github.com/google-research/arxiv-latex-cleaner), from Google Research | Apache-2.0 | What a paper's source for arXiv should leave out: its comments, and files it doesn't use. Only the idea: `proxenos/preprint.py` is written anew and holds none of its code |
| [Odysseus](https://github.com/odysseus-dev/odysseus) | AGPL-3.0 | The idea of pushing a notice to the phone through ntfy when something waits on you. Only the idea: `proxenos/notify.py` is written anew and holds none of its code or text |
