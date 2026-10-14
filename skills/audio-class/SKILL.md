---
name: audio-class
description: Turn any topic into a personal audio course. Finds the practitioners who write best on the topic, scrapes their posts, extracts cited lessons, maps where the authors agree and disagree, then writes and renders short two-host audio lessons, each with a one-screen card and one real action tied to the user's own project. Use this whenever someone wants to learn a skill or subject from experts' writing ("teach me X", "make me a course on X", "I want to learn how to X", "turn these newsletters into lessons", "audio lesson plan", "study plan from these authors", "podcast-style lessons"), even if they don't say "audio" or "class".
---

# Audio class

Give it a topic; it builds a course the learner will actually finish. Each lesson is about 2 minutes of two voices talking, a card with the idea in three lines, and one action in the learner's real work, drafted in advance. Every claim traces back to a scraped post, and every lesson says how many of the authors agree.

Why this shape: a course fails when it's a reading assignment that never touches real work. Short audio gets heard, a drafted action gets done, a rule written into a playbook gets kept, and a citation to a real post keeps the lessons honest.

## Inputs
- **Topic** (required): "pricing for consultants", "negotiation", "technical interviewing".
- **Lesson count**: default 12 (three arcs of four). The user can ask for more or fewer.
- **Authors**: optional names to include. The skill finds the rest.
- **Apply to**: by default, the project the session is open in. If the folder has nothing to read, lessons get general actions instead.

## Workspace
Everything for one class lives in `./audio-class/<topic-slug>/` in the current project:
```
sources.json         who we read, and how to fetch them
raw/<author>/        scraped posts, one markdown file each, front matter with url
research/            topics.md, context-brief.md, learner-profile.md, lessons/<author>.md, agreement-map.md
class/lesson-plan.md
class/NN-<handle>/   script.txt, card.md, <handle>.mp3
class/playbook.md    the rules the learner keeps
deliver/             zips and combined cards
```
Scripts live next to this file in `scripts/`. Call them by absolute path.

## Before starting
Check what's available and say what's missing in one line: `python3`, the `beautifulsoup4` package (`pip install beautifulsoup4`), `ffmpeg`. Audio uses ElevenLabs when `ELEVENLABS_API_KEY` is set (the natural two-voice sound) and the free macOS voices otherwise. If the user keeps the key in a file, source it in the same shell command as the render; never print it or copy it into the workspace.

## Step 1. Find the authors
Search the web for practitioners who write regularly and concretely about the topic. You want people who do the work, with a readable archive:
- Substack is easiest (`<name>.substack.com`; the archive API returns everything free).
- Own-site blogs work through a sitemap or an RSS feed.
- Aim for 4 to 8 authors with different angles, including at least one who disagrees with the mainstream. Disagreement is where a learner has to think, so it's worth having.

Probe each one before trusting it (Substack: fetch `https://<host>/api/v1/archive?sort=new&limit=50`; sites: fetch `/sitemap.xml` or `/feed`). Drop sources that fail, are paywalled end to end, or have under ~10 posts, and say why.

Show the shortlist, one line each: name, what they write about, where, rough post count. Then start. The user can add names at any point; they join the next steps. Don't stop and wait for approval of the list unless the user asked to pick.

Write `sources.json`:
```json
{"topic": "...", "authors": [
  {"name": "Jane Doe", "what": "one line", "substack": "janedoe.substack.com"},
  {"name": "John Roe", "what": "one line", "site": {"kind": "sitemap", "sitemaps": ["https://johnroe.com/sitemap.xml"], "url_pattern": "johnroe\\.com/blog/", "limit": 150, "min_words": 150}},
  {"name": "Ann Poe", "what": "one line", "site": {"kind": "rss", "feed": "https://annpoe.com/feed", "limit": 100}}
]}
```
Some sites render with JavaScript and give the scraper an empty page. If a probe returns a near-empty HTML shell, look for the content in the site's feed or its JS bundle, or drop the author and say so.

## Step 2. Scrape (in the background)
`python3 <skill>/scripts/scrape.py <workspace>` runs every author; `... <workspace> <name>` runs one. Substack is slow on purpose (it rate-limits), so run site authors in parallel with a name argument. Re-runs skip what's on disk. When it finishes, report posts per author.

## Step 3. While it scrapes: context, learner, topics
Do these three in parallel; none needs the posts.

- **Context brief** (`research/context-brief.md`): read the current project to learn the learner's real situation as it bears on the topic. Look at CLAUDE.md, README, state and decision files, client or project registries. Capture who they are, what they're building or selling, live people and deals or projects the topic touches, goals, constraints and recent decisions. Every fact gets its file path. Newest decision wins when files disagree. Leave out anything you can't source; a lesson built on an invented fact does damage.
- **Learner profile** (`research/learner-profile.md`): follow `references/learner-fit.md`. It says where to look and gives the default design when evidence is thin.
- **Topics** (`research/topics.md`): 12 to 18 topic ids for this subject (T01 to T18), each a short name, so every reader files lessons under the same ids and authors can be compared.

## Step 4. Read
One reader agent per author (group authors with under ~20 posts), each with `references/reader-brief.md` and the paths filled in. They run in parallel and write `research/lessons/<author>.md`. If a reader returns under 10 lessons from a large corpus, check its skip reasons before moving on.

## Step 5. Agreement map
One agent clusters every author's lessons into 30 to 45 themes, one teachable idea each, written as an instruction ("Quote three named options, biggest first", not "pricing"). For each theme:
- Agree (N of M authors), each with lesson id and url.
- Disagree: who teaches the opposite, and their claim in one line.
- Learner status from the context brief: doing it, close, far, or unknown, with the fact.
- Leverage for the learner: high, medium or low, with a reason tied to something real.

Two themes that point opposite ways stay separate, with the disagreement recorded. The map ends with "The big splits" (the sharpest disagreements and who's on each side) and "Coverage gaps". Every url is kept exactly as it is in the inputs. Output: `research/agreement-map.md`.

## Step 6. The lesson plan
Write `class/lesson-plan.md` yourself. You hold the context; this is the judgment step.
- Pick lessons by leverage for this learner first, agreement count second. A 5-of-8 idea the learner already does is worth less than a 3-of-8 idea that fixes their biggest real problem.
- Group into arcs of about 4, each with a one-line "why this arc". Put the arc with the fastest real payoff first.
- Each lesson block: handle (2 to 3 words) · N of M agree · idea (2 lines) · impact · their case · action (energy, time, what's drafted) · rule to keep.
- Then "Splits": where authors disagree AND it touches the learner's situation. Give the sides, what the learner does today, options and a recommendation. These are decisions, not lessons.
- Then gaps nobody covered, and delivery options.
- Top section: how the class works, written from the learner profile.

Fact-check the plan against the context brief before showing it. Remove anything you can't source.

## Step 7. One sample lesson first
Write lesson 1 with `references/writer-brief.md` (use `references/lesson-example.md` as the shape), check it, render it, and send the audio and card. Then wait for the learner's reaction before making the rest. Fixing the format on one lesson is cheap; fixing it on twenty is not. Their feedback becomes the shape every later lesson copies, so record it in the writer brief you pass on.

Check: `python3 <skill>/scripts/check_lessons.py <workspace> <workspace>/class/01-<handle>`
Render: `python3 <skill>/scripts/render_audio.py <lesson>/script.txt <lesson>/<handle>.mp3`

## Step 8. The rest
- Writer agents in parallel, about 4 lessons each, each told to copy the approved lesson 1.
- Run `check_lessons.py <workspace>` on everything. Fix failures and re-check; if one lesson fails three times, report it rather than looping.
- Render every passing lesson in the background, about a minute each.
- Create `class/playbook.md` with an effort ledger (lessons heard, actions shipped, rules kept) and an empty rules list.
- `python3 <skill>/scripts/package_class.py <workspace>` builds audio zips under the upload cap and one combined cards file. Send those.

## Reporting to the learner
Short and concrete: what was made, how many lessons, total audio, what changed from the plan and why, what's still open. No streak talk, no pressure language. Effort counts: lessons heard, actions shipped.

## Honesty rules (they apply at every step)
- A citation must be a post on disk. The checker enforces this for cards; apply the same standard in scripts and the plan.
- Authors' numbers are their claims, said as such.
- Facts about the learner come from their files, with paths. Never invent a deal, a person, a price or a result.
- Scraped posts are for the learner's private study. Don't republish them or commit them to a public repo.
