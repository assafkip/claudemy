# Reader brief: extract lessons from one author's posts

Give this file to one reader agent per author (or per group of small authors). The reader turns a pile of scraped posts into concrete, cited lessons that can be compared across authors.

## Inputs (the orchestrator fills in the paths)
- Posts: `<workspace>/raw/<author-slug>/`. Markdown with front matter: title, date, url, words, paywalled.
- Topic ids: `<workspace>/research/topics.md` (12 to 18 ids written for this topic, see SKILL.md step 3).
- The learner's context: `<workspace>/research/context-brief.md`. Use it ONLY to fill each lesson's "Apply" line. Never bend a lesson to fit the learner.
- Earlier authors' lesson files, if any exist, so you can mark agreement and disagreement.

## Rules
- Skip posts with no teachable lesson on the topic (personal news, promos, under ~60 words of substance). Count the skips.
- Every lesson cites at least one post by its exact `url:` value. No citation, no lesson. A short quote (under 25 words) when the wording matters.
- Concrete beats abstract: a script line, a number, a rule, a test, a template. "Believe in yourself" with nothing behind it is not a lesson.
- The author's numbers are the author's claims. Write "(their claim)".
- Note promotional bias: when posts sell the author's course, community or book.
- No emdashes or double hyphens in the output.

## Output: `<workspace>/research/lessons/<author-slug>.md`
```
# <Author>: lessons
Posts read: N. With lessons: N. Skipped: N (why, one line).
Who they are and what they sell (2 lines, note bias).

## T03 <topic name>
- L1. <the lesson, one or two concrete sentences>
  - Source: <url> [, <url>]  Quote: "<short phrase>"
  - vs others: AGREES with <author Lx> | DISAGREES with <author Lx>: <how> | NEW
  - Apply: <one line: where the learner already does this, is close, or is far, citing a context-brief fact; "unknown" if the brief is silent>
```
Order topics by how much this author covers them. Aim for the 20 to 60 strongest lessons (fewer for small authors). End with:
- `## Strongest disagreements` (up to 5)
- `## Top 5 for the learner right now` (most leverage on the learner's real situation, one line why each)

Final message: the counts line plus the Top 5.
