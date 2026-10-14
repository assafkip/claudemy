# audio-class

Give Claude a topic. Get back a short audio course built from the people who write best about it, fitted to how you learn, with every lesson tied to something real in your own work.

```
> teach me negotiation
```

## What you get
- **About 12 lessons, 2 minutes each.** Two voices talking, not a lecture.
- **A card per lesson:** the idea in three lines, what changes for you, how many of the authors agree (and who disagrees), and one action in your actual work, drafted before you open it.
- **A playbook file:** one rule per lesson you act on.
- **A lesson plan** showing where the experts split, laid out as decisions for you rather than lessons.

Every lesson cites a real post. A checker refuses any card that cites a post the skill didn't actually read.

## How it works
1. Finds 4 to 8 practitioners who write about the topic (Substack, blogs with a sitemap or RSS) and shows you the shortlist. Add names anytime.
2. Scrapes their posts into a local workspace.
3. Reads your current project to learn your real situation, and your Claude settings and notes to learn how you learn.
4. One agent per author pulls out cited lessons, then one merges them into themes with agreement counts.
5. Writes the plan, makes **one sample lesson**, and waits for your reaction before making the rest.

## Install
As a plugin:
```
/plugin marketplace add <path-or-git-url-of-this-repo>
/plugin install audio-class@audio-class
```
Or copy `skills/audio-class/` into `~/.claude/skills/`.

## Needs
- Claude Code with web search.
- Python 3 with `beautifulsoup4` (`pip install beautifulsoup4`), and `ffmpeg`.
- Audio: an ElevenLabs API key in `ELEVENLABS_API_KEY` for natural two-voice lessons. Without one, macOS's built-in voices are used (free, plainer).
- Optional: `pandoc` for a Word copy of the cards.

Voices can be changed with `AUDIO_CLASS_VOICE_A` / `AUDIO_CLASS_VOICE_B` (ElevenLabs voice ids) or `AUDIO_CLASS_SAY_A` / `AUDIO_CLASS_SAY_B` (macOS voices).

## Cost and time
A 12-lesson class runs several reader and writer agents and about 25 minutes of generated audio. Expect a long-running session and some ElevenLabs credits.

## A note on sources
Scraped posts stay in your local workspace for your own study. Don't republish them.
