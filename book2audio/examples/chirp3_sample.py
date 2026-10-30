"""Ask Google Cloud Text-to-Speech for a short Chirp 3 HD sample and save it as an MP3.

Standard library only, and independent of the rest of book2audio, so it doubles as a quick check that
your credentials and the Text-to-Speech API work before you spend anything on a whole book.

    python examples/chirp3_sample.py
    python examples/chirp3_sample.py --voice en-US-Chirp3-HD-Leda --voice en-US-Chirp3-HD-Kore
    python examples/chirp3_sample.py --list
    python examples/chirp3_sample.py "Any text you would like to hear."

Credentials, either one:
    GOOGLE_TTS_API_KEY   an API key allowed to call the Cloud Text-to-Speech API
    or the gcloud CLI after `gcloud auth login` (GOOGLE_CLOUD_PROJECT names the quota project)

The text is sent to Google, and Chirp 3 HD is billed per character (the default sample is about 100).
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
SAMPLE = "Alice was beginning to get very tired of sitting by her sister on the bank, and of having nothing to do."
# The 30 voices listed on https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd (use as en-US-Chirp3-HD-<name>).
VOICES = {
    "female": "Achernar Aoede Autonoe Callirrhoe Despina Erinome Gacrux Kore Laomedeia Leda Pulcherrima Sulafat "
              "Vindemiatrix Zephyr".split(),
    "male": "Achird Algenib Algieba Alnilam Charon Enceladus Fenrir Iapetus Orus Puck Rasalgethi Sadachbia "
            "Sadaltager Schedar Umbriel Zubenelgenubi".split(),
}


def auth_headers() -> dict:
    key = os.environ.get("GOOGLE_TTS_API_KEY")
    if key:
        return {"x-goog-api-key": key}
    gcloud = shutil.which("gcloud")
    if not gcloud:
        sys.exit("error: set GOOGLE_TTS_API_KEY, or install the gcloud CLI and run: gcloud auth login")
    r = subprocess.run([gcloud, "auth", "print-access-token"], capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        sys.exit(f"error: gcloud gave no access token ({r.stderr.strip()[-200:]}). Run: gcloud auth login")
    headers = {"Authorization": f"Bearer {r.stdout.strip()}"}
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        headers["x-goog-user-project"] = os.environ["GOOGLE_CLOUD_PROJECT"]
    return headers


def request_sample(text: str, voice: str) -> bytes:
    """One synthesize call -> MP3 bytes."""
    language = "-".join(voice.split("-")[:2])  # en-US-Chirp3-HD-Charon -> en-US
    body = {"input": {"text": text}, "voice": {"languageCode": language, "name": voice},
            "audioConfig": {"audioEncoding": "MP3"}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **auth_headers()})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return base64.b64decode(json.load(r)["audioContent"])
    except urllib.error.HTTPError as e:  # Google's message says what is wrong (API not enabled, bad key, ...)
        sys.exit(f"error: HTTP {e.code} {e.reason}: {e.read().decode('utf-8', 'replace').strip()[:400]}")
    except urllib.error.URLError as e:
        sys.exit(f"error: could not reach Google: {e}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("text", nargs="?", default=SAMPLE, help="text to speak (default: a line from Alice in Wonderland)")
    p.add_argument("--voice", action="append", help="voice name; repeat to compare several (default: Charon)")
    p.add_argument("--outdir", default=".", help="where to save the MP3 files")
    p.add_argument("--list", action="store_true", help="list the Chirp 3 HD voice names and exit")
    args = p.parse_args(argv)
    if args.list:
        for gender, names in VOICES.items():
            print(f"{gender}: {', '.join(names)}")
        return 0
    for voice in args.voice or ["en-US-Chirp3-HD-Charon"]:
        audio = request_sample(args.text, voice)
        out = Path(args.outdir) / f"chirp3-{voice.rsplit('-', 1)[-1]}.mp3"
        out.write_bytes(audio)
        print(f"{voice}: wrote {out} ({len(audio):,} bytes, {len(args.text)} characters billed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
