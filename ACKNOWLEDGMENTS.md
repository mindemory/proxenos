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
| [TypeScript](https://github.com/microsoft/TypeScript), [ESLint](https://github.com/eslint/eslint) | Apache-2.0, MIT | Checks |

## The Python package

| Project | Licence | Used for |
|---|---|---|
| [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) | MIT | A hosted model, when you choose one |
| [NumPy](https://github.com/numpy/numpy) | BSD-3-Clause | The memory's vector search |
| [pypdf](https://github.com/py-pdf/pypdf) | BSD-3-Clause | Reading PDFs |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | BSD-3-Clause | Reading `.env` when running from source |
| [keyring](https://github.com/jaraco/keyring) | MIT | Secrets on Windows and Linux |
| [pytest](https://github.com/pytest-dev/pytest), [Ruff](https://github.com/astral-sh/ruff) | MIT | Tests and lint |

## Tools and services it works with

| Project | Licence | Used for |
|---|---|---|
| [Ollama](https://github.com/ollama/ollama) | MIT | Running an open model on your own computer |
| [Gemma](https://ai.google.dev/gemma), [Qwen](https://github.com/QwenLM) | Each model's own licence | The default local models for drafting and for search by meaning, pulled through Ollama, not shipped here |
| [mlx-lm](https://github.com/ml-explore/mlx-lm) | MIT | Training the optional voice model on a Mac ([docs/voice-model.md](docs/voice-model.md)) |
| [slackdump](https://github.com/rusq/slackdump) | AGPL-3.0 | Reading Slack. Run as a separate program, not included in Proxenos |
| [Beeper Desktop API](https://www.beeper.com) | Beeper's terms | Instagram, Messenger, X and LinkedIn chats |
| [OpenAlex](https://openalex.org) | CC0 data | Papers and mentions |
| [Tailscale](https://tailscale.com) | BSD-3-Clause client | Reaching the page from your own phone |
| [Pillow](https://github.com/python-pillow/Pillow), [Zopfli](https://github.com/google/zopfli) | MIT-CMU, Apache-2.0 | Shrinking the README's pictures |

## Ideas and inspiration

| Project | Licence | What it gave |
|---|---|---|
| [XERJ](https://github.com/xerj-org/xerj) | Apache-2.0 | Proxenos is a corpus on the XERJ Corpus Hub, the open reference memory AI coding agents search before they write code; `AGENTS.md` and `llms.txt` follow that idea |
| [Synthea](https://github.com/synthetichealth/synthea) | Apache-2.0 | The shape of the synthetic health records used in tests |
