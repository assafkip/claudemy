# Map brief: cluster every note into themes with agreement counts

Give this file to the one agent that builds the agreement map.

## Inputs
- Every notes file: `<workspace>/research/notes/*.md`. Note ids look like `a:N12`.
- Sub-topic ids: `<workspace>/research/topics.md`.

## What a theme is
One teachable idea, written as an instruction: "Anchor with a specific number, not a round one", not "anchoring". Aim for 30 to 45 themes. Two ideas that point opposite ways are two themes, with the disagreement recorded on both.

A note can support more than one theme; list it under each.

## Counting agreement: N of M
- **M** is the number of distinct pages (urls) with at least one note on this theme's sub-topic, including its `Also:` lines. These are the sources that had a chance to say it.
- **N** is how many of those M pages support the theme.
- Count pages, not notes: three notes from one page are one source.

So "9 of 14" means 14 pages covered this ground and 9 of them teach this idea. A theme with M under 3 is marked "thin evidence".

## For each theme
```
## TH07 <the idea, as an instruction>
- Sub-topic: T03 (also T07)
- Agree: N of M. Notes: a:N3, c:N12 ... Urls: <each supporting url once>
- Disagree: <url>: <their claim in one line>, or "none found"
- Level: foundation | core | advanced
- Best story: <one line, with url>, or none
```
A disagreement taken from a "Disagreements seen" section has no note id; cite its url.

## End of the map
- `## The big splits`: the sharpest disagreements, who's on each side (urls), and what the disagreement turns on.
- `## Coverage gaps`: sub-topics with thin evidence, and what a learner would expect that no source covered.

Keep every url exactly as it appears in the notes. Output: `<workspace>/research/agreement-map.md`. Final message: theme count by level, the big splits in one line each, and the gaps.
