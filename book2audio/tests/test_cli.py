"""The command line, end to end: dry-run, the paid-run gate, resuming, chapter markers."""
import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (sets up sys.path)
from helpers import FIXTURES, WORDS, make_epub

from book2audio import assemble, cli, tts

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


class NoSynthesis(tts.Backend):
    """Any attempt to synthesize fails the test."""

    def synth(self, text, before="", after=""):
        raise AssertionError("synthesis must not run")


class DryRunAndGates(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name)
        self.addCleanup(self.td.cleanup)
        self.epub = shutil.copy(FIXTURES / "alice.epub", self.dir / "alice.epub")
        for cls in (tts.Piper, tts.ElevenLabs, tts.Say):
            p = mock.patch.object(cls, "synth", NoSynthesis.synth)
            p.start()
            self.addCleanup(p.stop)

    def test_dry_run_lists_chapters_and_estimates_without_doing_anything(self):
        with mock.patch.object(assemble, "require_ffmpeg", side_effect=AssertionError("not needed for a dry run")), \
                mock.patch.dict("os.environ", {}, clear=True):  # no API keys either
            code, out, err = run_cli(self.epub, "--dry-run", "--price-per-1k", "0.30")
        self.assertEqual(code, 0, err)
        self.assertIn("DRY RUN", out)
        self.assertIn("12 chapters to narrate, 4 skipped", out)
        self.assertIn("CHAPTER I. Down the Rabbit-Hole", out)
        self.assertIn("CHAPTER XII. Alice’s Evidence", out)
        self.assertIn("'Contents': front/back matter", out)
        for backend in ("elevenlabs", "piper", "say"):
            self.assertIn(backend, out)
        self.assertRegex(out, r"[\d,]{6,} credits = [\d.,]+ at 0.3 per 1,000")
        self.assertIn("The text stays on this computer.", out)
        self.assertEqual(list((self.dir / "alice.b2a").glob("tts")), [], "nothing synthesized")
        text = (self.dir / "alice.b2a" / "text" / "01.txt").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("CHAPTER one. Down the Rabbit-Hole.\n\nAlice was beginning"))

    def test_dry_run_on_a_pdf(self):
        pdf = shutil.copy(FIXTURES / "alice-excerpt.pdf", self.dir / "a.pdf")
        code, out, err = run_cli(pdf, "--dry-run", "--backend", "elevenlabs")
        self.assertEqual(code, 0, err)
        self.assertIn("3 chapters to narrate, 0 skipped", out)
        self.assertIn("The text of this book will be sent to ElevenLabs (cloud).", out)

    def test_chapter_selection(self):
        code, out, _ = run_cli(self.epub, "--dry-run", "--chapters", "2-3,5")
        self.assertEqual(code, 0)
        self.assertIn("3 chapters to narrate", out)
        self.assertNotIn("CHAPTER I. Down", out)
        code, _, err = run_cli(self.epub, "--dry-run", "--chapters", "13")
        self.assertEqual(code, 2)
        self.assertIn("numbered 1 to 12", err)

    def test_a_paid_backend_shows_the_estimate_and_waits_for_yes(self):
        with mock.patch.dict("os.environ", {"ELEVENLABS_API_KEY": "sk-test"}), \
                mock.patch.object(assemble, "require_ffmpeg"):
            code, out, err = run_cli(self.epub, "--backend", "elevenlabs", "--chapters", "1")
        self.assertEqual(code, 3)
        self.assertIn("credits", out)
        self.assertIn("with --yes", err)

    def test_claude_pass_also_needs_yes_and_discloses_where_text_goes(self):
        fake = mock.Mock()
        with mock.patch.object(assemble, "require_ffmpeg"), mock.patch.object(cli.llm, "make_client",
                                                                              return_value=fake), \
                mock.patch.object(tts.Piper, "check"):
            code, out, err = run_cli(self.epub, "--llm", "--chapters", "1")
        self.assertEqual(code, 3)
        self.assertIn("Anthropic (cloud)", out)
        self.assertIn("Claude pass (faithful, claude-opus-5-5)", out)
        self.assertEqual(fake.method_calls, [], "no request before --yes")

    def test_missing_key_is_reported_before_anything_is_spent(self):
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(assemble, "require_ffmpeg"):
            code, _, err = run_cli(self.epub, "--backend", "elevenlabs", "--yes", "--chapters", "1")
        self.assertEqual(code, 2)
        self.assertIn("ELEVENLABS_API_KEY", err)

    def test_bad_arguments(self):
        for argv, text in (([self.epub, "--mode", "adapted"], "needs --llm"),
                           ([self.epub, "--condense"], "only applies with --mode adapted"),
                           ([self.dir / "missing.epub"], "no such file"),
                           ([shutil.copy(self.epub, self.dir / "x.txt")], "only .epub and .pdf")):
            code, _, err = run_cli(*argv, "--dry-run")
            self.assertEqual(code, 2, argv)
            self.assertIn(text, err)

    def test_a_job_folder_belongs_to_one_book(self):
        other = shutil.copy(FIXTURES / "alice-excerpt.pdf", self.dir / "other.pdf")
        run_cli(self.epub, "--dry-run", "--job-dir", self.dir / "shared")
        code, _, err = run_cli(other, "--dry-run", "--job-dir", self.dir / "shared")
        self.assertEqual(code, 2)
        self.assertIn("different file", err)


class Fake(tts.Backend):
    name, ext, paid, max_chars, voice = "fake", "wav", False, 1000, "v"
    calls, audio, fail_on_call = [], b"", None

    def __init__(self, voice=None, model=None):
        pass

    def synth(self, text, before="", after=""):
        Fake.calls.append(text)
        if Fake.fail_on_call == len(Fake.calls):
            raise tts.B2AError("simulated network failure")
        return Fake.audio


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        wav = Path(cls.td.name) / "tone.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "sine=frequency=300:duration=2", str(wav)], check=True)
        Fake.audio = wav.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def setUp(self):
        Fake.calls, Fake.fail_on_call = [], None
        self.dir = Path(tempfile.mkdtemp(dir=self.td.name))
        pages = {f"c{i}.xhtml": f"<h1>Chapter {i}</h1><p>{WORDS.replace('quick', f'quick{i}') * 8}</p>"
                 for i in (1, 2, 3)}
        self.epub = make_epub(self.dir / "book.epub", pages, [(f"Chapter {i}", f"c{i}.xhtml") for i in (1, 2, 3)],
                              title="Tiny Book", author="Ann Author")
        patch = mock.patch.dict(tts.BACKENDS, {"fake": Fake})
        patch.start()
        self.addCleanup(patch.stop)

    def chapters(self, m4b):
        out = subprocess.run(["ffprobe", "-v", "error", "-of", "json", "-show_chapters", "-show_format", str(m4b)],
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_book_becomes_an_m4b_with_a_marker_per_chapter(self):
        code, out, err = run_cli(self.epub, "--backend", "fake")
        self.assertEqual(code, 0, err)
        info = self.chapters(self.dir / "book.m4b")
        self.assertEqual([c["tags"]["title"] for c in info["chapters"]], ["Chapter 1", "Chapter 2", "Chapter 3"])
        self.assertEqual(info["format"]["tags"]["title"], "Tiny Book")
        self.assertGreater(len(Fake.calls), 3, "each chapter is several chunks")
        self.assertTrue(all(len(c) <= 1000 for c in Fake.calls))
        self.assertIn("Wrote", out)
        self.assertIn("synthesized", err)

    def test_rerun_costs_nothing_and_chapter_selection_limits_the_book(self):
        run_cli(self.epub, "--backend", "fake")
        first = len(Fake.calls)
        code, _, err = run_cli(self.epub, "--backend", "fake", "-o", self.dir / "again.m4b")
        self.assertEqual((code, len(Fake.calls)), (0, first), err)
        self.assertIn("cached", err)
        code, out, _ = run_cli(self.epub, "--backend", "fake", "--chapters", "2", "-o", self.dir / "one.m4b")
        self.assertEqual(len(self.chapters(self.dir / "one.m4b")["chapters"]), 1)
        self.assertEqual(len(Fake.calls), first, "chapter 2 was already cached")

    def test_an_interrupted_run_resumes_without_repeating_work(self):
        Fake.fail_on_call = 3
        code, _, err = run_cli(self.epub, "--backend", "fake")
        self.assertEqual(code, 2)
        self.assertIn("simulated network failure", err)
        self.assertFalse((self.dir / "book.m4b").exists())
        Fake.fail_on_call = None
        code, _, err = run_cli(self.epub, "--backend", "fake")
        self.assertEqual(code, 0, err)
        # Two chunks were saved before the failure; the failed one is tried again and nothing else is repeated.
        self.assertEqual(len(Fake.calls), len(set(Fake.calls)) + 1)

    def test_claude_pass_runs_only_after_yes_and_its_text_is_what_is_spoken(self):
        client = mock.Mock()
        client.messages.create.side_effect = lambda **kw: mock.Mock(
            stop_reason="end_turn", content=[mock.Mock(type="text", text=kw["messages"][0]["content"].replace("lazy", "sleepy"))])
        with mock.patch.object(cli.llm, "make_client", return_value=client):
            code, _, _ = run_cli(self.epub, "--backend", "fake", "--llm", "--llm-model", "claude-haiku-5-5",
                                 "--chapters", "1")
            self.assertEqual((code, client.messages.create.call_count), (3, 0))
            code, _, err = run_cli(self.epub, "--backend", "fake", "--llm", "--llm-model", "claude-haiku-5-5",
                                   "--chapters", "1", "--yes")
        self.assertEqual(code, 0, err)
        self.assertGreater(client.messages.create.call_count, 0)
        self.assertTrue(any("sleepy dog" in c and "lazy" not in c for c in Fake.calls),
                        "the Claude text is what gets voiced")


if __name__ == "__main__":
    unittest.main()
