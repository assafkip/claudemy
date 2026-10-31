"""The voices and models each engine offers, for the voice picker in the web page.

Google's 30 Chirp 3 HD names are from https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd (same list as
examples/chirp3_sample.py). ElevenLabs voices come from the account when a key is present. Piper voices are the
.onnx files found in the voice folder; macOS voices come from `say -v ?`.
"""
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

from .book import B2AError
from .tts import DEFAULT_ELEVENLABS_VOICE, _http

GOOGLE_NAMES = {
    "female": "Achernar Aoede Autonoe Callirrhoe Despina Erinome Gacrux Kore Laomedeia Leda Pulcherrima Sulafat "
              "Vindemiatrix Zephyr".split(),
    "male": "Achird Algenib Algieba Alnilam Charon Enceladus Fenrir Iapetus Orus Puck Rasalgethi Sadachbia "
            "Sadaltager Schedar Umbriel Zubenelgenubi".split(),
}
# A few of the languages Chirp 3 HD documents; the voice names are the same in each.
GOOGLE_LANGUAGES = {"en-US": "English (US)", "en-GB": "English (UK)", "en-AU": "English (Australia)",
                    "en-IN": "English (India)", "de-DE": "German", "fr-FR": "French", "es-ES": "Spanish (Spain)",
                    "es-US": "Spanish (US)", "it-IT": "Italian", "pt-BR": "Portuguese (Brazil)", "nl-NL": "Dutch"}
ELEVENLABS_MODELS = [
    {"id": "eleven_multilingual_v2", "label": "Multilingual v2: natural and steady (the usual choice)"},
    {"id": "eleven_v3", "label": "v3: most expressive, newest"},
    {"id": "eleven_flash_v2_5", "label": "Flash v2.5: fast, half the credits"},
    {"id": "eleven_turbo_v2_5", "label": "Turbo v2.5: fast, half the credits"},
]
# Shown until a key is typed. Liam is the voice id this project already defaults to; the rest are ElevenLabs'
# long-standing ready-made voices, which a given account may not offer (the account's own list replaces these).
ELEVENLABS_FALLBACK = [
    {"id": DEFAULT_ELEVENLABS_VOICE, "name": "Liam", "detail": "man, ready-made"},
    {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "detail": "woman, ready-made"},
    {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam", "detail": "man, ready-made"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella", "detail": "woman, ready-made"},
]
PIPER_SUGGESTED = ["en_US-lessac-medium", "en_US-amy-medium", "en_US-ryan-medium", "en_GB-alan-medium"]
PIPER_NAME = re.compile(r"^([a-z]{2,3})_([A-Z]{2,4})-([A-Za-z0-9_]+)-(x_low|low|medium|high)$")
ELEVENLABS_ID = re.compile(r"^[A-Za-z0-9]{10,40}$")  # goes into a URL path, so nothing else is allowed


def google_voices(language="en-US") -> list[dict]:
    if language not in GOOGLE_LANGUAGES:
        raise B2AError(f"language {language!r} is not in the list")
    return [{"id": f"{language}-Chirp3-HD-{n}", "name": n, "detail": gender}
            for gender, names in GOOGLE_NAMES.items() for n in sorted(names)]


def elevenlabs_voices(api_key) -> list[dict]:
    """The account's own voices (needs a key); raises B2AError if ElevenLabs refuses."""
    req = urllib.request.Request("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": api_key})
    try:
        found = json.loads(_http(req, "ElevenLabs"))["voices"]
    except (ValueError, KeyError):
        raise B2AError("ElevenLabs answered, but not with a list of voices")
    out = []
    for v in found:
        labels = v.get("labels") or {}
        detail = ", ".join(x for x in (labels.get("gender"), labels.get("accent"), labels.get("descriptive")) if x)
        out.append({"id": v["voice_id"], "name": v.get("name", v["voice_id"]),
                    "detail": detail or v.get("category", "")})
    return sorted(out, key=lambda v: v["name"].lower())


def piper_voices(folder) -> list[dict]:
    out = []
    for f in sorted(Path(folder).glob("*.onnx")) if Path(folder).is_dir() else []:
        m = PIPER_NAME.match(f.stem)
        out.append({"id": f.stem, "name": m.group(3).replace("_", " ") if m else f.stem,
                    "detail": f"{m.group(1)}_{m.group(2)}, {m.group(4).replace('_', ' ')} quality" if m else ""})
    return out


def say_voices() -> list[dict]:
    if not shutil.which("say"):
        return []
    r = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, errors="replace")
    # a long name leaves only one space before the language, so the name is whatever comes before it
    rows = (re.match(r"^(.+?)\s+([a-z]{2,3}_[A-Za-z]{2,4})\s+#", line) for line in r.stdout.splitlines())
    return [{"id": m.group(1).strip(), "name": m.group(1).strip(), "detail": m.group(2)} for m in rows if m]


def catalog(engine, language="en-US", api_key=None, piper_dir=".") -> dict:
    """-> {models, voices, languages, note}: what to put in the pickers for this engine."""
    if engine == "google":
        return {"models": [], "languages": [{"id": k, "label": v} for k, v in GOOGLE_LANGUAGES.items()],
                "voices": google_voices(language), "note": None}
    if engine == "elevenlabs":
        mine = elevenlabs_voices(api_key) if api_key else None
        return {"models": ELEVENLABS_MODELS, "languages": [], "voices": mine or ELEVENLABS_FALLBACK,
                "note": None if mine else "Add your ElevenLabs key to see the voices on your own account."}
    if engine == "piper":
        mine = piper_voices(piper_dir)
        return {"models": [], "languages": [], "voices": mine, "suggested": PIPER_SUGGESTED,
                "note": None if mine else "No free voice is installed yet."}
    if engine == "say":
        return {"models": [], "languages": [], "voices": say_voices(), "note": None}
    raise B2AError(f"unknown voice engine {engine!r}")


def check_choice(engine, voice, model, language, piper_dir) -> None:
    """Refuse a voice or model the page could not have offered. Voices end up in URLs and command lines."""
    if engine == "elevenlabs":
        if not ELEVENLABS_ID.match(voice or ""):
            raise B2AError("that ElevenLabs voice id looks wrong; pick a voice from the list")
        if model not in {m["id"] for m in ELEVENLABS_MODELS}:
            raise B2AError("pick one of the listed ElevenLabs models")
    elif engine == "google":
        if voice not in {v["id"] for v in google_voices(language)}:
            raise B2AError("pick one of the listed Google voices")
    elif engine == "piper":
        if voice not in {v["id"] for v in piper_voices(piper_dir)}:
            raise B2AError("that free voice is not installed; install one first")
    elif engine == "say":
        if voice not in {v["id"] for v in say_voices()}:
            raise B2AError("pick one of the listed Mac voices")
    else:
        raise B2AError(f"unknown voice engine {engine!r}")
