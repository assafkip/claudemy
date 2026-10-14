# Writer brief: one lesson = script.txt + card.md

Give this to each writer agent with its lesson numbers. Lesson 1, once the user has approved it, is the shape every other lesson copies; point the writers at it.

## Read first
1. The approved lesson 1: `<workspace>/class/01-*/script.txt` and `card.md` (or `references/lesson-example.md` if lesson 1 is the one being written).
2. Your lessons' blocks in `<workspace>/class/lesson-plan.md`. The plan is the spec; the card expands it and never contradicts it.
3. The themes behind them in `<workspace>/research/agreement-map.md`, and detail in `research/notes/*.md`.
4. The pages in `<workspace>/raw/` for a real story or number. Open the page before quoting it.

## script.txt
- Two hosts, one turn per line: `A: ...` or `B: ...`. Nothing else on any line.
- 280 to 350 words (about 2 minutes of audio; the checker enforces this band).
- Write the way people talk: contractions, short turns, reactions ("right?", "oof", "exactly"), numbers written the way they're said. Energetic, warm, never a lecture.
- At most 3 audio tags, only `[laughs]`, `[chuckles]`, `[sighs]`, at the start of a turn.
- Shape: hook, the idea, how widely sources agree (and who pushes back), one real story or number from a page, a concrete example of it in use, then the small thing to try, then one line to close on what changes.
- Speak to "you", the listener. Assume nothing about them beyond the level in `sources.json`.
- No emdashes, no double hyphens. Skip demand words aimed at the listener (you need to, you must, you should, you have to, make sure): the listener chooses, the lesson offers. Describing a situation is fine ("both sides have to say yes").

## card.md
Sections in this order (the checker looks for them):
- `# Lesson N. <Handle>` (a 2 to 3 word name; named ideas stick)
- `**Listen:** <slug>.mp3 (2 min)` (the render replaces the time with the real one)
- `**The idea, in three lines**` then three bullets
- `**Impact:**` one line: what gets better once you do this
- `**Who says it:**` N of M sources agree, plus who disagrees and how, in one line
- `**Try it** · <Energy> · <minutes>` where Energy is Quick Win, Deep Focus, People or Admin. One small practice anyone at this level can do in 2 to 15 minutes, spelled out so there's nothing to figure out first: the steps, the script, the template.
- `**Rule to keep**` one sentence for the playbook
- `**Skip**` skipping costs nothing; the next lesson is just the next lesson
- `**Go deeper (optional)**` 2 or 3 source urls

## Hard rules on facts
- Every url must appear exactly as a `url:` line in a page in `raw/`. Grep before you write it. The checker fails anything else.
- Source numbers are their claims ("one study found", "by his count").
- Health, legal, financial and safety advice: say when it depends on the person's situation, and name when to ask a professional if the sources do.

## Output
`<workspace>/class/NN-<handle-slug>/script.txt` and `card.md` (NN two digits). Don't render audio. Final message: per lesson, folder, word count, urls cited.
