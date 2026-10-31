# STATE: book2audio in the fork gcazzola/chillbook

Updated 2026-10-31. Rewrite this file at the end of a work block; do not append.

## Where things stand
- The `book2audio` CLI is done: EPUB and PDF ingestion, speech normalization, chunking, backends (elevenlabs, google Chirp 3 HD, piper, say), optional `--llm` pass, ffmpeg M4B with chapters, `--dry-run`, `--yes` gate for paid runs, resumable job folder.
- 80 tests pass (last run at `a65e8da`).
- Branches: `feat/book2audio` is pushed up to `d0694f6`; `a65e8da` (Google backend) is local only. `feat/book2audio-ui` holds the visual interface, built by a separate session. `main` is upstream Claudemy, untouched.
- Live checks by the user: Google Chirp 3 HD samples (14 voices) and one ElevenLabs sample returned audio. Not yet live: a full chapter on either, Piper, the Anthropic pass.

## Open work
- Push `a65e8da` (the user pushes; nothing here pushes on its own).
- Visual interface: phase 1 app on `feat/book2audio-ui`; phase 2 packaging for non-technical users (licence flags: ffmpeg full build is GPL, Piper is GPL, each Piper voice has its own licence).
- First real chapter test: `book2audio BOOK --backend google --chapters 1 --yes` (or `--backend elevenlabs`).
- Run `/code-review`, and `/security-review` before pushing (the code handles API keys).

## Out of date or unconfirmed
- Cost and time numbers are estimates; no price is built in (`--price-per-1k`). Google's Chirp 3 HD price and free allowance are unconfirmed.
- Google API-key auth is only community-confirmed; the documented path is a gcloud access token.
- Google input limit is 5,000 bytes per request; chunks are 1,500 characters.

## Fragile
- PDF handling was tuned on one synthetic PDF; real books may need tuning (columns, tables, small print low on a page).
- Windows: use the short-path venv `%LOCALAPPDATA%\Temp\b2a-venv`; ffmpeg is installed by winget but not on PATH in the agent shell; `gh` is unavailable.
- Two sessions can share this one checkout: run `git branch --show-current` before committing.

## Where to look
- Docs: `book2audio/README.md`. Code: `book2audio/src/book2audio/` (`cli.py`, `pipeline.py`, `tts.py`, `estimate.py`).
- Tests: `cd book2audio && python -m unittest discover -s tests`.
- Voice sample script: `book2audio/examples/chirp3_sample.py`.
