"""The callable pieces the web page is built on: structured estimate, progress and cancel, in-memory keys, samples."""
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (sets up sys.path)
from helpers import FIXTURES, WORDS, make_epub

from book2audio import estimate, pipeline, tts
from book2audio.book import Cancelled

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class Estimate(unittest.TestCase):
    def test_compute_returns_the_numbers_the_report_prints(self):
        with tempfile.TemporaryDirectory() as td:
            epub = shutil.copy(FIXTURES / "alice.epub", Path(td) / "alice.epub")
            job = pipeline.Job(Path(td) / "job", Path(epub))
            book = pipeline.load_book(Path(epub), job)
            picks, skipped = pipeline.select(book)
            prepared = pipeline.prepare(picks, job, save=False)
            self.assertFalse(job.text.exists(), "an estimate must not write files")
            est = estimate.compute(prepared, skipped, job, tts.make_backend("elevenlabs"), price_per_1k=0.30)
        self.assertEqual(len(est["chapters"]), 12)
        self.assertEqual(est["chars"], sum(c["chars"] for c in est["chapters"]))
        self.assertEqual({b["name"] for b in est["backends"]}, set(tts.BACKENDS))
        eleven = next(b for b in est["backends"] if b["selected"])
        self.assertEqual(eleven["units"], eleven["todo_chars"])  # 1 credit per character
        self.assertAlmostEqual(eleven["money"], eleven["units"] / 1000 * 0.30)
        self.assertEqual(est["sent_to"], ["ElevenLabs"])
        self.assertIsNone(next(b for b in est["backends"] if b["name"] == "piper")["money"])
        self.assertIn({"title": "Contents", "reason": "front/back matter"}, est["skipped"])

    def test_only_the_selected_backend_when_asked(self):
        with tempfile.TemporaryDirectory() as td:
            epub = shutil.copy(FIXTURES / "alice.epub", Path(td) / "alice.epub")
            job = pipeline.Job(Path(td) / "job", Path(epub))
            picks, skipped = pipeline.select(pipeline.load_book(Path(epub), job), "1")
            est = estimate.compute(pipeline.prepare(picks, job, save=False), skipped, job, tts.make_backend("piper"),
                                   llm_opts={"mode": "faithful", "model": "claude-haiku-5-5", "condense": False},
                                   every_backend=False)
        self.assertEqual([b["name"] for b in est["backends"]], ["piper"])
        self.assertEqual(est["sent_to"], ["Anthropic"])
        self.assertGreater(est["claude"]["usd"], 0)


class KeysInMemory(unittest.TestCase):
    def test_a_typed_key_is_used_instead_of_the_environment(self):
        with mock.patch.dict("os.environ", {"ELEVENLABS_API_KEY": "from-env", "GOOGLE_TTS_API_KEY": "g-env"}):
            eleven = tts.make_backend("elevenlabs", api_key="typed-key")
            google = tts.make_backend("google", api_key="g-typed")
            with mock.patch.object(tts, "_http", return_value=b'{"audioContent": ""}') as http:
                eleven.synth("Hi.")
                self.assertEqual(http.call_args[0][0].get_header("Xi-api-key"), "typed-key")
                google.synth("Hi.")
                self.assertEqual(http.call_args[0][0].get_header("X-goog-api-key"), "g-typed")
            self.assertEqual(tts.make_backend("elevenlabs")._key(), "from-env")

    def test_a_typed_key_satisfies_the_check(self):
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(tts.shutil, "which", return_value=None):
            tts.make_backend("elevenlabs", api_key="k").check()
            tts.make_backend("google", api_key="k").check()
            with self.assertRaises(tts.B2AError):
                tts.make_backend("elevenlabs").check()

    def test_the_claude_client_gets_the_typed_key(self):
        from book2audio import llm
        with mock.patch("anthropic.Anthropic") as ctor:
            llm.make_client("typed")
            ctor.assert_called_once_with(api_key="typed")


class Sample(unittest.TestCase):
    def test_a_sample_is_a_whole_passage_of_about_100_to_200_characters(self):
        text = "CHAPTER one. Down.\n\n" + " ".join(f"Sentence number {i} is here to be read aloud." for i in range(40))
        sample = pipeline.sample_text(text)
        self.assertTrue(100 <= len(sample) <= 200, len(sample))
        self.assertTrue(sample.endswith("."))
        self.assertNotIn("Down", sample, "the title is skipped")

    def test_a_tiny_chapter_still_gives_something(self):
        self.assertEqual(pipeline.sample_text("Title.\n\nOnly one short line."), "Only one short line.")
        self.assertEqual(pipeline.sample_text(""), "")


class Fake(tts.Backend):
    name, ext, paid, max_chars, voice = "fake", "wav", False, 1000, "v"
    calls, audio = [], b""

    def __init__(self, voice=None, model=None):
        pass

    def synth(self, text, before="", after=""):
        Fake.calls.append(text)
        return Fake.audio


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class ProgressAndCancel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        wav = Path(cls.td.name) / "tone.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "sine=frequency=300:duration=1", str(wav)], check=True)
        Fake.audio = wav.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def setUp(self):
        Fake.calls = []
        self.dir = Path(tempfile.mkdtemp(dir=self.td.name))
        pages = {f"c{i}.xhtml": f"<h1>Chapter {i}</h1><p>{WORDS.replace('quick', f'quick{i}') * 8}</p>"
                 for i in (1, 2)}
        self.epub = make_epub(self.dir / "b.epub", pages, [(f"Chapter {i}", f"c{i}.xhtml") for i in (1, 2)])
        self.job = pipeline.Job(self.dir / "job", self.epub)
        self.book = pipeline.load_book(self.epub, self.job)
        self.picks, _ = pipeline.select(self.book)

    def test_events_cover_every_chunk_and_the_last_one_reaches_the_total(self):
        events = []
        seconds = pipeline.convert(self.book, self.picks, Fake(), self.job, self.dir / "b.m4b", progress=events.append,
                                   log=lambda m: None)
        self.assertGreater(seconds, 0)
        voice = [e for e in events if e["stage"] == "voice"]
        self.assertEqual(voice[-1]["done"], voice[-1]["total"])
        self.assertEqual({e["count"] for e in voice}, {2})
        self.assertEqual([e["stage"] for e in events if e["stage"] != "voice"], ["mix", "mix", "book"])
        self.assertTrue((self.dir / "b.m4b").exists())

    def test_cancel_stops_between_chunks_and_a_rerun_repeats_nothing(self):
        stop = threading.Event()

        def progress(e):
            if e["stage"] == "voice" and e["done"] > 0:
                stop.set()

        with self.assertRaises(Cancelled):
            pipeline.convert(self.book, self.picks, Fake(), self.job, self.dir / "b.m4b", progress=progress,
                             cancel=stop, log=lambda m: None)
        self.assertEqual(len(Fake.calls), 1, "stopped right after the first chunk")
        self.assertFalse((self.dir / "b.m4b").exists())
        pipeline.convert(self.book, self.picks, Fake(), self.job, self.dir / "b.m4b", log=lambda m: None)
        self.assertEqual(len(Fake.calls), len(set(Fake.calls)), "the saved chunk was reused")
        self.assertTrue((self.dir / "b.m4b").exists())


if __name__ == "__main__":
    unittest.main()
