# Writer brief: one lesson = script.txt + card.md

Give this to each writer agent with its lesson numbers. Lesson 1, once the learner has approved it, is the shape every other lesson copies; point the writers at it.

## Read first
1. The approved lesson 1: `<workspace>/class/01-*/script.txt` and `card.md` (or `references/lesson-example.md` if lesson 1 is the one being written).
2. Your lessons' blocks in `<workspace>/class/lesson-plan.md`. The plan is the spec; the card expands it and never contradicts it.
3. The themes behind them in `<workspace>/research/agreement-map.md`, and detail in `research/lessons/<author>.md`.
4. Raw posts in `<workspace>/raw/` for a real story or number. Open the post before quoting it.
5. `<workspace>/research/context-brief.md` (the learner's real situation) and `research/learner-profile.md` (how they learn).

## script.txt
- Two hosts, one turn per line: `A: ...` or `B: ...`. Nothing else on any line.
- 300 to 380 words (about 2 minutes of audio).
- Write the way people talk: contractions, short turns, reactions ("right?", "oof", "exactly"), numbers written the way they're said. Energetic, warm, never a lecture.
- At most 3 audio tags, only `[laughs]`, `[chuckles]`, `[sighs]`, at the start of a turn.
- Shape: hook, the idea, who says it (name the authors), one real story or number from a post, then "here's where it gets real" with the learner's own case, then today's small action, then one impact line to close.
- Speak to "you", the learner.
- No emdashes, no double hyphens. Skip demand words (need to, must, should, have to, make sure): the learner chooses, the lesson offers.

## card.md
Sections in this order (the checker looks for them):
- `# Lesson N. <Handle>` (a 2 to 3 word name; named ideas stick)
- `**Listen:** <slug>.mp3 (2 min)`
- `**The idea, in three lines**` then three bullets
- `**Impact:**` one line: what changes for the learner, in growth terms
- `**Who says it:**` N of M authors agree, by name, plus who disagrees and how, in one line
- `**Try it on: <their real case>.**` with the file it came from
- `**Your action** · <Energy> · <minutes>` where Energy is Quick Win, Deep Focus, People or Admin. The thing is drafted already: a message, a line, a list. If it needs data you don't have, write the phrase the learner says ("say 'source count'") and what Claude then does. Never a command to type.
- `**Rule to keep**` one sentence for their playbook
- `**Skip**` skipping costs nothing; the next lesson is just the next lesson
- `**Go deeper (optional)**` 2 or 3 source urls

## Hard rules on facts
- Every url must appear exactly as a `url:` line in a raw post. Grep before you write it. The checker fails anything else.
- Author numbers are their claims ("she says", "by his count").
- Facts about the learner come only from context-brief.md, the plan, or a file you opened (cite it). Unsure means leave it out.
- Prices, legal terms or medical claims for the learner's real decisions: never invent; write `{{decide: <what>}}`.
- Drafted messages to real people: short, casual, no invented facts about the person or the deal. If sending depends on the latest state of a thread, say "Claude checks the thread first."

## Output
`<workspace>/class/NN-<handle-slug>/script.txt` and `card.md` (NN two digits). Don't render audio. Final message: per lesson, folder, word count, urls cited.
