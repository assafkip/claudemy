"""`book2audio ui`: a small web server for this computer only, and the one page it serves (web/index.html).

Safety, because this server can spend money:
- it listens on 127.0.0.1 only, on a free port picked at start;
- every request needs the Host header of this server (blocks DNS rebinding) and, when the browser sends an
  Origin, that origin must be this server too (blocks other web pages); the API also needs the random token
  printed at start, so a page on another site cannot call it;
- API keys are typed into the page and kept in this process only: never written to disk or to the settings
  file, never sent back to the page, and scrubbed from every message; they are not put in the environment, so
  programs started from here (ffmpeg, Piper) never see them;
- a paid action is refused unless it carries the quote of the estimate the page showed for exactly that work;
- the page never sends a file path: books are referred to by their content hash, voices are checked against
  the lists the page was given, and output files get names made here.
"""
import argparse
import dataclasses
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote as urlquote, urlparse

from . import __version__, assemble, estimate, llm, pipeline, tts, voices
from .book import B2AError, Cancelled

KEY_ENV = {"elevenlabs": "ELEVENLABS_API_KEY", "google": "GOOGLE_TTS_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
PROVIDER_NAME = {"elevenlabs": "ElevenLabs", "google": "Google", "anthropic": "Anthropic"}
ENGINES = {"piper": "Free voice on this computer", "say": "Mac built-in voice (free)",
           "google": "Google Cloud voices (paid, online)", "elevenlabs": "ElevenLabs voices (paid, online)"}
CLAUDE_MODELS = {"claude-opus-5-5": "Opus: most careful, costs the most", "claude-sonnet-5-5": "Sonnet: in between",
                 "claude-haiku-5-5": "Haiku: cheapest"}
MAX_UPLOAD = 600 << 20
MAX_JSON = 64 << 10
KEY_SHAPE = re.compile(r"^[\x21-\x7e]{8,300}$")  # printable, no spaces or line breaks (they could split a header)
BOOK_ID = re.compile(r"^[0-9a-f]{16}$")
PIPER_FIX = '"{py}" -m pip install piper-tts'


def app_home() -> Path:
    if os.environ.get("BOOK2AUDIO_HOME"):
        return Path(os.environ["BOOK2AUDIO_HOME"])
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "book2audio"


def safe_name(text, fallback="audiobook") -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip(" .")[:80].strip(" .") or fallback
    return name + "_" if name.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)\d", name.upper()) \
        else name


def find_ffmpeg() -> None:
    """A program installed a minute ago is often missing from the PATH of an already-open window: look where
    the usual installers put ffmpeg and add that folder for this run only."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    local = Path(os.environ.get("LOCALAPPDATA") or "")
    spots = [*sorted((local / "Microsoft" / "WinGet" / "Packages").glob("Gyan.FFmpeg*/*/bin")),
             Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    for d in spots:
        if (d / "ffmpeg.exe").exists() or (d / "ffmpeg").exists():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            return


@dataclasses.dataclass
class LoadedBook:
    id: str
    name: str
    job: pipeline.Job
    book: object
    texts: dict  # chapter index -> what is spoken (rules only), so a checkbox click does not redo the work


@dataclasses.dataclass
class Plan:
    lb: LoadedBook
    idxs: list
    picks: list
    engine: str
    backend: tts.Backend
    llm_opts: dict | None
    price: float | None
    book: object  # the Book with any title/author the page changed


class App:
    def __init__(self, home: Path, piper_dir: Path | None = None):
        self.home = Path(home)
        self.piper_dir = Path(piper_dir or os.environ.get("PIPER_DATA_DIR") or self.home / "voices")
        music = Path.home() / "Music"  # easy to find; the app data folder is hidden on Windows
        self.out_dir = Path(os.environ.get("BOOK2AUDIO_OUT") or (music / "book2audio" if music.is_dir()
                                                                  else self.home / "audiobooks"))
        self.token = secrets.token_urlsafe(24)
        self.port = 0
        self.keys: dict[str, str] = {}  # memory only
        self.books: dict[str, LoadedBook] = {}
        self.current = None
        self.selection: list = []
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.run = {"status": "idle"}
        self.shutdown = lambda: None
        self._piper_ok = False

    # ---- keys and messages -------------------------------------------------------------------------------
    def key(self, provider):
        return self.keys.get(provider) or os.environ.get(KEY_ENV[provider]) or None

    def key_info(self) -> dict:
        return {p: {"has": bool(self.key(p)), "typed": p in self.keys, "environment": bool(os.environ.get(e))}
                for p, e in KEY_ENV.items()} | {"gcloud": bool(shutil.which("gcloud"))}

    def scrub(self, text) -> str:
        text = str(text)
        for secret in [*self.keys.values(), *(os.environ.get(e) for e in KEY_ENV.values())]:
            if secret and len(secret) >= 8:
                text = text.replace(secret, "(your key)")
        return text

    # ---- settings (prices and last choices: never keys) --------------------------------------------------
    def settings(self) -> dict:
        try:
            data = json.loads((self.home / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {"prices": data.get("prices") if isinstance(data.get("prices"), dict) else {},
                "choice": data.get("choice") if isinstance(data.get("choice"), dict) else {}}

    def save_settings(self, body: dict) -> dict:
        cur = self.settings()
        for p, v in (body.get("prices") or {}).items():
            if p in ("elevenlabs", "google"):
                if v in (None, ""):
                    cur["prices"].pop(p, None)
                elif isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 10000:
                    cur["prices"][p] = v
        choice = body.get("choice")
        if isinstance(choice, dict):  # plain values only, bounded
            cur["choice"] = {k: v for k, v in choice.items() if isinstance(k, str) and len(k) < 40
                             and (v is None or isinstance(v, (bool, int, float)) or (isinstance(v, str) and len(v) < 200))}
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.home / "settings.json.part"
        tmp.write_text(json.dumps(cur, indent=2), encoding="utf-8")
        os.replace(tmp, self.home / "settings.json")
        return cur

    # ---- books -------------------------------------------------------------------------------------------
    def add_book(self, name, tmp: Path, digest: str) -> LoadedBook:
        ext = Path(name).suffix.lower()
        bid = digest[:16]
        dest = self.home / "uploads" / bid / f"book{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            tmp.unlink(missing_ok=True)
        else:
            os.replace(tmp, dest)
        if bid not in self.books:
            job = pipeline.Job(self.home / "jobs" / bid, dest)
            try:
                book = pipeline.load_book(dest, job)
            except B2AError as e:  # the readers name the file on disk; the person knows it by its own name
                raise B2AError(f"This book could not be read. {str(e).replace(str(dest), Path(name).name)}")
            self.books[bid] = LoadedBook(bid, Path(name).name, job, book, {})
        self.current, self.selection = bid, []
        return self.books[bid]

    def get_book(self, bid) -> LoadedBook:
        if not isinstance(bid, str) or not BOOK_ID.match(bid) or bid not in self.books:
            raise B2AError("That book is not open any more. Drop the file onto the page again.")
        return self.books[bid]

    def summary(self, lb: LoadedBook | None) -> dict | None:
        if not lb:
            return None
        b = lb.book
        cover = None
        if b.cover and len(b.cover) < 4 << 20:
            import base64
            mime = "image/png" if b.cover_ext == "png" else "image/jpeg"
            cover = f"data:{mime};base64,{base64.b64encode(b.cover).decode()}"
        return {"id": lb.id, "file": lb.name, "title": b.title, "author": b.author, "cover": cover,
                "chapters": [{"i": i, "title": c.title, "words": len(c.text.split()), "skip": c.skip,
                              "empty": not c.text.strip()} for i, c in enumerate(b.chapters)]}

    # ---- turning a request from the page into work -------------------------------------------------------
    def plan(self, p: dict, chapters=True) -> Plan:
        lb = self.get_book(p.get("book"))
        idxs = p.get("chapters") or []
        if chapters:
            if not (isinstance(idxs, list) and idxs and all(isinstance(i, int) and not isinstance(i, bool)
                                                            and 0 <= i < len(lb.book.chapters) for i in idxs)):
                raise B2AError("Tick at least one chapter to narrate.")
            idxs = sorted(set(idxs))
            if any(not lb.book.chapters[i].text.strip() for i in idxs):
                raise B2AError("One of the ticked chapters has no text.")
        engine = p.get("engine")
        if engine not in ENGINES or (engine == "say" and sys.platform != "darwin"):
            raise B2AError("Pick a voice engine from the list.")
        voice, model, language = p.get("voice") or "", p.get("model") or "", p.get("language") or "en-US"
        voices.check_choice(engine, voice, model or None, language, self.piper_dir)
        backend = tts.make_backend(engine, voice, model or None, api_key=self.keys.get(engine))
        llm_opts = None
        c = p.get("claude") or {}
        if c.get("on"):
            if c.get("mode") not in ("faithful", "adapted") or c.get("model") not in CLAUDE_MODELS:
                raise B2AError("Pick one of the listed Claude options.")
            llm_opts = {"mode": c["mode"], "model": c["model"], "condense": bool(c.get("condense")) and c["mode"] == "adapted",
                        "client": None}
        price = p.get("price_per_1k")
        if price is not None and not (isinstance(price, (int, float)) and not isinstance(price, bool) and 0 <= price <= 10000):
            raise B2AError("The price must be a number such as 0.03.")
        book = dataclasses.replace(lb.book, title=str(p.get("title") or lb.book.title)[:300],
                                   author=str(p.get("author") if p.get("author") is not None else lb.book.author)[:300])
        picks = [(n, lb.book.chapters[i]) for n, i in enumerate(idxs, 1)] if chapters else []
        return Plan(lb, idxs, picks, engine, backend, llm_opts, price, book)

    def prepared(self, plan: Plan) -> list:
        out = []
        for (number, ch), i in zip(plan.picks, plan.idxs):
            if i not in plan.lb.texts:
                plan.lb.texts[i] = pipeline.rule_text(ch)
            out.append(pipeline.Prepared(number, ch.title, plan.lb.texts[i]))
        return out

    def quote(self, *parts) -> str:
        return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()[:16]

    def estimate(self, p: dict) -> dict:
        plan = self.plan(p)
        est = estimate.compute(self.prepared(plan), [], plan.lb.job, plan.backend, plan.llm_opts, plan.price,
                               every_backend=False)
        b = est["backends"][0]
        claude_usd = est["claude"] and est["claude"]["usd"]
        total_money = None if (b["paid"] and b["money"] is None) or (est["claude"] and claude_usd is None) \
            else (b["money"] or 0) + (claude_usd or 0)
        self.selection = plan.idxs
        return {
            "engine": plan.engine, "voice": plan.backend.voice, "paid": b["paid"] or bool(plan.llm_opts),
            "sent_to": est["sent_to"], "chars": est["chars"], "audio_minutes": est["minutes"],
            "voice_minutes": b["minutes"], "todo_chars": b["todo_chars"], "cached_chars": b["cached_chars"],
            "units": b["units"], "unit": b["unit"], "voice_paid": b["paid"], "voice_money": b["money"],
            "claude": est["claude"], "total_money": total_money, "chapters": est["chapters"],
            "missing_key": self.missing_key(plan),
            "quote": self.quote(plan.lb.id, plan.idxs, plan.engine, plan.backend.fingerprint(), b["todo_chars"],
                                plan.price, plan.llm_opts and [plan.llm_opts[k] for k in ("mode", "model", "condense")]),
        }

    def missing_key(self, plan: Plan) -> str | None:
        """The provider whose key must be typed before this plan can run, or None."""
        if plan.engine == "elevenlabs" and not self.key("elevenlabs"):
            return "elevenlabs"
        if plan.engine == "google" and not self.key("google") and not shutil.which("gcloud"):
            return "google"
        if plan.llm_opts and not self.key("anthropic"):
            return "anthropic"
        return None

    def piper_ready(self) -> bool:
        self._piper_ok = self._piper_ok or piper_installed()  # only a yes is remembered: it can be installed later
        return self._piper_ok

    def engine_ready(self, plan: Plan) -> None:
        """Raise, in plain words, if this voice engine cannot run right now."""
        if plan.engine == "piper":
            if not self.piper_ready():
                raise B2AError("The free voice program (Piper) is not installed yet. Open 'Get ready' at the top "
                               "of this page and follow the steps.")
        else:
            plan.backend.check()

    def preflight(self, plan: Plan) -> None:
        """Everything that can fail before anything is spent, in words for someone who never saw a terminal."""
        if (miss := self.missing_key(plan)):
            raise B2AError(f"Paste your {PROVIDER_NAME[miss]} key into the box first (see 'Keys' on this page).")
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise B2AError("ffmpeg, the program that builds the audiobook file, is missing. Open 'Get ready' at the "
                           "top of this page and follow the steps.")
        self.engine_ready(plan)

    # ---- voice samples -----------------------------------------------------------------------------------
    def sample_plan(self, p: dict):
        plan = self.plan(p, chapters=False)
        book = plan.lb.book
        i = p.get("chapter")
        if not (isinstance(i, int) and 0 <= i < len(book.chapters) and book.chapters[i].text.strip()):
            i = next((k for k, c in enumerate(book.chapters) if c.text.strip() and not c.skip), None)
        if i is None:
            raise B2AError("This book has no text to sample.")
        if i not in plan.lb.texts:
            plan.lb.texts[i] = pipeline.rule_text(book.chapters[i])
        text = pipeline.sample_text(plan.lb.texts[i])
        cached = tts.cache_path(plan.backend, text, self.home / "samples").exists()
        units = 0 if cached or not plan.backend.paid else len(text) * plan.backend.credit_per_char
        money = units / 1000 * plan.price if plan.backend.paid and plan.price is not None else None
        return plan, text, {"text": text, "chars": len(text), "cached": cached, "paid": plan.backend.paid,
                            "units": units, "unit": plan.backend.unit, "money": money,
                            "sent_to": [estimate.PROVIDER[plan.engine]] if plan.engine in estimate.PROVIDER else [],
                            "missing_key": self.missing_key(plan),
                            "quote": self.quote("sample", plan.engine, plan.backend.fingerprint(), text, plan.price)}

    def sample_audio(self, p: dict) -> tuple[bytes, str, bool]:
        plan, text, info = self.sample_plan(p)
        if info["paid"] and not info["cached"]:
            if p.get("quote") != info["quote"]:
                raise B2AError("Please look at the cost again and press the button once more.")
            if info["missing_key"]:
                raise B2AError(f"Paste your {PROVIDER_NAME[info['missing_key']]} key into the box first.")
        self.engine_ready(plan)
        path, hit = tts.synth_cached(plan.backend, text, self.home / "samples")
        path = playable(path)
        return path.read_bytes(), {".mp3": "audio/mpeg", ".wav": "audio/wav"}[path.suffix], hit

    # ---- the conversion ----------------------------------------------------------------------------------
    def output_path(self, lb: LoadedBook, title) -> Path:
        record = lb.job.root / "output.txt"
        if record.exists():
            name = record.read_text(encoding="utf-8").strip()
            if name and name == Path(name).name:
                return self.out_dir / name
        base, n = safe_name(title), 1
        while (self.out_dir / (f"{base}.m4b" if n == 1 else f"{base} ({n}).m4b")).exists():
            n += 1
        name = f"{base}.m4b" if n == 1 else f"{base} ({n}).m4b"
        record.write_text(name, encoding="utf-8")
        return self.out_dir / name

    def start(self, p: dict) -> dict:
        with self.lock:
            if self.run.get("status") == "running":
                raise B2AError("A conversion is already running. Wait for it, or press Stop.")
            plan = self.plan(p)
            est = self.estimate(p)
            if est["paid"] and p.get("quote") != est["quote"]:
                raise B2AError("The cost changed since you last looked at it. Please read it again and press the "
                               "button once more.")
            self.preflight(plan)
            if plan.llm_opts:
                plan.llm_opts["client"] = llm.make_client(self.key("anthropic"))
            self.out_dir.mkdir(parents=True, exist_ok=True)
            out = self.output_path(plan.lb, plan.book.title)
            self.cancel.clear()
            now = time.time()
            self.run = {"status": "running", "book": plan.lb.id, "title": plan.book.title, "chapters": len(plan.picks),
                        "started": now, "stage": "start", "message": "Getting started", "percent": 0, "eta": None,
                        "file": out.name, "titles": [ch.title for _, ch in plan.picks], "index": 0, "_t": now, "_done": 0,
                        "_fresh": 0, "_fresh_s": 0.0}
            threading.Thread(target=self._work, args=(plan, out), daemon=True).start()
        return self.snapshot()

    def _progress(self, e: dict) -> None:
        with self.lock:
            r, now = self.run, time.time()
            if e["stage"] == "voice":
                size = e["done"] - r["_done"]
                if not e["cached"]:
                    r["_fresh"] += size
                    r["_fresh_s"] += now - r["_t"]
                r["_done"], r["_t"] = e["done"], now
                r["percent"] = min(99, round(100 * e["done"] / max(1, e["total"])))
                r["eta"] = round((e["total"] - e["done"]) * r["_fresh_s"] / r["_fresh"]) if r["_fresh"] > 500 else None
                r["message"] = f"Making the voice: chapter {e['index']} of {e['count']}"
            elif e["stage"] == "mix":
                r["_t"] = now
                r["message"] = f"Finishing chapter {e['index']} of {e['count']}"
            elif e["stage"] == "text":
                r["message"] = f"Claude is preparing the text: chapter {e['index']} of {e['count']}"
                r["percent"] = round(100 * (e["index"] - 1) / e["count"] / 4)
            elif e["stage"] == "book":
                r["message"], r["percent"], r["eta"] = "Putting the audiobook together", 99, None
            r["stage"] = e["stage"]
            r["index"], r["chunk"], r["chunks"] = e.get("index", r.get("index")), e.get("chunk"), e.get("chunks")

    def _work(self, plan: Plan, out: Path) -> None:
        try:
            seconds = pipeline.convert(plan.book, plan.picks, plan.backend, plan.lb.job, out, plan.llm_opts,
                                       progress=self._progress, cancel=self.cancel)
            result = {"status": "done", "message": "Your audiobook is ready.", "percent": 100, "eta": None,
                      "minutes": round(seconds / 60), "output": str(out)}
        except Cancelled:
            result = {"status": "stopped", "eta": None, "message": "Stopped. Nothing is lost: press Convert again "
                      "to carry on where it left off."}
        except B2AError as e:
            result = {"status": "failed", "eta": None, "message": self.scrub(e) + " What was finished is saved: "
                      "fix the problem and press Convert again to carry on."}
        except Exception as e:  # a bug: say so plainly, keep the details for whoever reads the black window
            traceback.print_exc()
            result = {"status": "failed", "eta": None, "message": "Something unexpected went wrong "
                      f"({self.scrub(type(e).__name__)}). What was finished is saved; try pressing Convert again."}
        with self.lock:
            self.run.update(result, finished=time.time())

    def snapshot(self) -> dict:
        with self.lock:
            r = {k: v for k, v in self.run.items() if not k.startswith("_")}
            if "started" in r:
                r["elapsed"] = round(r.get("finished", time.time()) - r["started"])
            r.pop("output", None)
            r["has_output"] = bool(self.run.get("output")) and Path(self.run["output"]).is_file()
            return r

    def open_folder(self) -> None:
        out = Path(self.run.get("output") or "")
        target = out if out.is_file() else self.out_dir
        if not target.exists():
            raise B2AError("There is nothing to show yet.")
        if sys.platform == "win32":
            subprocess.Popen(["explorer", f"/select,{target}"] if target.is_file() else ["explorer", str(target)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)] if target.is_file() else ["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target.parent if target.is_file() else target)])

    # ---- first-run checklist -----------------------------------------------------------------------------
    def setup(self) -> list:
        win = sys.platform == "win32"
        mac = sys.platform == "darwin"
        have_piper, have_ffmpeg = self.piper_ready(), bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        installed = voices.piper_voices(self.piper_dir)
        items = [
            {"id": "ffmpeg", "label": "ffmpeg (builds the audiobook file)", "ok": have_ffmpeg, "required": True,
             "detail": "Found." if have_ffmpeg else "Not found. Every audiobook needs it.",
             "fix": None if have_ffmpeg else (
                 "Open the Start menu, type  cmd , open Command Prompt, paste this line and press Enter. When it "
                 "finishes, close this program and start it again:\n\nwinget install Gyan.FFmpeg" if win else
                 "Open the Terminal app, paste this line and press Enter, then start this program again:\n\n"
                 "brew install ffmpeg" if mac else "Install ffmpeg with your package manager, e.g.  sudo apt install ffmpeg")},
            {"id": "piper", "label": "Free voice program (Piper)", "ok": have_piper and bool(installed), "required": False,
             "detail": ("Installed, with " + str(len(installed)) + " voice(s)." if have_piper and installed else
                        "The program is installed, but no voice is downloaded yet. Use the button in the voice list "
                        "to get one." if have_piper else "Not installed. Needed only for the free voice."),
             "fix": None if have_piper else ("Paste this into Command Prompt (Windows) or Terminal (Mac), press Enter, "
                                             "then start this program again:\n\n" + PIPER_FIX.format(py=sys.executable))},
        ]
        for p, extra in (("elevenlabs", ""), ("google", " Or sign in with Google's gcloud tool instead."),
                         ("anthropic", "")):
            k = self.key_info()
            ok = k[p]["has"] or (p == "google" and k["gcloud"])
            items.append({"id": p, "label": f"{PROVIDER_NAME[p]} key", "ok": bool(ok), "required": False,
                          "detail": ("Ready." if ok else "Not added. Only needed if you choose " + (
                              "the Claude clean-up." if p == "anthropic" else f"{PROVIDER_NAME[p]} voices.") + extra),
                          "fix": None})
        if importlib.util.find_spec("anthropic") is None:
            items.append({"id": "anthropic-sdk", "label": "Claude clean-up add-on", "ok": False, "required": False,
                          "detail": "Not installed. Needed only for the optional Claude clean-up.",
                          "fix": "Paste into Command Prompt or Terminal, press Enter, then start this program again:"
                                 f"\n\n\"{sys.executable}\" -m pip install anthropic"})
        return items

    def install_piper_voice(self, voice) -> None:
        if not (isinstance(voice, str) and voices.PIPER_NAME.match(voice)):
            raise B2AError("That is not a Piper voice name.")
        if not self.piper_ready():
            raise B2AError("The free voice program (Piper) is not installed yet. See 'Get ready' at the top.")
        self.piper_dir.mkdir(parents=True, exist_ok=True)
        # piper.download_voices saves into the folder it runs in (as the README says), so run it in the voice folder
        r = subprocess.run([sys.executable, "-m", "piper.download_voices", voice], cwd=self.piper_dir,
                           capture_output=True, text=True, errors="replace", timeout=900)
        if r.returncode or not (self.piper_dir / f"{voice}.onnx").exists():
            raise B2AError("The voice could not be downloaded. Check your internet connection and try again."
                           f" ({(r.stderr or r.stdout).strip()[-200:]})")


def playable(path: Path) -> Path:
    """Browsers play wav and mp3; the Mac voices write aiff, so that one is converted (once)."""
    if path.suffix != ".aiff":
        return path
    wav = path.with_suffix(".wav")
    if not wav.exists():
        assemble.require_ffmpeg()
        assemble._run(["ffmpeg", "-nostdin", "-hide_banner", "-y", "-i", str(path), str(wav)])
    return wav


def piper_installed() -> bool:
    try:
        return subprocess.run([sys.executable, "-m", "piper", "--help"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "book2audio"
    app: App  # set on the subclass made by make_server()

    def log_message(self, *args):  # the address line carries the token; say nothing
        pass

    # ---- plumbing ----------------------------------------------------------------------------------------
    def _send(self, status, body: bytes, ctype, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; "
                         "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def _fail(self, status, message):
        self._json({"error": self.app.scrub(message)}, status)

    def _allowed(self) -> bool:
        """Host must be this server (DNS rebinding); an Origin, when sent, must be this server too."""
        ok_hosts = {f"127.0.0.1:{self.app.port}", f"localhost:{self.app.port}"}
        origin = self.headers.get("Origin")
        return (self.headers.get("Host") in ok_hosts
                and (origin is None or origin in {f"http://{h}" for h in ok_hosts})
                and self.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none"))

    def _token_ok(self, supplied) -> bool:
        return bool(supplied) and hmac.compare_digest(str(supplied), self.app.token)

    def _json_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_JSON:
            raise B2AError("That request is too big.")
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise B2AError("The page sent something the program could not read. Reload the page.")
        if not isinstance(data, dict):
            raise B2AError("The page sent something the program could not read. Reload the page.")
        return data

    def _dispatch(self, method):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if not self._allowed():
            return self._send(403, b"Not allowed.", "text/plain")
        try:
            if method == "GET" and url.path == "/":
                if not self._token_ok(query.get("t")):
                    return self._send(403, "<h1>Book2Audio</h1><p>This link is missing its security code. Close "
                                      "this tab and start Book2Audio again from its launcher.</p>".encode(), "text/html")
                return self._send(200, (Path(__file__).parent / "web" / "index.html").read_bytes(),
                                  "text/html; charset=utf-8")
            if method == "GET" and url.path == "/app.js":  # code, not data: no token, still Host-checked above
                return self._send(200, (Path(__file__).parent / "web" / "app.js").read_bytes(),
                                  "text/javascript; charset=utf-8")
            if method == "GET" and url.path == "/api/download":  # a plain link can't send headers: token in the query
                if not self._token_ok(query.get("t")):
                    return self._send(403, b"Not allowed.", "text/plain")
                return self._download(query.get("id"))
            if not url.path.startswith("/api/") or not self._token_ok(self.headers.get("X-B2A-Token")):
                return self._send(403 if url.path.startswith("/api/") else 404, b"Not allowed.", "text/plain")
            route = {("GET", "/api/state"): lambda: self._state(),
                     ("GET", "/api/setup"): lambda: {"items": self.app.setup()},
                     ("GET", "/api/voices"): lambda: self._voices(query),
                     ("POST", "/api/upload"): lambda: self._upload(query.get("name", "")),
                     ("POST", "/api/key"): lambda: self._set_key(self._json_body()),
                     ("POST", "/api/settings"): lambda: self.app.save_settings(self._json_body()),
                     ("POST", "/api/estimate"): lambda: self.app.estimate(self._json_body()),
                     ("POST", "/api/sample/quote"): lambda: self.app.sample_plan(self._json_body())[2],
                     ("POST", "/api/sample"): lambda: self._sample(),
                     ("POST", "/api/convert"): lambda: {"run": self.app.start(self._json_body())},
                     ("POST", "/api/cancel"): lambda: self._cancel(),
                     ("POST", "/api/open-folder"): lambda: self._after(self.app.open_folder),
                     ("POST", "/api/piper/install"): lambda: self._after(
                         lambda: self.app.install_piper_voice(self._json_body().get("voice"))),
                     ("POST", "/api/quit"): lambda: self._quit()}.get((method, url.path))
            if route is None:
                return self._send(404, b"Not found.", "text/plain")
            result = route()
            if isinstance(result, tuple):  # (bytes, content type): a voice sample
                return self._send(200, result[0], result[1], [("X-Sample-Cached", "1" if result[2] else "0")])
            self._json(result)
        except B2AError as e:
            self._fail(400, str(e))
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception as e:  # a bug; the details stay in this window, never in the page
            traceback.print_exc()
            self._fail(500, f"Something unexpected went wrong ({type(e).__name__}). Try again.")

    do_GET = lambda self: self._dispatch("GET")
    do_POST = lambda self: self._dispatch("POST")

    # ---- routes ------------------------------------------------------------------------------------------
    def _state(self):
        a = self.app
        lb = a.books.get(a.current)
        return {"version": __version__, "platform": {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux"),
                "keys": a.key_info(), "settings": a.settings(), "book": a.summary(lb), "selection": a.selection,
                "run": a.snapshot(), "engines": [{"id": k, "label": v} for k, v in ENGINES.items()
                                                 if k != "say" or sys.platform == "darwin"],
                "claude_models": [{"id": k, "label": v} for k, v in CLAUDE_MODELS.items()],
                "folder": str(a.out_dir)}

    def _voices(self, q):
        a = self.app
        engine, language = q.get("engine", ""), q.get("language") or "en-US"
        try:
            return voices.catalog(engine, language, a.keys.get("elevenlabs") or os.environ.get("ELEVENLABS_API_KEY"),
                                  a.piper_dir)
        except B2AError as e:
            if engine != "elevenlabs":
                raise
            out = voices.catalog(engine, language, None, a.piper_dir)
            out["note"] = "Could not load the voices on your account: " + a.scrub(e)
            return out

    def _upload(self, name):
        a = self.app
        if Path(name).suffix.lower() not in (".epub", ".pdf"):
            raise B2AError("Please choose a book that ends in .epub or .pdf.")
        left = int(self.headers.get("Content-Length") or 0)
        if not 0 < left <= MAX_UPLOAD:
            raise B2AError("That file is empty or too big (the limit is 600 MB).")
        (a.home / "uploads").mkdir(parents=True, exist_ok=True)
        tmp, digest = a.home / "uploads" / f"incoming-{secrets.token_hex(4)}", hashlib.sha256()
        with open(tmp, "wb") as f:
            while left:
                block = self.rfile.read(min(1 << 20, left))
                if not block:
                    break
                f.write(block)
                digest.update(block)
                left -= len(block)
        if left:
            tmp.unlink(missing_ok=True)
            raise B2AError("The upload was cut off. Please try again.")
        try:
            with a.lock:
                return {"book": a.summary(a.add_book(name, tmp, digest.hexdigest()))}
        finally:
            tmp.unlink(missing_ok=True)

    def _set_key(self, body):
        provider, key = body.get("provider"), body.get("key")
        if provider not in KEY_ENV:
            raise B2AError("Unknown provider.")
        if not key:
            self.app.keys.pop(provider, None)
        elif isinstance(key, str) and KEY_SHAPE.match(key.strip()):
            self.app.keys[provider] = key.strip()
        else:
            raise B2AError("That does not look like a key. Copy it again from the provider's website, without spaces.")
        return {"keys": self.app.key_info()}

    def _sample(self):
        return self.app.sample_audio(self._json_body())

    def _cancel(self):
        with self.app.lock:
            if self.app.run.get("status") == "running":
                self.app.cancel.set()
                self.app.run["message"] = "Stopping after the part being made now"
        return {"run": self.app.snapshot()}

    def _after(self, fn):
        fn()
        return {"ok": True}

    def _quit(self):
        if self.app.run.get("status") == "running":
            raise B2AError("A conversion is running. Press Stop first, or wait for it to finish.")
        threading.Thread(target=self.app.shutdown, daemon=True).start()
        return {"ok": True}

    def _download(self, bid):
        a = self.app
        record = a.get_book(bid).job.root / "output.txt"
        name = record.read_text(encoding="utf-8").strip() if record.exists() else ""
        path = a.out_dir / name if name and name == Path(name).name else None
        if not path or not path.is_file():
            return self._send(404, b"There is no finished audiobook for this book yet.", "text/plain")
        self.send_response(200)
        self.send_header("Content-Type", "audio/mp4")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{urlquote(path.name)}")
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1 << 20)


def make_server(app: App, port=0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), type("BoundHandler", (Handler,), {"app": app}))
    app.port = server.server_address[1]
    app.shutdown = server.shutdown
    return server


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="book2audio ui", description="Open the Book2Audio page in your browser. "
                                 "It runs on this computer only; closing this window stops it.")
    ap.add_argument("--port", type=int, default=0, help="a fixed port (default: any free one)")
    ap.add_argument("--no-browser", action="store_true", help="only print the link")
    ap.add_argument("--home", help="where books, voices and settings are kept")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    find_ffmpeg()
    app = App(Path(args.home) if args.home else app_home())
    os.environ.setdefault("PIPER_DATA_DIR", str(app.piper_dir))
    try:
        server = make_server(app, args.port)
    except OSError as e:
        print(f"error: could not start (port {args.port} is busy?): {e}", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{app.port}/?t={app.token}"
    print(f"Book2Audio is running. Your browser should open by itself.\nIf it does not, open this link:\n\n  {url}\n\n"
          "Keep this window open while you use it. Close it, or press Ctrl+C, to stop.", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
    return 0
