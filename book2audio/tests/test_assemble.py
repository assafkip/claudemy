"""ffmpeg assembly. Needs ffmpeg and ffprobe on PATH; skipped otherwise."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (sets up sys.path)

from book2audio import assemble
from book2audio.book import B2AError

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *args], check=True)


def probe(path, *args):
    out = subprocess.run(["ffprobe", "-v", "error", "-of", "json", *args, str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def loudness(path) -> float:
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    return float(r.stderr.rsplit("Integrated loudness:", 1)[1].split("I:")[1].split("LUFS")[0])


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class Assemble(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.td.name)
        # Two tones of different volume stand in for TTS chunks (wav and mp3 both appear in real jobs).
        cls.loud = cls.dir / "loud.wav"
        cls.quiet = cls.dir / "it's quiet.wav"  # an apostrophe in the name must not break the concat list
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=300:duration=4", "-af", "volume=0.9", str(cls.loud))
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=500:duration=3", "-af", "volume=0.05", str(cls.quiet))
        cls.cover = cls.dir / "cover.jpg"
        ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(cls.cover))

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_chapter_is_normalized_to_the_target_loudness(self):
        for name, files in (("a", [self.loud, self.loud]), ("b", [self.quiet, self.quiet])):
            out = self.dir / f"ch-{name}.m4a"
            assemble.build_chapter(files, out)
            self.assertAlmostEqual(loudness(out), -16.0, delta=1.5, msg=name)
            info = probe(out, "-show_streams")["streams"][0]
            self.assertEqual((info["codec_name"], info["channels"], info["sample_rate"]), ("aac", 1, "44100"))

    def test_m4b_has_chapters_tags_and_cover(self):
        chapters = []
        for i, files in enumerate(([self.loud], [self.quiet, self.loud], [self.quiet])):
            out = self.dir / f"c{i}.m4a"
            assemble.build_chapter(files, out)
            chapters.append(out)
        titles = ["CHAPTER I; The Start", "Two = the middle", "Three #3"]
        m4b = self.dir / "book.m4b"
        total = assemble.build_m4b(chapters, titles, m4b, "My Book", "Ann Author",
                                   cover=self.cover.read_bytes(), cover_ext="jpg", work=self.dir / "w")
        info = probe(m4b, "-show_chapters", "-show_format", "-show_streams")
        self.assertEqual([c["tags"]["title"] for c in info["chapters"]], titles)
        starts = [float(c["start_time"]) for c in info["chapters"]]
        self.assertEqual(starts[0], 0.0)
        self.assertEqual(starts, sorted(starts))
        self.assertAlmostEqual(float(info["format"]["duration"]), total, delta=0.5)
        self.assertAlmostEqual(total, 4 + 3 + 4 + 3, delta=1.0)
        tags = {k.lower(): v for k, v in info["format"]["tags"].items()}
        self.assertEqual((tags["title"], tags["artist"], tags["genre"]), ("My Book", "Ann Author", "Audiobook"))
        kinds = {s["codec_type"]: s for s in info["streams"]}
        self.assertEqual(kinds["audio"]["codec_name"], "aac")
        self.assertEqual(kinds["video"]["disposition"]["attached_pic"], 1)
        self.assertTrue(str(m4b).endswith(".m4b"))

    def test_m4b_without_a_cover(self):
        out = self.dir / "only.m4a"
        assemble.build_chapter([self.loud], out)
        m4b = self.dir / "nocover.m4b"
        assemble.build_m4b([out], ["Only"], m4b, "T", "A", work=self.dir / "w2")
        kinds = [s["codec_type"] for s in probe(m4b, "-show_streams")["streams"]]
        self.assertIn("audio", kinds)
        self.assertNotIn("video", kinds)  # (a "data" stream is the chapter track)

    def test_damaged_audio_is_a_clear_error(self):
        bad = self.dir / "bad.wav"
        bad.write_bytes(b"not audio at all")
        with self.assertRaises(B2AError):
            assemble.build_chapter([bad], self.dir / "bad.m4a")


class WithoutFfmpeg(unittest.TestCase):
    def test_missing_ffmpeg_says_how_to_install(self):
        from unittest import mock
        with mock.patch.object(assemble.shutil, "which", return_value=None):
            with self.assertRaises(B2AError) as cm:
                assemble.require_ffmpeg()
        self.assertIn("winget install Gyan.FFmpeg", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
