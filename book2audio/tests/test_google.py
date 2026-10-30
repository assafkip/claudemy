"""Google Chirp 3 HD backend and the sample script. All network and gcloud calls are mocked."""
import base64
import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (sets up sys.path)
from helpers import FIXTURES, HERE

from book2audio import cli, tts
from book2audio.book import B2AError

AUDIO = b"ID3 fake mp3 bytes"


def reply(payload=None):
    resp = mock.MagicMock()
    resp.__enter__.return_value.read.return_value = json.dumps(
        payload if payload is not None else {"audioContent": base64.b64encode(AUDIO).decode()}).encode()
    return resp


def http_error(code, body=b'{"error":{"code":403,"message":"API has not been used in project","status":"PERMISSION_DENIED"}}'):
    return urllib.error.HTTPError("https://texttospeech.googleapis.com/x", code, "Forbidden", {}, io.BytesIO(body))


class Backend(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict("os.environ", {"GOOGLE_TTS_API_KEY": "gk-secret"}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_request_shape_and_decoded_audio(self):
        with mock.patch.object(tts.urllib.request, "urlopen", return_value=reply()) as op:
            audio = tts.GoogleChirp3(voice="en-us-Chirp3-HD-Leda").synth("Hello there.")
        self.assertEqual(audio, AUDIO)
        req = op.call_args[0][0]
        self.assertEqual(req.full_url, "https://texttospeech.googleapis.com/v1/text:synthesize")
        self.assertEqual(req.get_header("X-goog-api-key"), "gk-secret")
        self.assertEqual(json.loads(req.data), {
            "input": {"text": "Hello there."},
            "voice": {"languageCode": "en-US", "name": "en-us-Chirp3-HD-Leda"},
            "audioConfig": {"audioEncoding": "MP3"}})

    def test_voice_names(self):
        self.assertEqual(tts.GoogleChirp3().voice, "en-US-Chirp3-HD-Charon")
        self.assertEqual(tts.GoogleChirp3(voice="cmn-CN-Chirp3-HD-Kore").language, "cmn-CN")
        for bad in ("Charon", "en-US-Wavenet-D", "en-US-Chirp3-Charon"):
            with self.assertRaises(B2AError, msg=bad):
                tts.GoogleChirp3(voice=bad)

    def test_chunks_fit_the_5000_byte_request_limit_even_for_three_byte_characters(self):
        self.assertLessEqual(len("’".encode()) * tts.GoogleChirp3.max_chars, 5000)
        self.assertEqual((tts.GoogleChirp3.ext, tts.GoogleChirp3.paid, tts.GoogleChirp3.unit),
                         ("mp3", True, "characters"))
        self.assertIs(tts.BACKENDS["google"], tts.GoogleChirp3)

    def test_google_error_text_is_shown_and_the_key_never_is(self):
        with mock.patch.object(tts.urllib.request, "urlopen", side_effect=http_error(403)) as op:
            with self.assertRaises(B2AError) as cm:
                tts.GoogleChirp3().synth("Hi.")
        self.assertIn("API has not been used", str(cm.exception))
        self.assertNotIn("gk-secret", str(cm.exception))
        self.assertEqual(op.call_count, 1, "a permission error is not retried")

    def test_transient_errors_are_retried(self):
        with mock.patch.object(tts.urllib.request, "urlopen", side_effect=[http_error(503), reply()]) as op, \
                mock.patch.object(tts.time, "sleep"):
            self.assertEqual(tts.GoogleChirp3().synth("Hi."), AUDIO)
        self.assertEqual(op.call_count, 2)

    def test_an_answer_without_audio_is_an_error(self):
        with mock.patch.object(tts.urllib.request, "urlopen", return_value=reply({"nothing": 1})):
            with self.assertRaises(B2AError):
                tts.GoogleChirp3().synth("Hi.")


class GcloudAuth(unittest.TestCase):
    def test_access_token_is_used_once_per_half_hour_and_project_is_sent(self):
        env = {"GOOGLE_CLOUD_PROJECT": "my-project"}
        done = mock.Mock(returncode=0, stdout="ya29.token\n", stderr="")
        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch.object(tts.shutil, "which", return_value="gcloud"), \
                mock.patch.object(tts.subprocess, "run", return_value=done) as run, \
                mock.patch.object(tts.urllib.request, "urlopen", side_effect=lambda *a, **k: reply()) as op:
            backend = tts.GoogleChirp3()
            backend.check()
            backend.synth("One.")
            backend.synth("Two.")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args[0][0][1:], ["auth", "print-access-token"])
        req = op.call_args[0][0]
        self.assertEqual(req.get_header("Authorization"), "Bearer ya29.token")
        self.assertEqual(req.get_header("X-goog-user-project"), "my-project")
        self.assertIsNone(req.get_header("X-goog-api-key"))

    def test_gcloud_failure_says_how_to_log_in(self):
        failed = mock.Mock(returncode=1, stdout="", stderr="not logged in")
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(tts.shutil, "which", return_value="gcloud"), \
                mock.patch.object(tts.subprocess, "run", return_value=failed):
            with self.assertRaises(B2AError) as cm:
                tts.GoogleChirp3().synth("Hi.")
        self.assertIn("gcloud auth login", str(cm.exception))

    def test_no_credentials_at_all(self):
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(tts.shutil, "which", return_value=None):
            with self.assertRaises(B2AError) as cm:
                tts.GoogleChirp3().check()
        self.assertIn("GOOGLE_TTS_API_KEY", str(cm.exception))
        self.assertIn("gcloud", str(cm.exception))


class InTheCli(unittest.TestCase):
    def test_dry_run_reports_characters_and_where_the_text_goes(self):
        with tempfile.TemporaryDirectory() as td:
            pdf = shutil.copy(FIXTURES / "alice-excerpt.pdf", Path(td) / "a.pdf")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), \
                    mock.patch.object(tts.GoogleChirp3, "synth", side_effect=AssertionError("no synthesis")):
                code = cli.main([str(pdf), "--dry-run", "--backend", "google", "--price-per-1k", "0.03"])
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertRegex(text, r"google\s+[\d,]+ ch .* [\d,]+ characters = [\d.]+ at 0.03 per 1,000")
        self.assertIn("The text of this book will be sent to Google Cloud (cloud).", text)


class SampleScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("chirp3_sample", HERE.parent / "examples" / "chirp3_sample.py")
        cls.sample = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.sample)

    def test_requests_each_voice_and_saves_an_mp3(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict("os.environ", {"GOOGLE_TTS_API_KEY": "gk-secret"}, clear=True), \
                mock.patch.object(self.sample.urllib.request, "urlopen", side_effect=lambda *a, **k: reply()) as op:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.sample.main(["--voice", "en-US-Chirp3-HD-Leda", "--voice", "en-US-Chirp3-HD-Kore",
                                         "--outdir", td, "Say this."])
            files = sorted(p.name for p in Path(td).iterdir())
            self.assertEqual(files, ["chirp3-Kore.mp3", "chirp3-Leda.mp3"])
            self.assertEqual((Path(td) / "chirp3-Leda.mp3").read_bytes(), AUDIO)
        self.assertEqual((code, op.call_count), (0, 2))
        body = json.loads(op.call_args[0][0].data)
        self.assertEqual((body["input"]["text"], body["voice"]["languageCode"]), ("Say this.", "en-US"))
        self.assertNotIn("gk-secret", out.getvalue())

    def test_google_errors_are_shown(self):
        with mock.patch.dict("os.environ", {"GOOGLE_TTS_API_KEY": "gk-secret"}, clear=True), \
                mock.patch.object(self.sample.urllib.request, "urlopen", side_effect=http_error(403)):
            with self.assertRaises(SystemExit) as cm:
                self.sample.main(["--outdir", tempfile.gettempdir()])
        self.assertIn("API has not been used", str(cm.exception))
        self.assertNotIn("gk-secret", str(cm.exception))

    def test_list_voices(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.sample.main(["--list"])
        self.assertIn("Charon", out.getvalue())
        self.assertEqual(sum(len(v) for v in self.sample.VOICES.values()), 30)


if __name__ == "__main__":
    unittest.main()
