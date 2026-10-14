# Reader brief: turn a batch of pages into cited notes

Give this file to each reader agent with its batch name and its list of pages. The reader turns pages into concrete, cited lesson candidates that can be compared across sources.

## Inputs (the orchestrator fills these in)
- Batch name: a short letter (`a`, `b`, `c`...).
- Pages: an explicit list of file paths under `<workspace>/raw/web/` (or `raw/<person>/` in person mode). Read only these. Markdown with front matter: title, date, url, words.
- Sub-topic ids: `<workspace>/research/topics.md`.
- The learner's level, from `sources.json`.

## Rules
- A page with nothing teachable on the topic is skipped, and so is a teaser or summary of a paywalled article, even if it carries one number. Count the skips and say why in one line.
- Every note cites its page by the exact `url:` value. No citation, no note. A short quote (under 25 words) when the wording matters.
- Concrete beats abstract: a technique, a number, a rule of thumb, a test, a template, a common mistake. "Practice makes perfect" with nothing behind it is not a note.
- File each note under the one sub-topic it fits best. If it clearly serves another, name it on an `Also:` line; don't copy the note.
- A source's numbers are its claims. Write "(their claim)".
- Note bias: when a page sells a course, a product or a service, say so.
- Note a story or example worth retelling in audio, with its url. Lessons land on a story.
- No emdashes or double hyphens in the output.

## Output: `<workspace>/research/notes/<batch>.md`
Note ids carry the batch name, so they stay unique across files: `a:N1`, `a:N2`, and so on.
```
# Notes: batch <batch>
Pages read: N. With notes: N. Skipped: N (why, one line).

## T03 <sub-topic name>
- a:N1. <the idea, one or two concrete sentences>
  - Source: <url>  Quote: "<short phrase>"
  - Kind: technique | rule of thumb | mistake | number | story | definition | template | test
  - Level: foundation | core | advanced
  - Also: T07 (only if it clearly serves a second sub-topic)
  - Bias: <one line, or none>
```
Write 20 to 50 notes. If you have more, keep the 50 strongest: concrete, well sourced, and useful at this level. End with:
- `## Disagreements seen` (up to 5: which pages contradict which, on what, with urls)
- `## Best stories` (up to 5, one line each, with url)

Final message: the counts line plus the best stories.
