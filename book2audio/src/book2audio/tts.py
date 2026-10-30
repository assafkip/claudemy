"""Text-to-speech backends and the content-addressed chunk cache.

Portions adapted from Claudemy (c) 2026 Assaf Kipnis, MIT: the ElevenLabs request style and
the habit of showing the API's own error body (never the key) come from its render_audio.py.
Claudemy used ElevenLabs' two-speaker dialogue endpoint; a narrator needs the single-voice
text-to-speech endpoint used here.

Every backend turns one chunk of text into audio bytes. synth_cached() stores the result under
a hash of (backend, voice, model, settings, text), so an interrupted run resumes where it
stopped and a re-run never pays for the same chunk twice.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .book import B2AError

# ElevenLabs per-request character limits by model, from https://elevenlabs.io/docs/overview/models.
ELEVENLABS_LIMITS = {"eleven_v3": 5000, "eleven_multilingual_v2": 10000, "eleven_flash_v2_5": 40000,
                     "eleven_turbo_v2_5": 40000, "eleven_flash_v2": 30000, "eleven_turbo_v2": 30000}
CHUNK_CHARS = 2500  # long enough for good prosody, short enough that a failed call wastes little
# Claudemy's default ElevenLabs voice id (Liam); change it with --voice.
DEFAULT_ELEVENLABS_VOICE = "TX3LPaxmHKxFdv7VOQHJ"


class Backend:
    name = ""
    ext = "wav"
    paid = False
    max_chars = 3000
    voice = ""

    def check(self):
        """Raise B2AError if this backend cannot run (missing key, program or voice)."""

    def fingerprint(self) -> str:
        """Everything besides the text that changes the audio; part of the cache key."""
        return self.voice

    def synth(self, text: str, before: str = "", after: str = "") -> bytes:
        raise NotImplementedError


class ElevenLabs(Backend):
    name = "elevenlabs"
    ext = "mp3"
    paid = True
    STABILITY = 0.5  # valid for every model (eleven_v3 only accepts 0, 0.5 and 1)

    def __init__(self, voice=None, model=None):
        self.voice = voice or DEFAULT_ELEVENLABS_VOICE
        self.model = model or "eleven_multilingual_v2"
        self.max_chars = min(CHUNK_CHARS, ELEVENLABS_LIMITS.get(self.model, 5000))

    @property
    def credit_per_char(self) -> float:
        return 0.5 if ("flash" in self.model or "turbo" in self.model) else 1.0  # half price per the docs

    def fingerprint(self):
        return f"{self.voice}|{self.model}|{self.STABILITY}"

    def check(self):
        if not os.environ.get("ELEVENLABS_API_KEY"):
            raise B2AError("ELEVENLABS_API_KEY is not set. Set it in your environment (never in a file in this "
                           "project); or use --backend piper for a free local voice.")

    def synth(self, text, before="", after=""):
        body = {"text": text, "model_id": self.model, "voice_settings": {"stability": self.STABILITY}, "seed": 42}
        if self.model != "eleven_v3":  # v3 does not take neighbouring text; others use it for smooth joins
            if before:
                body["previous_text"] = before[-300:]
            if after:
                body["next_text"] = after[:300]
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice}?output_format=mp3_44100_128",
            data=json.dumps(body).encode(),
            headers={"xi-api-key": os.environ.get("ELEVENLABS_API_KEY", ""), "Content-Type": "application/json",
                     "Accept": "audio/mpeg"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                # "HTTP Error 401" alone hides the cause (bad key, quota, unknown voice id); the body says which.
                detail = e.read().decode("utf-8", "replace").strip()[:300]
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(4 ** attempt)
                    continue
                raise B2AError(f"ElevenLabs refused the request: HTTP {e.code} {e.reason}. {detail}")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 2:
                    time.sleep(4 ** attempt)
                    continue
                raise B2AError(f"could not reach ElevenLabs: {e}")


class Piper(Backend):
    """Free local voices. Piper is GPL-3.0, so it runs as its own process and is never imported."""
    name = "piper"
    ext = "wav"
    max_chars = 3000  # each call loads the voice model, so fewer, larger calls are faster

    def __init__(self, voice=None, model=None):
        self.voice = voice or "en_US-lessac-medium"

    def _cmd(self, out, text):
        cmd = [sys.executable, "-m", "piper", "-m", self.voice, "-f", str(out)]
        if os.environ.get("PIPER_DATA_DIR"):
            cmd += ["--data-dir", os.environ["PIPER_DATA_DIR"]]
        return cmd + ["--", text]

    def check(self):
        r = subprocess.run([sys.executable, "-m", "piper", "--help"], capture_output=True, text=True)
        if r.returncode:
            raise B2AError("Piper is not installed. Run: pip install piper-tts, then download a voice with: "
                           f"python -m piper.download_voices {self.voice}  (set PIPER_DATA_DIR if the voice "
                           "files are not in the current folder).")

    def synth(self, text, before="", after=""):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.wav"
            r = subprocess.run(self._cmd(out, text), capture_output=True, text=True)
            if r.returncode or not out.exists():
                raise B2AError(f"Piper failed: {(r.stderr or r.stdout).strip()[-300:]}")
            return out.read_bytes()


class Say(Backend):
    """macOS built-in voices: free, offline, plainer."""
    name = "say"
    ext = "aiff"

    def __init__(self, voice=None, model=None):
        self.voice = voice or "Samantha"

    def check(self):
        if not shutil.which("say"):
            raise B2AError("the 'say' backend only exists on macOS; use --backend piper instead")

    def synth(self, text, before="", after=""):
        with tempfile.TemporaryDirectory() as td:
            src, out = Path(td) / "in.txt", Path(td) / "out.aiff"
            src.write_text(text, encoding="utf-8")
            r = subprocess.run(["say", "-v", self.voice, "-o", str(out), "-f", str(src)], capture_output=True,
                               text=True)
            if r.returncode:
                raise B2AError(f"say failed: {r.stderr.strip()[-300:]}")
            return out.read_bytes()


BACKENDS = {"elevenlabs": ElevenLabs, "piper": Piper, "say": Say}


def make_backend(name, voice=None, model=None) -> Backend:
    if name not in BACKENDS:
        raise B2AError(f"unknown backend {name!r}; choose from {', '.join(BACKENDS)}")
    return BACKENDS[name](voice, model)


def cache_key(backend: Backend, text: str) -> str:
    return hashlib.sha256(json.dumps([backend.name, backend.fingerprint(), text]).encode()).hexdigest()[:32]


def cache_path(backend: Backend, text: str, cache_dir: Path) -> Path:
    return Path(cache_dir) / backend.name / f"{cache_key(backend, text)}.{backend.ext}"


def synth_cached(backend: Backend, text: str, cache_dir: Path, before="", after="") -> tuple[Path, bool]:
    """-> (audio file, True if it came from the cache). The file is written atomically."""
    path = cache_path(backend, text, cache_dir)
    if path.exists() and path.stat().st_size > 0:
        return path, True
    data = backend.synth(text, before, after)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path, False
