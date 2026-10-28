# Tracker and web page

Goal: a page you keep open while you work. Every few hours it shows new things worth your attention, picked the way you'd pick them. It learns from what you open, save, or dismiss.

## The loop (every ~3 hours while the Mac is awake)

1. **Fetch candidates.** All sources are public:
   - **Papers:** arXiv listings for your categories, new OpenAlex works for followed concepts and authors, bioRxiv.
   - **News and blogs:** RSS feeds from a list in the vault. Seed the list from the domains you actually share on WhatsApp. Add newsletters you open or reply to.
   - **Hacker News:** front page plus topic search.
2. **Rank.** An LLM reads `self/interests.md`, `self/taste.md` and recent feedback. It scores each candidate: relevance, one line on why it matters to *you*, and which interest it hits. Keep ~20% of slots for exploration (adjacent or contrarian material) so the feed doesn't harden into a bubble.
3. **Store** in `$PROXENOS_VAULT/tracker/items/<date>.jsonl`, deduplicated by URL.
4. **React.** On the page you mark items useful, not-me, or save. Opening an item is logged too. Feedback goes to `$PROXENOS_VAULT/tracker/feedback.jsonl`. This is the "morning reaction" signal from the landscape doc, at a few-hours cadence. It scores Proxenos's predictions and feeds the next profile update.

## The page

- **Stack and look:**
  - Next.js + Tailwind v4 + lucide icons, Outfit font
  - the yellow-on-cream palette (`#FFC629` on `#FFF9E5`)
  - left sidebar nav
  - center feed with a sticky blurred header and a tab toggle
  - rounded-xl cards, with papers in the citation-card style
- **Local only.** It runs on localhost and reads and writes the vault through server-side API routes. It's never deployed, and there's no Supabase: that would put private data in the cloud. The code lives in `web/` in this repo. The data never does.
- **Views:**
  - **Feed:** new items, refreshed when a batch lands.
  - **Saved.**
  - **Profile:** what it currently thinks your interests are. This view is editable, so you can correct it directly.
  - **Status:** when each source last synced.

## Where it runs

A launchd job runs `proxenos ingest` for each source, then `proxenos clone tracker`, every ~3 hours. A closed laptop means no run; it catches up next time.

## Before building

1. **Pick the LLM for profiling and ranking.**
   - Claude API key: pay per token, clean to call from Python.
   - Claude Code headless (`claude -p`): runs on your existing subscription with no key, but gives less control.
   - A local model keeps everything on the Mac but ranks worse.
2. **Build the first profile** (`self/interests.md`, `self/taste.md`) from your reading library, your side of WhatsApp, and an interview. Ranking needs it.
3. **Limit what the LLM sees.** Ranking sends the distilled profile plus public items. Building the profile sends your own messages, so send only your side of conversations, not other people's.
