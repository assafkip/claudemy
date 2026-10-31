# Portable Windows bundle

One zip for people who should not have to install anything: they unzip it and double-click
`Start Book2Audio.bat`. It carries its own Python, ffmpeg and book2audio, needs no administrator rights and
changes nothing outside its folder (settings and unfinished work go to `%LOCALAPPDATA%\book2audio`, finished
audiobooks to `Music\book2audio`).

## Build it

On Windows, with any Python 3.10+ and internet access:

```powershell
python packaging\build_windows_bundle.py --work C:\Temp\b2a-bundle
```

Result: `C:\Temp\b2a-bundle\out\Book2Audio-<version>-windows-x64.zip` (about 105 MB zipped, 235 MB unzipped).
Use a `--work` folder that is not synced by OneDrive. Downloads are cached in `<work>\cache`, so a second build
is quick and offline for those two files.

The script downloads three things, each checked before it is used:

| What | From | Check |
|---|---|---|
| Python 3.13.17 "embeddable package" (11 MB) | python.org | SHA-256 shown on python.org's release page, pinned in the script |
| FFmpeg n9.0.2 **LGPL shared** build (77 MB) | BtbN/FFmpeg-Builds on GitHub (a dated autobuild release) | SHA-256 from BtbN's `checksums.sha256`, pinned in the script; the build is also refused if its banner says `--enable-gpl` or `--enable-nonfree` |
| book2audio, its dependencies, `anthropic` and `pip` (about 60 MB) | PyPI, as binary wheels for Windows | pip's own checks; versions are whatever PyPI serves on the build day (see `licenses\PACKAGES.txt` in the zip) |

Then it assembles `Book2Audio\`, **runs what it assembled** (imports every dependency, finds the page files,
starts `python -m book2audio --version`, runs `ffmpeg -version`) and only then zips it.

If a pinned download disappears (BtbN keeps only recent builds), choose a new release on
<https://github.com/BtbN/FFmpeg-Builds/releases>, take the `win64-lgpl-shared` zip and its line from
`checksums.sha256`, and change `FFMPEG` at the top of the script. Same for a new Python: change `PYTHON`.
Python's Windows binaries stop at 3.13.x and 3.14.x for security fixes; 3.12.11 and later have no embeddable zip.

## What is in the zip

```
Book2Audio\
  Start Book2Audio.bat      the launcher (puts its own ffmpeg first on PATH, runs python -m book2audio ui)
  START HERE.txt            the one-page guide for the person who receives it
  python\                   embeddable Python + Lib\site-packages (book2audio, dependencies, pip)
  ffmpeg\                   ffmpeg.exe, ffprobe.exe and the LGPL shared libraries
  licenses\                 book2audio MIT (with the Claudemy credit), Python, FFmpeg LGPL, THIRD-PARTY-NOTICES,
                            PACKAGES.txt (every Python package with its licence), BUILD-INFO.txt (exact versions)
```

## Licences, decided

- **ffmpeg** is the LGPL build, not the GPL "full" build that `winget install Gyan.FFmpeg` gives. book2audio only
  needs the native AAC encoder, `loudnorm` and the MP4 muxer, which the LGPL build has. The notices name the exact
  FFmpeg commit and where its source lives, and the libraries are separate DLLs the user may replace.
- **Piper is not in the bundle.** It is GPL-3.0-or-later; a bundle that contained it would have to carry its licence
  and source offer, and every voice model has its own licence (some restrict commercial use). Instead the page's
  **Install it for me** button runs one fixed command, `pip install piper-tts`, on the user's own computer, and the
  voice list downloads a voice from the Piper voice library on request. book2audio only starts Piper as a separate
  program. `pip` is in the bundle so that button works.
- Python (PSF licence), the PyPI wheels (their own licences, listed in `PACKAGES.txt`) and book2audio (MIT) ship
  with their licence files. This is the build's own reading of the licences, not legal advice: have someone check
  before you hand the zip to people outside your own circle.

## Checked, and not checked

Checked on this build: the extracted zip, in a folder with spaces and an accented letter, starts from the launcher
and shows the page; the checklist finds the bundled ffmpeg and offers "Install it for me"; a book is converted end
to end (upload, two chapters, a chaptered `.m4b` with title tag) using only the bundle's Python 3.13 and ffmpeg
with a fake voice; the whole test suite passes on the bundle's Python 3.13 with only the LGPL ffmpeg on PATH.

Not checked:
- A clean PC. This was built and tried on the author's own Windows 11 PC, which already has other Python and ffmpeg
  installs (the test PATH excluded them, but the machine is not clean). The Piper wheel's `onnxruntime` may need the
  Microsoft Visual C++ Redistributable on a PC that never had it; the guide says what to do if Windows complains.
- Piper itself (the install button, a voice download, a real voice), and any paid service.
- Whether a work PC's policy (AppLocker, antivirus, SmartScreen) lets programs from a user folder run. The
  executables are python.org's (signed by the PSF) and BtbN's ffmpeg (not signed). Try it on the target PC first.
- macOS. There is no embeddable Python for the Mac; for Mac users use the install steps in the main README.
