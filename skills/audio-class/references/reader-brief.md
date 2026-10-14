# Reader brief: turn a batch of pages into cited notes

Give this file to each reader agent with its batch of pages. The reader turns pages into concrete, cited lesson candidates that can be compared across sources.

## Inputs (the orchestrator fills in the paths)
- Pages: the files listed for this batch, under `<workspace>/raw/web/` (or `raw/<person>/` in person mode). Markdown with front matter: title, date, url, words.
- Sub-topic ids: `<workspace>/research/topics.md`.
- The learner's level, from `sources.json`.

## Rules
- Skip pages with nothing teachable on the topic. Count the skips and say why in one line.
- Every note cites its page by the exact `url:` value. No citation, no note. A short quote (under 25 words) when the wording matters.
- Concrete beats abstract: a technique, a number, a rule of thumb, a test, a template, a common mistake. "Practice makes perfect" with nothing behind it is not a note.
- A source's numbers are its claims. Write "(their claim)".
- Note bias: when a page sells a course, a product or a service, say so.
- Note a story or example worth retelling in audio, with its url. Lessons land on a story.
- No emdashes or double hyphens in the output.

## Output: `<workspace>/research/notes/<batch>.md`
```
# Notes: <batch name>
Pages read: N. With notes: N. Skipped: N (why, one line).

## T03 <sub-topic name>
- N1. <the idea, one or two concrete sentences>
  - Source: <url>  Quote: "<short phrase>"
  - Kind: technique | rule of thumb | mistake | number | story | definition
  - Level: foundation | core | advanced
  - Bias: <one line, or none>
```
Aim for the 20 to 50 strongest notes. End with:
- `## Disagreements seen` (up to 5: which pages contradict which, on what)
- `## Best stories` (up to 5, one line each, with url)

Final message: the counts line plus the best stories.
