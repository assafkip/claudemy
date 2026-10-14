# audio-class

Give Claude a topic. It researches it and hands back a broken-down set of 2-minute audio lessons.

```
> teach me negotiation
```

## What you get
- **About 12 lessons, 2 minutes each.** Two voices talking, not a lecture.
- **A card per lesson:** the idea in three lines, how widely the sources agree (and who disagrees), and one small thing to try, spelled out.
- **A playbook file:** one rule per lesson.
- **A lesson plan** showing where good sources split, laid out as decisions rather than lessons.

Every lesson cites a page the class actually read. A checker refuses any card that cites a page that isn't saved in the workspace.

## How it works
1. Maps the topic into sub-topics, from how it's usually taught.
2. Searches the web for 20 to 40 pages worth learning from: practitioners, official docs, research summaries, and a few dissenting views. No more than 3 pages from one site.
3. Reader agents pull cited notes from the pages, then one agent merges them into themes with agreement counts.
4. Writes the plan, makes **one sample lesson**, and waits for your reaction before making the rest.

Want a class from one person's work instead? Say so: `teach me negotiation from <name>'s writing`. It reads their Substack or blog and builds the class from that.

## Install
As a plugin:
```
/plugin marketplace add assafkip/audio-class
/plugin install audio-class@audio-class
```
Or copy `skills/audio-class/` into `~/.claude/skills/`, or download `dist/audio-class.skill`.

## Needs
- Claude Code with web search.
- Python 3 with `beautifulsoup4` (`pip install beautifulsoup4`), and `ffmpeg`.
- Audio: an ElevenLabs API key in `ELEVENLABS_API_KEY` for natural two-voice lessons. Without one, macOS's built-in voices are used (free, plainer).
- Optional: `pandoc` for a Word copy of the cards.

Voices can be changed with `AUDIO_CLASS_VOICE_A` / `AUDIO_CLASS_VOICE_B` (ElevenLabs voice ids) or `AUDIO_CLASS_SAY_A` / `AUDIO_CLASS_SAY_B` (macOS voices).

## Cost and time
A 12-lesson class runs several reader and writer agents and about 25 minutes of generated audio. Expect a long-running session and some ElevenLabs credits.

## A note on sources
Pages the class reads are saved in your local workspace for your own study. Don't republish them.

## License
MIT. Free to use, change and share.
