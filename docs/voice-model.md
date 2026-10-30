# A voice model of your own

Proxenos drafts replies with whichever model you set up: Anthropic's with a key, or an open model in Ollama. That model has never read anything you wrote. It gets a description of your voice and your last few messages in the chat, and writes like a model imitating you.

A voice model is the next step. It's a small open model fine-tuned on your own computer on what you've actually sent: your chat replies, emails and posts. Reply drafts then come from a model that has learned how you write. It's free to run, needs no account, and nothing leaves your computer. It's optional and off until you turn it on.

## What you need

- **A Mac with Apple silicon.** Training uses [mlx-lm](https://github.com/ml-explore/mlx-lm), Apple's library for running and fine-tuning models on its own chips.
- **Memory:** 32 GB for the default model, Google's Gemma 4 E4B. With 16 GB, train the smaller E2B instead: `--base mlx-community/gemma-4-e2b-it-4bit`. Qwen3.5 models don't work here: mlx trains their DeltaNet layers one token at a time, which runs out of memory even on short chats.
- **Disk:** about 5 GB for the model's weights (3.6 GB for the E2B), plus a few hundred MB for the training set, the trained adapter and the evaluation.
- **Time:** about a minute to build the training set. Training takes a few hours on an M1 Pro with 32 GB at the default 1000 steps; a newer chip is faster. Evaluating 60 drafts takes minutes for the small model and longer for a big local drafting model. Training uses the GPU flat out, so start it when you won't need the computer.
- **Your data in the vault:** chats (WhatsApp, Messenger, Instagram, LinkedIn, X, Slack), email, and the LinkedIn export. The more you've written, the better. A few thousand of your replies is plenty.

## Steps

```bash
pip install mlx-lm
```

```bash
proxenos voice build
```

This writes the training set into `vault/voice/`. Each example is a conversation as it stood when you answered someone, and what you sent. Your messages sent within 15 minutes of each other count as one answer, one message per line. Only conversations where the other person said something to answer count: a question, a link, or a few words. Your emails that start a thread (from their subject) and your LinkedIn posts are added too. The last five years count, and at most 40 answers from any one conversation, so one long chat doesn't drown the rest. The newest tenth of your conversations is held out for the evaluation and never trained on.

```bash
proxenos voice train
```

This downloads the base model's public weights once and trains a LoRA adapter, a small set of extra weights on top of the model, into `vault/voice/adapter/`. Progress goes to `vault/voice/train.log`.

```bash
proxenos voice eval
```

This drafts 60 of the held-out answers three ways: with the base model untrained, with your voice model, and with the drafting model you use now, given the same prompt reply drafts get, your own last messages in that chat included. Each draft is then scored by how much of it survived into what you actually sent: 1.0 means word for word, near 0 means something else. That's the same measure the Drafts page tracks. A fourth row, your previous message in that chat sent again, shows what a score means on your data. `vault/voice/eval.json` has every draft next to what you sent, so you can read them yourself. After training again, `proxenos voice eval --models tuned` drafts only with the voice model and keeps the other drafts from the last run.

```bash
proxenos voice score essay.md page.html
```

This reads each text paragraph by paragraph and scores how much more likely your voice model finds each paragraph than the base model does, in nats per token. Above 0, it reads more like you than the base model expects; below 0, less. Your own held-out emails and posts are scored the same way for comparison. It lists the paragraphs that read least like you, so you know where to look before you post something. Use `--kind email` for an email.

```bash
proxenos voice serve
```

This serves the voice model on this computer (127.0.0.1:8899) until you stop it. Then set the voice model to `mlx`: `PROXENOS_VOICE_MODEL=mlx` in `.env`, or `{"settings": {"voice_model": "mlx"}}` through `proxenos setup --apply`. A model you've imported into Ollama yourself also works, as `ollama:<name>`.

## What it changes

Only replies. The voice model writes a reply's text from the conversation. Your drafting model still writes the draft's title, what your memory showed that the reply rests on, and the questions only you can answer. It also still writes everything else: emails for tasks, outreach, plans and reading notes. If the voice model isn't running, the drafting model's reply is used and nothing is lost.

A voice model has learned how you write, not what you know. It doesn't see your calendar, your notes or the linked pages a reply's research turns up. Compare its drafts against your drafting model's with `proxenos voice eval` before turning it on, and train it again every few months as your writing changes.

## What stays private

Everything except the base model's public weights, which come from Hugging Face once.
- The training set, the adapter and the evaluation stay in `vault/voice/`, readable only by you.
- Links, email addresses and phone, card and long account numbers are blanked in the training set, as they are before Proxenos's other model calls.
- Training, serving and drafting all run on this computer. The server only listens on 127.0.0.1.
- The adapter has learned from your messages, so treat it like them: don't share it, and delete `vault/voice/` to remove it.

## Later

- **Windows and Linux:** mlx-lm only runs on Apple silicon. The same training set works with LoRA tools for NVIDIA GPUs, and that's the next step there.
- **Android:** running a small model on a phone is possible, but not in Proxenos yet. See [apps.md](apps.md).
- **Learning as you go:** training again each night on the day's sent messages, so the model keeps up without a full retrain.
