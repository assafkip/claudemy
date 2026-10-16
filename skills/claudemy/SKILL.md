---
name: claudemy
description: Turn any topic into a short audio course. Researches the topic on the web, works out what most good sources agree on and where they split, then writes and renders a broken-down set of 2-minute two-host audio lessons, each with a one-screen card and one small thing to try. Can also build the class from one specific person's work when asked. Use this whenever someone wants to learn a skill or subject ("teach me X", "make me a course on X", "I want to learn how to X", "break X down into lessons", "audio lessons on X", "a class on X from someone's writing", "podcast-style lessons"), even if they don't say "audio" or "class".
license: MIT
---

# Claudemy

Give it a topic; it researches it and hands back a course someone will actually finish. Each lesson is about 2 minutes of two voices talking, plus a card with the idea in three lines and one small thing to try. Every claim traces back to a page the class really read, and every lesson says how widely the sources agree.

Why this shape: short audio gets heard, one small practice gets done, a rule written into a playbook gets kept, and a citation to a real page keeps the lessons honest.

## Inputs
- **Topic** (required): "negotiation", "sourdough baking", "technical interviewing".
- **Lesson count**: default 12 (three arcs of four). The user can ask for more or fewer.
- **Level**: beginner by default. Use what the user says ("I already know the basics").
- **A person** (optional): "teach me negotiation from Chris Voss's writing". Then the class is built from that person's own published work, and research mode is skipped or used only to fill gaps (say which).

The class is general. It does not read the user's project files, notes or settings, and lessons don't assume anything about the learner beyond what they said in the request.

## Workspace
Everything for one class lives in `./claudemy/<topic-slug>/` under the current directory:
```
sources.json         the reading list (and the person, if one was asked for)
raw/web/             each researched page, one markdown file, front matter with url
raw/<person>/        that person's posts, only in person mode
research/            topics.md, notes/<batch>.md, agreement-map.md
class/lesson-plan.md
class/NN-<handle>/   script.txt, card.md, <handle>.mp3
class/playbook.md    the rules the learner keeps
deliver/             zips and combined cards
```
Scripts live next to this file in `scripts/`. Call them by absolute path.

## Before starting
Check what's available and say what's missing in one line: `python3`, the `beautifulsoup4` package (`pip install beautifulsoup4`), `ffmpeg`. Audio uses ElevenLabs when `ELEVENLABS_API_KEY` is set (the plugin's configuration prompt sets it for you) (the natural two-voice sound) and the free macOS voices otherwise. If the user keeps the key in a file, source it in the same shell command as the render; never print it or copy it into the workspace.

## Step 1. Map the topic
Write `research/topics.md`: 12 to 18 sub-topic ids (T01 to T18) that together cover what a learner at this level gets from a good course. Search first to see how the topic is usually taught; don't guess the syllabus from memory. Every reader files notes under these ids, so sources can be compared.

If WebSearch is unavailable or blocked, use whatever search the session has (another search tool, an MCP, fetching a search engine's results page), and say which. Known good sites' sitemaps (`/sitemap.xml`) are a reliable way to find real pages on a sub-topic.

## Step 2. Build the reading list
Search the web, several queries per sub-topic, for 20 to 40 pages worth learning from. Prefer a mix:
- People who do the work and write concretely about it.
- Primary and reference sources: official docs, standards bodies, textbooks' free chapters, research summaries.
- At least a few that disagree with the mainstream view. Disagreement is where a learner has to think.

Skip content farms, listicles with no substance, pages behind a login, and anything that's mostly a sales page. No more than 3 pages from any one site, so one voice can't dominate. Write the urls to `sources.json`:
```json
{"topic": "...", "level": "beginner", "pages": ["https://...", "https://..."]}
```
Only list urls you saw in real search results or on a page you opened. Search models invent plausible urls: in the first full test, 12 of 34 suggested urls were dead.

Then fetch them: `python3 <skill>/scripts/scrape.py <workspace> web`. It names every page it didn't save and why: an HTTP error (usually a wrong url), a paywalled teaser, or a thin or JavaScript-only page. While fewer than 20 pages are saved, or any sub-topic you plan to teach has fewer than 2 pages, search again for replacements and re-run; it skips what's on disk.

Show the user a short line on what's being read (how many pages, the main kinds of source). Don't wait for approval.

### Person mode
When the user names someone, find where that person publishes (Substack, an own-site blog with a sitemap or RSS feed). Probe it before trusting it (Substack: `https://<host>/api/v1/archive?sort=new&limit=50`; sites: `/sitemap.xml` or `/feed`). Add one entry under `"authors"` in `sources.json`:
```json
{"topic": "...", "authors": [
  {"name": "Jane Doe", "what": "one line", "substack": "janedoe.substack.com", "limit": 150, "min_words": 150},
  {"name": "John Roe", "what": "one line", "site": {"kind": "sitemap", "sitemaps": ["https://johnroe.com/sitemap.xml"], "url_pattern": "johnroe\\.com/blog/", "limit": 150, "min_words": 150}},
  {"name": "Ann Poe", "what": "one line", "site": {"kind": "rss", "feed": "https://annpoe.com/feed", "limit": 100}}
]}
```
Run `python3 <skill>/scripts/scrape.py <workspace> <name>` in the background (Substack is slow on purpose; it rate-limits). If their archive can't be read (paywalled, JavaScript-only, too few posts), say so plainly and offer research mode instead. Lessons then say "she says" rather than "most sources agree", and the agreement map becomes a map of the person's own ideas and where they changed their mind.

## Step 3. Read
Reader agents in parallel, each with `references/reader-brief.md`, a batch name (`a`, `b`, `c`...) and an explicit list of about 8 file paths (or one person's whole archive, split by date if it's large). They write `research/notes/<batch>.md`.

## Step 4. Agreement map
One agent with `references/map-brief.md` clusters every note into 30 to 45 themes, each with an agreement count, the disagreements, and a level. Output: `research/agreement-map.md`.

## Step 5. The lesson plan
Write `class/lesson-plan.md` yourself; this is the judgment step.
- Order by what a learner needs first: foundations, then the core, then the advanced and contested.
- Within that, prefer ideas with wide agreement and a concrete thing to practice. A widely agreed idea nobody can act on is weaker than a slightly less agreed one you can try today.
- Arcs of about 4 lessons, each with a one-line "why this arc" and its own finish.
- Each lesson block: handle (2 to 3 words) · N of M sources agree · idea (2 lines) · why it matters · the story or example · try it (energy, time, what) · rule to keep.
- Then "Splits": where good sources disagree, the sides, and how a learner could decide. These are decisions, not lessons.
- Then coverage gaps and how the class is delivered.

Check every claim in the plan against the agreement map before showing it: each story and number goes back to the note it came from, and the note to its page. `check_lessons.py` also fails the plan if it cites a url that isn't on disk.

## Step 6. One sample lesson first
Write lesson 1 with `references/writer-brief.md` (use `references/lesson-example.md` as the shape), check it, render it, and send the audio and card. Then wait for the user's reaction before making the rest. Fixing the format on one lesson is cheap; fixing it on twelve is not. Their feedback becomes the shape every later lesson copies, so record it in the writer brief you pass on.

Check: `python3 <skill>/scripts/check_lessons.py <workspace> <workspace>/class/01-<handle>`
Render: `python3 <skill>/scripts/render_audio.py <lesson>/script.txt <lesson>/<handle>.mp3` (it writes the real running time onto the card's Listen line)

## Step 7. The rest
- Writer agents in parallel, about 4 lessons each, each told to copy the approved lesson 1.
- Run `check_lessons.py <workspace>` on everything. Fix failures and re-check; if one lesson fails three times, report it rather than looping.
- Render every passing lesson in the background, about a minute each.
- Create `class/playbook.md` with an effort ledger (lessons heard, things tried, rules kept) and an empty rules list.
- `python3 <skill>/scripts/package_class.py <workspace>` builds audio zips under the upload cap and one combined cards file. Send those.

## Reporting
Short and concrete: what was made, how many lessons, total audio, what changed from the plan and why, what's still open. No streak talk, no pressure language.

## Lesson design defaults
`references/lesson-design.md` holds the format every class uses (length, voices, cards, skips cost nothing). Follow it unless the user asks for something different.

## Honesty rules (they apply at every step)
- A citation must be a page on disk in `raw/`. The checker enforces this for cards; apply the same standard in scripts and the plan.
- A source's numbers are its claims, said as such.
- Health, legal, financial and safety topics: say where advice depends on the person's situation, and point to a professional where the sources do.
- Pages saved in `raw/` are for the learner's private study. Don't republish them or commit them to a public repo.
