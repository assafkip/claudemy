# book2audio

Turn an **.epub** or **.pdf** book into a chaptered **.m4b** audiobook, with a free local voice, ElevenLabs or Google Chirp 3 HD.

```
book2audio mybook.epub --dry-run        # chapters, size, time and cost; spends nothing
book2audio mybook.epub                  # free local voice (Piper); writes mybook.m4b
```

The output has one chapter marker per chapter, the book's title and author, the cover (when the book has one) and every chapter at the same loudness. Play it in any audiobook app.

## Install

You need Python 3.10 or newer and ffmpeg.

```bash
# Windows:  winget install Gyan.FFmpeg      (then open a new terminal)
# macOS:    brew install ffmpeg
git clone https://github.com/gcazzola/chillbook && cd chillbook
pip install ./book2audio
```

Pick a voice engine (you need at least one):

| Backend | Cost | Install |
|---|---|---|
| `piper` (default) | free, runs on your computer | `pip install piper-tts`, then `python -m piper.download_voices en_US-lessac-medium` in the folder you run from (or set `PIPER_DATA_DIR`) |
| `elevenlabs` | paid, cloud | an API key in the `ELEVENLABS_API_KEY` environment variable |
| `google` | paid, cloud (Google Cloud Text-to-Speech, Chirp 3 HD voices) | `GOOGLE_TTS_API_KEY` set to an API key allowed to call the Text-to-Speech API, or the `gcloud` CLI logged in with `gcloud auth login` |
| `say` | free, macOS only | nothing |

Optional extras:

- `pip install anthropic` (or `pip install "./book2audio[llm]"`) for the Claude pass, with `ANTHROPIC_API_KEY` set.
- `ocrmypdf` plus the tesseract program, to read scanned PDFs.

Set keys in your shell for the session (PowerShell: `$env:ELEVENLABS_API_KEY = "..."`). They are only ever read from the environment: never written to disk, never printed, never committed. Do not put them in a file in this folder.

## Use

**Always start with a dry run.** It reads the book and prints the chapter list, the character count, and the estimated audio length, synthesis time and cost for each backend. It does not synthesize anything or contact any service.

```bash
book2audio mybook.pdf --dry-run --price-per-1k 0.30
```

```
alice.epub (EPUB): 12 chapters to narrate, 4 skipped
    #  Chapter                                        Characters     Audio
    1  CHAPTER I. Down the Rabbit-Hole                    11,251    13 min
    ...
       Total                                             142,548    2h 38m
Backend        To synthesize      Cached   Est. time  Cost
elevenlabs        142,463 ch        0 ch      12 min  142,463 credits = 42.74 at 0.3 per 1,000
piper             142,485 ch        0 ch      16 min  free (local) <- selected
```

Then run it for real:

```bash
book2audio mybook.epub                                    # Piper, free
book2audio mybook.epub --chapters 1 --backend elevenlabs --yes   # try one chapter on ElevenLabs first
book2audio mybook.pdf  --backend elevenlabs --voice <voice id> --yes
```

A paid run (ElevenLabs, Google, or `--llm`) prints the same estimate and then stops until you repeat the command with `--yes`.

### Hear a Google Chirp 3 HD sample first

[examples/chirp3_sample.py](examples/chirp3_sample.py) asks Google for one short sample and saves it as an MP3. It needs only Python and your credentials, so it is also the quickest check that the Text-to-Speech API is switched on for your project. A sample is about 100 characters.

```powershell
$env:GOOGLE_TTS_API_KEY = "your-key"     # or: gcloud auth login
python examples\chirp3_sample.py                                          # default voice: Charon
python examples\chirp3_sample.py --voice en-US-Chirp3-HD-Leda --voice en-US-Chirp3-HD-Kore
python examples\chirp3_sample.py --list                                   # the 30 voice names
python examples\chirp3_sample.py "Any text you would like to hear."
```

Then use the voice you like for the book:

```powershell
book2audio mybook.epub --backend google --voice en-US-Chirp3-HD-Leda --dry-run --price-per-1k 0.03
book2audio mybook.epub --backend google --voice en-US-Chirp3-HD-Leda --chapters 1 --yes
```

`--price-per-1k` is what 1,000 characters cost you. Check Google's [pricing page](https://cloud.google.com/text-to-speech/pricing) for the current Chirp 3 HD rate and free allowance; the number above is only an example.

### Options

| Option | Meaning |
|---|---|
| `-o FILE` | output `.m4b` (default: next to the input) |
| `--job-dir DIR` | working folder (default `<input>.b2a`) |
| `--backend`, `--voice`, `--model` | voice engine, its voice, and the ElevenLabs model (`eleven_multilingual_v2` by default) |
| `--mode faithful` | read the text as written. Default. Cleanup is done by rules. |
| `--mode adapted --llm` | Claude rewrites each chapter as natural narration; add `--condense` for about half the length |
| `--llm` | with `faithful`: Claude repairs leftover extraction damage; its reply is rejected if it drifts from the text |
| `--llm-model` | default `claude-opus-5-5`; `claude-haiku-5-5` is far cheaper |
| `--chapters 1-3,5` | only these chapters (numbers as in the dry-run list) |
| `--keep-all` | also narrate front/back matter and very short sections |
| `--cover FILE`, `--title`, `--author` | override what the book provides (PDFs have no cover unless you give one) |
| `--price-per-1k X` | what 1,000 ElevenLabs credits cost you, to show money in the estimate (or set `BOOK2AUDIO_PRICE_PER_1K`) |

### Resuming

Everything a run makes goes in the job folder, and each piece is named by a hash of its content. If a run stops (network, Ctrl-C, out of credits), run the same command again: finished chunks are reused, so credits are never spent twice. Changing the voice, model or text only redoes what changed. A job folder belongs to one input file; use another `--job-dir` for a different book.

## What it does to the text

1. **Reads the book.** EPUB: the table of contents gives the chapters, including chapters that start in the middle of a page. PDF: bookmarks give the chapters, or large headings when there are none. Front and back matter (copyright, contents, index, ads, acknowledgments, Project Gutenberg boilerplate) is skipped and listed in the dry run.
2. **Cleans PDFs.** Removes running headers and footers, page numbers, footnotes and footnote markers; rebuilds paragraphs across pages; rejoins hyphenated line ends. A scanned PDF (no text layer) is detected and passed to `ocrmypdf`, or you are told how to install it.
3. **Makes it speakable.** Expands abbreviations (Mr., Dr., etc., e.g.), numbers, years, money, percentages, times, ordinals and Roman-numeral chapter headings; reads URLs and emails; turns symbols and dashes into words and pauses. Tables, code listings and figures in EPUBs become one spoken sentence ("There is a table here with 3 rows and 2 columns, covering Name, Age.").
4. **Chunks** at sentence boundaries to fit each backend's limit, **synthesizes** each chunk (cached), and **assembles** with ffmpeg: two-pass loudness normalization per chapter to -16 LUFS, mono AAC at 64 kbit/s, chapter markers, tags and cover.

## Your text leaves your computer with cloud services

- **`--backend elevenlabs`** sends the full text of the book, in chunks, to ElevenLabs to make the audio.
- **`--backend google`** sends the full text of the book, in chunks, to Google Cloud Text-to-Speech.
- **`--llm`** sends the full text of the book, in segments, to Anthropic.
- `piper` and `say` run on your computer and send nothing anywhere.

The dry run states which of these apply to your command. Only use a cloud service for books you are allowed to send to it. Check the provider's terms on retention and on copyrighted works.

## Known limits

- English only. The number and abbreviation rules assume English, and the default voices are English.
- Synthesis is one chunk at a time. Time estimates are rough guesses; run `--chapters 1` to calibrate.
- PDF layout is heuristic. Multi-column pages, tables printed as text, small-print captions low on a page (read as footnotes), and compounds hyphenated at a line end ("well-known" becomes "wellknown") can come out wrong. Check the dry run's chapter list and listen to one chapter first.
- Piper, ElevenLabs and Google are driven the way their documentation describes, but this repository's tests use fakes for them. The first real run is the first live test.
- Google Chirp 3 HD: a request may hold at most 5,000 bytes, so chunks are 1,500 characters. Google's own examples authenticate with a `gcloud` access token; an API key is also supported here but Google's documentation does not describe it for this API, so if the key is rejected use `gcloud auth login`. The default voice is English.
- ElevenLabs credit counts are 1 per character (half for the Flash and Turbo models). Your plan decides the price, which is why it is an option and not built in.

## Tests

```bash
pip install "./book2audio[dev]"
cd book2audio && python -m unittest discover -s tests
```

The tests use Project Gutenberg #11 (*Alice's Adventures in Wonderland*, public domain) and need ffmpeg for the assembly and end-to-end tests (they are skipped without it). `tests/make_pdf_fixture.py` rebuilds the PDF fixture. No copyrighted books are used.

## Credits and license

book2audio lives in a fork of [Claudemy](https://github.com/assafkip/claudemy) by **Assaf Kipnis** (MIT), which turns a topic into short audio lessons. Its audio ideas started this project: the ElevenLabs request style and error-body reporting (`tts.py`) and the ffmpeg concat + loudness step (`assemble.py`), both adapted and marked in the file headers, plus the test layout. Everything else here is new. Claudemy's own skill is untouched in this repository.

MIT licensed; see [LICENSE](../LICENSE), which keeps Assaf Kipnis's copyright notice.

Libraries were chosen to keep this project MIT: `ebooklib` and PyMuPDF are AGPL-3.0 and are not used. `pdfminer.six` (MIT), `pypdf` (BSD-3) and `beautifulsoup4` (MIT) are. Piper (`piper-tts`) is GPL-3.0, so book2audio runs it as a separate program and never imports it.
