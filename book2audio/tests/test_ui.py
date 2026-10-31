"""The local web server: who may call it, what it refuses, and a book going through it. No network, no paid calls."""
import http.client
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (sets up sys.path)
from helpers import FIXTURES, WORDS, make_epub

from book2audio import tts, ui, voices
from book2audio.book import B2AError

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
SECRET = "sk-super-secret-key-1234567890"


class Server(unittest.TestCase):
    """A real server on a free port, with a temporary home and fake voice engines."""

    tone = b""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        if HAVE_FFMPEG:
            wav = Path(cls.td.name) / "tone.wav"
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "sine=frequency=300:duration=1", str(wav)], check=True)
            cls.tone = wav.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(dir=self.td.name))
        (self.dir / "voices").mkdir()
        (self.dir / "voices" / "en_US-test-medium.onnx").write_bytes(b"x")
        env = mock.patch.dict("os.environ")  # the real keys on this computer must never leak into a test
        env.start()
        self.addCleanup(env.stop)
        for var in ui.KEY_ENV.values():
            os.environ.pop(var, None)
        self.calls = []
        real_which = shutil.which
        for target, attr, new in ((ui, "piper_installed", lambda: True), (tts.Piper, "check", lambda self: None),
                                  (tts.Piper, "synth", self.fake_synth), (tts.GoogleChirp3, "synth", self.fake_synth),
                                  (shutil, "which", lambda name, *a, **k: None if name == "gcloud" else real_which(name, *a, **k))):
            p = mock.patch.object(target, attr, new)
            p.start()
            self.addCleanup(p.stop)
        self.app = ui.App(self.dir / "home", piper_dir=self.dir / "voices")
        self.app.out_dir = self.dir / "out"
        self.server = ui.make_server(self.app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.host = f"127.0.0.1:{self.app.port}"

    def fake_synth(self, text, before="", after=""):
        self.calls.append(text)
        return self.tone or b"RIFFfake"

    # ---- tiny http client --------------------------------------------------------------------------------
    def call(self, method, path, body=None, token=True, headers=None, raw=None):
        h = {"Host": self.host}
        if token:
            h["X-B2A-Token"] = self.app.token
        h.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            h["Content-Length"] = str(len(data))
        conn = http.client.HTTPConnection("127.0.0.1", self.app.port, timeout=60)
        conn.request(method, path, data, h)
        r = conn.getresponse()
        payload = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), payload

    def api(self, method, path, body=None, **kw):
        status, headers, payload = self.call(method, path, body, **kw)
        return status, (json.loads(payload) if headers.get("Content-Type", "").startswith("application/json") else payload)

    def upload(self, path, name=None):
        name = name or Path(path).name
        return self.api("POST", f"/api/upload?name={name}", raw=Path(path).read_bytes())

    def small_book(self, n=3):
        pages = {f"c{i}.xhtml": f"<h1>Chapter {i}</h1><p>{WORDS.replace('quick', f'quick{i}') * 8}</p>"
                 for i in range(1, n + 1)}
        epub = make_epub(self.dir / "tiny.epub", pages, [(f"Chapter {i}", f"c{i}.xhtml") for i in range(1, n + 1)],
                         title="Tiny Book", author="Ann Author")
        status, out = self.upload(epub)
        self.assertEqual(status, 200, out)
        return out["book"]

    def request(self, book, engine="piper", **extra):
        voice = {"piper": "en_US-test-medium", "google": "en-US-Chirp3-HD-Kore"}[engine]
        return {"book": book["id"], "chapters": [c["i"] for c in book["chapters"] if not c["skip"]], "engine": engine,
                "voice": voice, "model": "", "language": "en-US", **extra}

    def wait_for(self, *statuses, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            run = self.api("GET", "/api/state")[1]["run"]
            if run["status"] in statuses:
                return run
            time.sleep(0.1)
        self.fail(f"run never reached {statuses}: {run}")


class Safety(Server):
    def test_the_page_needs_the_token(self):
        self.assertEqual(self.call("GET", "/", token=False)[0], 403)
        self.assertEqual(self.call("GET", "/?t=wrong", token=False)[0], 403)
        status, headers, body = self.call("GET", f"/?t={self.app.token}", token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"Book2Audio", body)
        self.assertIn("no-referrer", headers["Referrer-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_the_api_needs_the_token(self):
        for token in (False, "wrong"):
            headers = {"X-B2A-Token": token} if token else {}
            self.assertEqual(self.call("GET", "/api/state", token=False, headers=headers)[0], 403)
        self.assertEqual(self.api("GET", "/api/state")[0], 200)

    def test_another_website_cannot_call_it(self):
        for headers in ({"Host": "evil.example:80"}, {"Host": f"evil.example:{self.app.port}"},
                        {"Origin": "https://evil.example"}, {"Origin": "http://localhost:1"},
                        {"Sec-Fetch-Site": "cross-site"}):
            status, _, _ = self.call("POST", "/api/cancel", {}, headers=headers)
            self.assertEqual(status, 403, headers)
        self.assertEqual(self.call("POST", "/api/cancel", {}, headers={"Origin": f"http://{self.host}"})[0], 200)
        self.assertEqual(self.call("GET", "/api/state", headers={"Host": f"localhost:{self.app.port}"})[0], 200)

    def test_no_cross_origin_permission_is_ever_granted(self):
        _, headers, _ = self.call("GET", "/api/state")
        self.assertFalse([h for h in headers if h.lower().startswith("access-control")])
        self.assertEqual(self.call("OPTIONS", "/api/convert")[0], 501)

    def test_it_listens_on_this_computer_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_a_key_is_kept_in_memory_and_never_sent_back(self):
        status, out = self.api("POST", "/api/key", {"provider": "elevenlabs", "key": SECRET})
        self.assertEqual((status, out["keys"]["elevenlabs"]["typed"]), (200, True))
        everything = b"".join(self.call("GET", p)[2] for p in ("/api/state", "/api/setup", "/api/voices?engine=google"))
        self.assertNotIn(SECRET.encode(), everything)
        self.assertEqual(self.app.keys["elevenlabs"], SECRET)
        self.app.save_settings({"prices": {"elevenlabs": 0.3}, "choice": {"engine": "elevenlabs"}})
        for f in self.app.home.rglob("*"):
            if f.is_file():
                self.assertNotIn(SECRET.encode(), f.read_bytes(), f)
        self.api("POST", "/api/key", {"provider": "elevenlabs", "key": ""})
        self.assertNotIn("elevenlabs", self.app.keys)

    def test_a_bad_key_is_refused_without_echoing_it(self):
        for bad in ("short", "has space in it 12345", "line\r\nbreak-12345", 12345678):
            status, body = self.call("POST", "/api/key", {"provider": "google", "key": bad})[::2]
            self.assertEqual(status, 400)
            self.assertNotIn(b"break-12345", body)
        self.assertEqual(self.api("POST", "/api/key", {"provider": "nope", "key": SECRET})[0], 400)

    def test_error_messages_hide_keys(self):
        self.assertEqual(self.api("POST", "/api/key", {"provider": "google", "key": SECRET})[0], 200)
        self.assertNotIn(SECRET, self.app.scrub(f"Google said: bad key {SECRET}"))

    def test_nothing_that_looks_like_a_path_gets_through(self):
        book = self.small_book()
        for patch in ({"book": "../../etc/passwd"}, {"book": "0" * 16}, {"voice": "../../evil"},
                      {"voice": "C:\\evil.onnx"}, {"chapters": [999]}, {"chapters": ["1"]}, {"chapters": []},
                      {"engine": "../x"}):
            status, out = self.api("POST", "/api/estimate", {**self.request(book), **patch})
            self.assertEqual(status, 400, patch)
            self.assertIn("error", out)
        eleven = {**self.request(book), "engine": "elevenlabs", "model": "eleven_multilingual_v2"}
        for voice in ("../../v1/user", "abc/def", "a" * 5, ""):
            self.assertEqual(self.api("POST", "/api/estimate", {**eleven, "voice": voice})[0], 400, voice)
        self.assertEqual(self.call("GET", f"/api/download?id=../x&t={self.app.token}", token=False)[0], 400)
        self.assertEqual(self.call("GET", "/api/download?id=aaaaaaaaaaaaaaaa", token=False)[0], 403)


class Books(Server):
    def test_a_book_is_read_and_its_chapters_listed_with_reasons(self):
        status, out = self.upload(FIXTURES / "alice.epub")
        self.assertEqual(status, 200)
        book = out["book"]
        self.assertIn("Alice", book["title"])
        self.assertTrue(book["cover"] is None or book["cover"].startswith("data:image/"))
        skipped = {c["title"]: c["skip"] for c in book["chapters"] if c["skip"]}
        self.assertEqual(skipped["Contents"], "front/back matter")
        self.assertEqual(len([c for c in book["chapters"] if not c["skip"]]), 12)
        again = self.upload(FIXTURES / "alice.epub")[1]["book"]
        self.assertEqual(again["id"], book["id"], "the same file is the same book")
        self.assertEqual(self.api("GET", "/api/state")[1]["book"]["id"], book["id"], "a refresh gets it back")

    def test_only_epub_and_pdf_and_only_real_ones(self):
        status, out = self.api("POST", "/api/upload?name=notes.txt", raw=b"hello")
        self.assertEqual(status, 400)
        self.assertIn(".epub or .pdf", out["error"])
        status, out = self.api("POST", "/api/upload?name=fake.epub", raw=b"not a zip")
        self.assertEqual(status, 400)
        self.assertIn("cannot open", out["error"])
        self.assertIn("fake.epub", out["error"])
        self.assertNotIn(str(self.dir), out["error"], "the person knows the file by its own name")
        self.assertEqual(self.api("POST", "/api/upload?name=empty.epub", raw=b"")[0], 400)
        self.assertEqual(list((self.app.home / "uploads").glob("incoming-*")), [], "no half-saved files left")

    def test_the_page_never_names_a_file_on_disk(self):
        book = self.small_book()
        self.assertNotIn(str(self.dir), json.dumps(self.api("GET", "/api/state")[1]))
        self.assertEqual(book["file"], "tiny.epub")


class Choices(Server):
    def test_voice_lists_per_engine(self):
        google = self.api("GET", "/api/voices?engine=google&language=de-DE")[1]
        self.assertEqual(len(google["voices"]), 30)
        self.assertTrue(all(v["id"].startswith("de-DE-Chirp3-HD-") for v in google["voices"]))
        self.assertIn("en-GB", [lang["id"] for lang in google["languages"]])
        eleven = self.api("GET", "/api/voices?engine=elevenlabs")[1]
        self.assertTrue(eleven["voices"] and "key" in eleven["note"])
        self.assertIn("eleven_v3", [m["id"] for m in eleven["models"]])
        piper = self.api("GET", "/api/voices?engine=piper")[1]
        self.assertEqual([v["id"] for v in piper["voices"]], ["en_US-test-medium"])
        self.assertEqual(self.api("GET", "/api/voices?engine=nope")[0], 400)

    def test_elevenlabs_voices_come_from_the_account_when_a_key_is_typed(self):
        self.api("POST", "/api/key", {"provider": "elevenlabs", "key": SECRET})
        with mock.patch.object(voices, "elevenlabs_voices", return_value=[{"id": "abc1234567", "name": "Mine",
                                                                           "detail": ""}]) as get:
            out = self.api("GET", "/api/voices?engine=elevenlabs")[1]
        get.assert_called_once_with(SECRET)
        self.assertEqual([v["name"] for v in out["voices"]], ["Mine"])
        with mock.patch.object(voices, "elevenlabs_voices", side_effect=B2AError(f"ElevenLabs refused {SECRET}")):
            out = self.api("GET", "/api/voices?engine=elevenlabs")[1]
        self.assertNotIn(SECRET, json.dumps(out))
        self.assertIn("Could not load", out["note"])

    def test_prices_and_choices_are_remembered_without_keys(self):
        self.api("POST", "/api/settings", {"prices": {"google": 0.03, "bogus": 1, "elevenlabs": -4},
                                           "choice": {"engine": "google", "nested": {"a": 1}}})
        saved = self.api("GET", "/api/state")[1]["settings"]
        self.assertEqual(saved, {"prices": {"google": 0.03}, "choice": {"engine": "google"}})
        self.assertEqual(self.api("POST", "/api/settings", {"prices": {"google": None}})[1]["prices"], {})


class Estimates(Server):
    def test_free_voice_stays_on_this_computer_and_costs_nothing(self):
        est = self.api("POST", "/api/estimate", self.request(self.small_book()))[1]
        self.assertEqual((est["paid"], est["sent_to"], est["voice_paid"]), (False, [], False))
        self.assertEqual(est["total_money"], 0)
        self.assertGreater(est["chars"], 3000)
        self.assertEqual(len(est["chapters"]), 3)

    def test_cloud_voice_names_where_the_text_goes_and_what_it_costs(self):
        book = self.small_book()
        est = self.api("POST", "/api/estimate", {**self.request(book, "google"), "price_per_1k": 0.03})[1]
        self.assertEqual((est["paid"], est["sent_to"], est["unit"]), (True, ["Google Cloud"], "characters"))
        self.assertAlmostEqual(est["voice_money"], est["units"] / 1000 * 0.03)
        self.assertEqual(est["missing_key"], "google")
        self.assertIsNone(self.api("POST", "/api/estimate", self.request(book, "google"))[1]["total_money"],
                          "no price entered: credits are shown, money is not guessed")
        self.api("POST", "/api/key", {"provider": "google", "key": SECRET})
        self.assertIsNone(self.api("POST", "/api/estimate", self.request(book, "google"))[1]["missing_key"])

    def test_claude_clean_up_adds_anthropic_and_a_dollar_figure(self):
        claude = {"on": True, "mode": "faithful", "model": "claude-haiku-5-5", "condense": False}
        est = self.api("POST", "/api/estimate", {**self.request(self.small_book()), "claude": claude})[1]
        self.assertEqual((est["paid"], est["sent_to"], est["missing_key"]), (True, ["Anthropic"], "anthropic"))
        self.assertGreater(est["claude"]["usd"], 0)
        self.assertEqual(self.api("POST", "/api/estimate", {**self.request(self.small_book()),
                                                            "claude": {**claude, "model": "gpt"}})[0], 400)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class Samples(Server):
    def test_a_free_sample_plays_and_costs_nothing(self):
        book = self.small_book()
        q = self.api("POST", "/api/sample/quote", self.request(book))[1]
        self.assertTrue(100 <= q["chars"] <= 200, q["chars"])
        self.assertEqual((q["paid"], q["units"], q["sent_to"]), (False, 0, []))
        status, headers, audio = self.call("POST", "/api/sample", self.request(book))
        self.assertEqual((status, headers["Content-Type"], audio[:4]), (200, "audio/wav", b"RIFF"))
        self.assertEqual(self.calls, [q["text"]])
        self.assertIn("Chapter", q["text"] + "Chapter", "the sample comes from the book's own text")

    def test_a_paid_sample_needs_the_cost_shown_first_then_replays_free(self):
        book = self.small_book()
        self.api("POST", "/api/key", {"provider": "google", "key": SECRET})
        req = {**self.request(book, "google"), "price_per_1k": 0.03}
        q = self.api("POST", "/api/sample/quote", req)[1]
        self.assertEqual((q["paid"], q["cached"], q["sent_to"]), (True, False, ["Google Cloud"]))
        self.assertEqual(q["units"], q["chars"])
        self.assertAlmostEqual(q["money"], q["chars"] / 1000 * 0.03)
        for body in (req, {**req, "quote": "stale"}):
            status, out = self.api("POST", "/api/sample", body)
            self.assertEqual(status, 400)
            self.assertIn("cost", out["error"])
        self.assertEqual(self.calls, [], "nothing was spent")
        self.assertEqual(self.call("POST", "/api/sample", {**req, "quote": q["quote"]})[0], 200)
        self.assertEqual(len(self.calls), 1)
        again = self.api("POST", "/api/sample/quote", req)[1]
        self.assertEqual((again["cached"], again["units"]), (True, 0))
        self.assertEqual(self.call("POST", "/api/sample", req)[0], 200, "a saved sample needs no confirmation")
        self.assertEqual(len(self.calls), 1, "replay is free")

    def test_a_paid_sample_without_a_key_says_what_to_do(self):
        book = self.small_book()
        req = self.request(book, "google")
        q = self.api("POST", "/api/sample/quote", req)[1]
        status, out = self.api("POST", "/api/sample", {**req, "quote": q["quote"]})
        self.assertEqual(status, 400)
        self.assertIn("Google key", out["error"])
        self.assertEqual(self.calls, [])


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class Conversion(Server):
    def chapters(self, path):
        out = subprocess.run(["ffprobe", "-v", "error", "-of", "json", "-show_chapters", str(path)],
                             capture_output=True, text=True, check=True).stdout
        return [c["tags"]["title"] for c in json.loads(out)["chapters"]]

    def test_a_chapter_goes_all_the_way_to_a_downloadable_m4b(self):
        book = self.small_book()
        req = {**self.request(book), "chapters": [book["chapters"][1]["i"]]}
        status, out = self.api("POST", "/api/convert", req)
        self.assertEqual(status, 200, out)
        run = self.wait_for("done")
        self.assertEqual((run["percent"], run["has_output"], run["file"]), (100, True, "Tiny Book.m4b"))
        self.assertEqual(self.chapters(self.dir / "out" / "Tiny Book.m4b"), ["Chapter 2"])
        status, headers, audio = self.call("GET", f"/api/download?id={book['id']}&t={self.app.token}", token=False)
        self.assertEqual(status, 200)
        self.assertIn("Tiny%20Book.m4b", headers["Content-Disposition"])
        self.assertEqual(audio, (self.dir / "out" / "Tiny Book.m4b").read_bytes())
        self.assertNotIn(str(self.dir), json.dumps(run))

    def test_stop_then_continue_repeats_no_work(self):
        book = self.small_book()
        stopped = []

        def synth(text, before="", after=""):
            self.calls.append(text)
            if len(self.calls) == 1:
                stopped.append(self.api("POST", "/api/cancel", {})[1]["run"]["message"])
            return self.tone

        with mock.patch.object(tts.Piper, "synth", lambda self_, *a, **k: synth(*a, **k)):
            self.api("POST", "/api/convert", self.request(book))
            run = self.wait_for("stopped")
            self.assertIn("press Convert again", run["message"])
            self.assertFalse((self.dir / "out" / "Tiny Book.m4b").exists())
            done_before = len(self.calls)
            self.api("POST", "/api/convert", self.request(book))
            self.wait_for("done")
        self.assertEqual(len(self.calls), len(set(self.calls)), "the saved chunk was reused")
        self.assertGreater(len(self.calls), done_before)
        self.assertTrue((self.dir / "out" / "Tiny Book.m4b").exists())

    def test_a_second_conversion_while_one_runs_is_refused_and_a_refresh_sees_it(self):
        book = self.small_book()
        gate = threading.Event()

        def slow(self_, text, before="", after=""):
            gate.wait(30)
            return self.tone

        with mock.patch.object(tts.Piper, "synth", slow):
            self.api("POST", "/api/convert", self.request(book))
            run = self.api("GET", "/api/state")[1]["run"]
            self.assertEqual((run["status"], run["title"]), ("running", "Tiny Book"))
            status, out = self.api("POST", "/api/convert", self.request(book))
            self.assertEqual(status, 400)
            self.assertIn("already running", out["error"])
            self.assertEqual(self.api("POST", "/api/quit", {})[0], 400, "quitting mid-run is refused")
            gate.set()
            self.wait_for("done")

    def test_a_paid_conversion_needs_the_quote_of_what_was_shown(self):
        book = self.small_book()
        self.api("POST", "/api/key", {"provider": "google", "key": SECRET})
        req = {**self.request(book, "google"), "price_per_1k": 0.03}
        est = self.api("POST", "/api/estimate", req)[1]
        for body in (req, {**req, "quote": "stale"}, {**req, "quote": est["quote"], "chapters": req["chapters"][:1]}):
            status, out = self.api("POST", "/api/convert", body)
            self.assertEqual(status, 400, body)
            self.assertIn("cost", out["error"])
        self.assertEqual(self.calls, [], "nothing was spent")
        self.assertEqual(self.api("POST", "/api/convert", {**req, "quote": est["quote"]})[0], 200)
        self.wait_for("done")
        self.assertTrue((self.dir / "out" / "Tiny Book.m4b").exists())

    def test_the_claude_clean_up_needs_its_key_and_the_quote_and_its_text_is_what_is_voiced(self):
        book = self.small_book()
        claude = {"on": True, "mode": "faithful", "model": "claude-haiku-5-5", "condense": False}
        req = {**self.request(book), "claude": claude}
        est = self.api("POST", "/api/estimate", req)[1]
        self.assertIn("Anthropic key", self.api("POST", "/api/convert", {**req, "quote": est["quote"]})[1]["error"])
        self.api("POST", "/api/key", {"provider": "anthropic", "key": SECRET})
        self.assertEqual(self.api("POST", "/api/convert", req)[0], 400, "no quote, no run")
        client = mock.Mock()
        client.messages.create.side_effect = lambda **kw: mock.Mock(
            stop_reason="end_turn", content=[mock.Mock(type="text", text=kw["messages"][0]["content"].replace("lazy", "sleepy"))])
        with mock.patch.object(ui.llm, "make_client", return_value=client) as make:
            self.assertEqual(self.api("POST", "/api/convert", {**req, "quote": est["quote"]})[0], 200)
            self.wait_for("done")
        make.assert_called_once_with(SECRET)
        self.assertGreater(client.messages.create.call_count, 0)
        self.assertTrue(any("sleepy dog" in c for c in self.calls))

    def test_failures_are_plain_and_never_show_the_key(self):
        book = self.small_book()
        self.api("POST", "/api/key", {"provider": "google", "key": SECRET})
        req = {**self.request(book, "google")}
        quote = self.api("POST", "/api/estimate", req)[1]["quote"]
        with mock.patch.object(tts.GoogleChirp3, "synth", side_effect=B2AError(f"Google refused: key {SECRET} is bad")):
            self.api("POST", "/api/convert", {**req, "quote": quote})
            run = self.wait_for("failed")
        self.assertNotIn(SECRET, json.dumps(run))
        self.assertIn("Google refused", run["message"])
        self.assertIn("press Convert again", run["message"])

    def test_a_missing_key_or_program_is_explained_before_anything_starts(self):
        book = self.small_book()
        req = self.request(book, "google")
        quote = self.api("POST", "/api/estimate", req)[1]["quote"]
        status, out = self.api("POST", "/api/convert", {**req, "quote": quote})
        self.assertEqual(status, 400)
        self.assertIn("Google key", out["error"])
        with mock.patch.object(ui.shutil, "which", return_value=None):
            status, out = self.api("POST", "/api/convert", self.request(book))
        self.assertIn("ffmpeg", out["error"])
        self.assertEqual(self.app.snapshot()["status"], "idle")

    def test_two_books_with_one_title_keep_separate_files(self):
        a = self.small_book(2)
        self.api("POST", "/api/convert", self.request(a))
        self.wait_for("done")
        pages = {"c1.xhtml": f"<h1>Other</h1><p>{WORDS * 8}</p>"}
        b = self.upload(make_epub(self.dir / "other.epub", pages, [("Other", "c1.xhtml")], title="Tiny Book"))[1]["book"]
        self.api("POST", "/api/convert", self.request(b))
        self.wait_for("done")
        self.assertEqual(sorted(p.name for p in (self.dir / "out").glob("*.m4b")), ["Tiny Book (2).m4b", "Tiny Book.m4b"])


class Checklist(Server):
    def test_the_checklist_gives_plain_steps_to_paste(self):
        with mock.patch.object(ui.shutil, "which", return_value=None), mock.patch.object(ui, "piper_installed",
                                                                                         return_value=False):
            items = {i["id"]: i for i in self.api("GET", "/api/setup")[1]["items"]}
        self.assertFalse(items["ffmpeg"]["ok"])
        self.assertIn("winget install", items["ffmpeg"]["fix"] + "brew install" + "apt")
        self.assertIn("pip install piper-tts", items["piper"]["fix"])
        self.assertFalse(items["google"]["ok"])
        self.assertNotIn("--", items["ffmpeg"]["fix"] + items["piper"]["fix"], "no command-line flags for beginners")


class Helpers(Server):
    def test_open_folder_shows_the_audiobook_or_the_folder(self):
        self.app.out_dir.mkdir(parents=True)
        with mock.patch.object(ui.subprocess, "Popen") as popen:
            self.api("POST", "/api/open-folder", {})
        self.assertEqual(popen.call_count, 1)
        self.assertIn(str(self.app.out_dir), " ".join(popen.call_args[0][0]))
        shutil.rmtree(self.app.out_dir)
        status, out = self.api("POST", "/api/open-folder", {})
        self.assertEqual(status, 400)
        self.assertIn("nothing to show", out["error"])

    def test_a_free_voice_download_runs_in_the_voice_folder(self):
        def fake_run(cmd, cwd, **kw):
            (Path(cwd) / "en_US-amy-medium.onnx").write_bytes(b"x")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(ui.subprocess, "run", fake_run):
            self.assertEqual(self.api("POST", "/api/piper/install", {"voice": "en_US-amy-medium"})[0], 200)
        self.assertIn("en_US-amy-medium", [v["id"] for v in self.api("GET", "/api/voices?engine=piper")[1]["voices"]])
        for bad in ("../x", "en_US-amy-medium; rm -rf", "", None, 5):
            self.assertEqual(self.api("POST", "/api/piper/install", {"voice": bad})[0], 400, bad)
        with mock.patch.object(ui.subprocess, "run", return_value=mock.Mock(returncode=1, stdout="", stderr="no net")):
            status, out = self.api("POST", "/api/piper/install", {"voice": "en_US-ryan-medium"})
        self.assertEqual(status, 400)
        self.assertIn("internet", out["error"])

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
    def test_mac_voice_samples_are_converted_so_a_browser_can_play_them(self):
        aiff = self.dir / "s.aiff"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=duration=1",
                        str(aiff)], check=True)
        wav = ui.playable(aiff)
        self.assertEqual((wav.suffix, wav.read_bytes()[:4]), (".wav", b"RIFF"))
        self.assertEqual(ui.playable(wav), wav)

    def test_ffmpeg_is_found_where_installers_put_it(self):
        spot = self.dir / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_x" / "ffmpeg-9-full" / "bin"
        spot.mkdir(parents=True)
        (spot / "ffmpeg.exe").write_bytes(b"x")
        with mock.patch.dict("os.environ", {"LOCALAPPDATA": str(self.dir), "PATH": "nothing"}),                 mock.patch.object(shutil, "which", return_value=None):
            ui.find_ffmpeg()
            self.assertTrue(os.environ["PATH"].startswith(str(spot)))


class Misc(unittest.TestCase):
    def test_file_names_are_safe_on_windows(self):
        self.assertEqual(ui.safe_name('A: B/C?"<>|*'), "A BC")
        self.assertEqual(ui.safe_name("CON"), "CON_")
        self.assertEqual(ui.safe_name("   "), "audiobook")
        self.assertLessEqual(len(ui.safe_name("x" * 500)), 80)

    def test_the_ui_command_is_wired_into_the_cli(self):
        from book2audio import cli
        with mock.patch.object(ui, "main", return_value=0) as main:
            self.assertEqual(cli.main(["ui", "--no-browser"]), 0)
        main.assert_called_once_with(["--no-browser"])


if __name__ == "__main__":
    unittest.main()
