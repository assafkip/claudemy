"""The voice catalog: what each engine offers and what the page is allowed to pick. No network."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (sets up sys.path)

from book2audio import voices
from book2audio.book import B2AError

SAY_OUTPUT = """Albert              en_US    # Hello! My name is Albert.
Eddy (English (UK)) en_GB    # Hello! My name is Eddy.
Amélie              fr_CA    # Bonjour ! Je m’appelle Amélie.
"""


class Google(unittest.TestCase):
    def test_the_thirty_documented_voices_in_the_chosen_language(self):
        found = voices.google_voices("de-DE")
        self.assertEqual(len(found), 30)
        self.assertEqual(len({v["id"] for v in found}), 30)
        self.assertIn({"id": "de-DE-Chirp3-HD-Charon", "name": "Charon", "detail": "male"}, found)
        self.assertEqual(sum(v["detail"] == "female" for v in found), 14)

    def test_an_unknown_language_is_refused(self):
        with self.assertRaises(B2AError):
            voices.google_voices("xx-XX")


class ElevenLabs(unittest.TestCase):
    def test_account_voices_are_listed_by_name(self):
        reply = {"voices": [{"voice_id": "bbbbbbbbbb", "name": "Zed", "labels": {"gender": "male", "accent": "irish"}},
                            {"voice_id": "aaaaaaaaaa", "name": "amy", "category": "cloned"}]}
        with mock.patch.object(voices, "_http", return_value=json.dumps(reply).encode()) as http:
            found = voices.elevenlabs_voices("key-123456")
        self.assertEqual(http.call_args[0][0].get_header("Xi-api-key"), "key-123456")
        self.assertEqual([v["name"] for v in found], ["amy", "Zed"])
        self.assertEqual(found[1]["detail"], "male, irish")
        self.assertEqual(found[0]["detail"], "cloned")

    def test_a_reply_that_is_not_a_voice_list_is_a_plain_error(self):
        with mock.patch.object(voices, "_http", return_value=b'{"oops": 1}'), self.assertRaises(B2AError):
            voices.elevenlabs_voices("key-123456")

    def test_without_a_key_a_small_built_in_list_is_shown(self):
        cat = voices.catalog("elevenlabs")
        self.assertEqual(cat["voices"], voices.ELEVENLABS_FALLBACK)
        self.assertIn("key", cat["note"])
        self.assertTrue(all(voices.ELEVENLABS_ID.match(v["id"]) for v in cat["voices"]))


class Local(unittest.TestCase):
    def test_piper_voices_are_the_onnx_files_found(self):
        with tempfile.TemporaryDirectory() as td:
            for name in ("en_US-lessac-medium.onnx", "en_GB-northern_english_male-low.onnx", "mine.onnx",
                         "en_US-lessac-medium.onnx.json", "notes.txt"):
                (Path(td) / name).write_bytes(b"x")
            found = voices.piper_voices(td)
        self.assertEqual([v["id"] for v in found], ["en_GB-northern_english_male-low", "en_US-lessac-medium", "mine"])
        self.assertEqual(found[0]["name"], "northern english male")
        self.assertEqual(found[1]["detail"], "en_US, medium quality")
        self.assertEqual(voices.piper_voices("/no/such/folder"), [])

    def test_mac_voices_are_read_from_say(self):
        with mock.patch.object(voices.shutil, "which", return_value="/usr/bin/say"), \
                mock.patch.object(voices.subprocess, "run", return_value=mock.Mock(stdout=SAY_OUTPUT)):
            found = voices.say_voices()
        self.assertEqual([v["id"] for v in found], ["Albert", "Eddy (English (UK))", "Amélie"])
        self.assertEqual(found[1]["detail"], "en_GB")
        with mock.patch.object(voices.shutil, "which", return_value=None):
            self.assertEqual(voices.say_voices(), [])


class Choice(unittest.TestCase):
    def test_only_what_the_page_could_have_offered_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "en_US-lessac-medium.onnx").write_bytes(b"x")
            ok = [("piper", "en_US-lessac-medium", None, "en-US"),
                  ("google", "en-US-Chirp3-HD-Kore", None, "en-US"),
                  ("elevenlabs", "TX3LPaxmHKxFdv7VOQHJ", "eleven_v3", "en-US")]
            for args in ok:
                voices.check_choice(*args, td)
            bad = [("piper", "../lessac", None, "en-US"), ("piper", "en_US-lessac-medium.onnx", None, "en-US"),
                   ("piper", "C:\\x\\v.onnx", None, "en-US"), ("google", "en-US-Chirp3-HD-Nobody", None, "en-US"),
                   ("google", "de-DE-Chirp3-HD-Kore", None, "en-US"), ("elevenlabs", "a/b", "eleven_v3", "en-US"),
                   ("elevenlabs", "TX3LPaxmHKxFdv7VOQHJ", "gpt-4", "en-US"), ("elevenlabs", None, "eleven_v3", "en-US"),
                   ("say", "Albert", None, "en-US"), ("nope", "x", None, "en-US")]
            for args in bad:
                with self.assertRaises(B2AError, msg=args):
                    voices.check_choice(*args, td)


if __name__ == "__main__":
    unittest.main()
