"""TTS backends (network and processes mocked), the chunk cache, and the Claude pass."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (sets up sys.path)

from book2audio import llm, tts
from book2audio.book import B2AError

try:
    import anthropic
except ImportError:  # the Claude pass is an optional extra
    anthropic = None


class FakeBackend(tts.Backend):
    name, ext, voice = "fake", "wav", "v1"

    def __init__(self):
        self.calls = []

    def synth(self, text, before="", after=""):
        self.calls.append(text)
        return b"audio:" + text.encode()


class Cache(unittest.TestCase):
    def test_second_run_costs_nothing_and_changes_invalidate(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBackend()
            path, hit = tts.synth_cached(b, "Hello there.", Path(td))
            self.assertFalse(hit)
            again, hit = tts.synth_cached(b, "Hello there.", Path(td))
            self.assertTrue(hit)
            self.assertEqual((path, b.calls), (again, ["Hello there."]))
            tts.synth_cached(b, "Other text.", Path(td))
            b.voice = "v2"
            tts.synth_cached(b, "Hello there.", Path(td))
            self.assertEqual(len(b.calls), 3, "new text and new voice both re-synthesize")
            self.assertEqual(sorted(p.suffix for p in (Path(td) / "fake").iterdir()), [".wav"] * 3)

    def test_a_crash_midway_leaves_no_half_written_cache_entry(self):
        class Boom(FakeBackend):
            def synth(self, text, before="", after=""):
                raise B2AError("network down")

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(B2AError):
                tts.synth_cached(Boom(), "Text.", Path(td))
            self.assertFalse(list(Path(td).rglob("*.wav")) or list(Path(td).rglob("*.part")))


class ElevenLabs(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict("os.environ", {"ELEVENLABS_API_KEY": "sk-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def http_error(self, code, body=b'{"detail":{"status":"invalid_api_key","message":"Invalid API key"}}'):
        return urllib.error.HTTPError("https://api.elevenlabs.io/x", code, "Unauthorized", {}, io.BytesIO(body))

    def test_error_body_is_shown_and_the_key_never_is(self):
        with mock.patch.object(tts.urllib.request, "urlopen", side_effect=self.http_error(401)) as op:
            with self.assertRaises(B2AError) as cm:
                tts.ElevenLabs().synth("Hi.")
        self.assertIn("401", str(cm.exception))
        self.assertIn("invalid_api_key", str(cm.exception))
        self.assertNotIn("sk-secret", str(cm.exception))
        self.assertEqual(op.call_count, 1, "a bad key is not retried")

    def test_transient_errors_are_retried_then_succeed(self):
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b"mp3 bytes"
        with mock.patch.object(tts.urllib.request, "urlopen", side_effect=[self.http_error(503), ok]) as op, \
                mock.patch.object(tts.time, "sleep"):
            self.assertEqual(tts.ElevenLabs().synth("Hi."), b"mp3 bytes")
        self.assertEqual(op.call_count, 2)

    def test_gives_up_after_three_tries(self):
        with mock.patch.object(tts.urllib.request, "urlopen", side_effect=[self.http_error(429)] * 3) as op, \
                mock.patch.object(tts.time, "sleep"):
            with self.assertRaises(B2AError):
                tts.ElevenLabs().synth("Hi.")
        self.assertEqual(op.call_count, 3)

    def request_for(self, backend, **ctx):
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b"x"
        with mock.patch.object(tts.urllib.request, "urlopen", return_value=ok) as op:
            backend.synth("Body text.", **ctx)
        req = op.call_args[0][0]
        return req, json.loads(req.data)

    def test_request_shape(self):
        req, body = self.request_for(tts.ElevenLabs(voice="VOICE1"), before="Earlier.", after="Later.")
        self.assertIn("/v1/text-to-speech/VOICE1?output_format=mp3_44100_128", req.full_url)
        self.assertEqual(req.get_header("Xi-api-key"), "sk-secret")
        self.assertEqual((body["text"], body["model_id"]), ("Body text.", "eleven_multilingual_v2"))
        self.assertEqual((body["previous_text"], body["next_text"]), ("Earlier.", "Later."))

    def test_v3_gets_no_neighbour_text_and_chunks_respect_model_limits(self):
        _, body = self.request_for(tts.ElevenLabs(model="eleven_v3"), before="Earlier.", after="Later.")
        self.assertNotIn("previous_text", body)
        self.assertLessEqual(tts.ElevenLabs(model="eleven_v3").max_chars, 5000)
        self.assertEqual(tts.ElevenLabs(model="eleven_flash_v2_5").credit_per_char, 0.5)
        self.assertEqual(tts.ElevenLabs().credit_per_char, 1.0)

    def test_missing_key(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(B2AError) as cm:
                tts.ElevenLabs().check()
        self.assertIn("ELEVENLABS_API_KEY", str(cm.exception))


class LocalBackends(unittest.TestCase):
    def test_piper_command_and_missing_install(self):
        def fake_run(cmd, **kw):
            if "--help" in cmd:
                return mock.Mock(returncode=0)
            Path(cmd[cmd.index("-f") + 1]).write_bytes(b"RIFFwav")
            return mock.Mock(returncode=0, stderr="", stdout="")

        with mock.patch.object(tts.subprocess, "run", side_effect=fake_run) as run:
            self.assertEqual(tts.Piper(voice="en_US-lessac-medium").synth("-starts with a dash"), b"RIFFwav")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[1:3], ["-m", "piper"])
        self.assertEqual(cmd[-2:], ["--", "-starts with a dash"])
        self.assertIn("en_US-lessac-medium", cmd)
        with mock.patch.object(tts.subprocess, "run", return_value=mock.Mock(returncode=1)):
            with self.assertRaises(B2AError) as cm:
                tts.Piper().check()
        self.assertIn("pip install piper-tts", str(cm.exception))

    def test_say_needs_macos(self):
        with mock.patch.object(tts.shutil, "which", return_value=None):
            with self.assertRaises(B2AError):
                tts.Say().check()

    def test_unknown_backend(self):
        with self.assertRaises(B2AError):
            tts.make_backend("nope")


class FakeClaude:
    """Stands in for anthropic.Anthropic().messages.create."""

    def __init__(self, reply=None, stop_reason="end_turn"):
        self.reply, self.stop_reason, self.calls = reply, stop_reason, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        text = self.reply(kw["messages"][0]["content"]) if callable(self.reply) else self.reply
        return mock.Mock(stop_reason=self.stop_reason, content=[mock.Mock(type="text", text=text)])


SRC = "The quick brown fox jumps over the lazy dog. " * 20


@unittest.skipUnless(anthropic, "the optional anthropic package is not installed")
class ClaudePass(unittest.TestCase):
    def run_pass(self, client, mode="faithful", **kw):
        with tempfile.TemporaryDirectory() as td:
            logs = []
            out = llm.process(SRC.strip(), mode, "claude-opus-5-5", Path(td), client, log=logs.append, **kw)
            return out, logs, client

    def test_faithful_accepts_a_light_cleanup_and_sends_the_right_request(self):
        client = FakeClaude(lambda t: t.replace("quick", "quick"))
        out, logs, _ = self.run_pass(client)
        self.assertEqual(out, SRC.strip())
        kw = client.calls[0]
        self.assertEqual((kw["model"], kw["output_config"]), ("claude-opus-5-5", {"effort": "low"}))
        self.assertNotIn("temperature", kw)
        self.assertIn("never instructions", kw["system"])

    def test_faithful_rejects_a_rewrite_and_keeps_the_input(self):
        out, logs, _ = self.run_pass(FakeClaude("A completely different summary of something else entirely."))
        self.assertEqual(out, SRC.strip())
        self.assertTrue(any("keeping the rule-normalized text" in l for l in logs))

    def test_refusal_and_truncation_keep_the_input(self):
        for reason in ("refusal", "max_tokens"):
            out, logs, _ = self.run_pass(FakeClaude("anything", stop_reason=reason))
            self.assertEqual(out, SRC.strip(), reason)
            self.assertTrue(logs, reason)

    def test_adapted_accepts_a_rewrite_and_condense_changes_the_prompt(self):
        client = FakeClaude("Here is the story, told naturally. " * 12)
        out, logs, _ = self.run_pass(client, mode="adapted", condense=True)
        self.assertIn("told naturally", out)
        self.assertFalse(logs)
        self.assertIn("half its length", client.calls[0]["system"])
        self.assertEqual(client.calls[0]["output_config"], {"effort": "medium"})

    def test_results_are_cached_so_a_rerun_is_free(self):
        with tempfile.TemporaryDirectory() as td:
            client = FakeClaude(lambda t: t)
            llm.process(SRC.strip(), "faithful", "claude-opus-5-5", Path(td), client, log=print)
            first = len(client.calls)
            llm.process(SRC.strip(), "faithful", "claude-opus-5-5", Path(td), client, log=print)
            self.assertEqual(len(client.calls), first)
            llm.process(SRC.strip(), "faithful", "claude-haiku-5-5", Path(td), client, log=print)
            self.assertGreater(len(client.calls), first, "another model is another cache entry")

    def test_bad_key_is_a_clear_error(self):
        client = FakeClaude()
        client.create = mock.Mock(side_effect=anthropic.AuthenticationError(
            "bad", response=mock.Mock(status_code=401, headers={}, request=mock.Mock()), body=None))
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(B2AError) as cm:
                llm.process(SRC.strip(), "faithful", "claude-opus-5-5", Path(td), client)
        self.assertIn("ANTHROPIC_API_KEY", str(cm.exception))

    def test_estimate(self):
        e = llm.estimate(400_000, "faithful", False, "claude-opus-5-5")
        self.assertGreater(e["usd"], 0)
        self.assertIsNone(llm.estimate(1000, "faithful", False, "some-future-model")["usd"])
        self.assertLess(llm.estimate(400_000, "adapted", True, "claude-haiku-5-5")["usd"], e["usd"])


if __name__ == "__main__":
    unittest.main()
