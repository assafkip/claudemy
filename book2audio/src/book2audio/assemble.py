"""Assemble synthesized chunks into a chaptered M4B with ffmpeg.

Portions adapted from Claudemy (c) 2026 Assaf Kipnis, MIT: the ffmpeg concat + loudnorm idea
in its render_audio.py. Changes: two-pass (measured) loudness per chapter instead of one dynamic
pass, no dialogue EQ/echo, AAC speech bitrate, chapter markers, cover art, and a concat list that
survives apostrophes and Windows paths.

Each chapter is normalized to the same loudness target on its own, which keeps chapters level
with each other without holding a whole book as uncompressed audio.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from .book import B2AError

LOUDNESS = "I=-16:TP=-1.5:LRA=11"  # a common audiobook target; speech at -16 LUFS is comfortable on phones
AAC_BITRATE = "64k"                # mono speech sounds clean at 64 kbit/s and keeps a 10-hour book near 300 MB


def require_ffmpeg():
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise B2AError("ffmpeg is not installed (or not on PATH). Windows: winget install Gyan.FFmpeg, then open a "
                       "new terminal. macOS: brew install ffmpeg. Linux: apt install ffmpeg.")


def _run(cmd) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise B2AError(f"{cmd[0]} failed: {r.stderr.strip()[-400:]}")
    return r.stderr if cmd[0] == "ffmpeg" else r.stdout


def _concat_list(files, path: Path):
    """ffmpeg concat list: forward slashes, and a single quote written as '\\'' ."""
    lines = [f"file '{Path(f).resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'"
             for f in files]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def duration(path) -> float:
    return float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                       str(path)]).strip())


def build_chapter(chunk_files, out: Path):
    """Chunk audio files (in order) -> one loudness-normalized AAC chapter file."""
    out.parent.mkdir(parents=True, exist_ok=True)
    listing = out.with_suffix(".txt")
    _concat_list(chunk_files, listing)
    src = ["ffmpeg", "-nostdin", "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(listing)]
    # Pass 1 measures; pass 2 applies exactly that correction (linear), so speech is not pumped.
    stats = _run(src + ["-af", f"loudnorm={LOUDNESS}:print_format=json", "-f", "null", "-"])
    try:
        m = json.loads(stats[stats.rindex("{"):stats.rindex("}") + 1])
        measured = ":".join(f"measured_{k}={m['input_' + k]}" for k in ("i", "tp", "lra", "thresh"))
        measured += f":offset={m['target_offset']}:linear=true"
    except (ValueError, KeyError):
        raise B2AError("could not measure loudness (is the chunk audio empty or damaged?)")
    tmp = out.with_suffix(".part.m4a")
    _run(src + ["-af", f"loudnorm={LOUDNESS}:{measured}", "-ar", "44100", "-ac", "1", "-c:a", "aac",
                "-b:a", AAC_BITRATE, str(tmp)])
    tmp.replace(out)
    listing.unlink(missing_ok=True)


def _meta(s: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", s)


def build_m4b(chapter_files, titles, out: Path, title, author, cover=None, cover_ext="jpg", work: Path = None):
    """Chapter AAC files -> one .m4b with chapter markers, tags and optional cover art."""
    work = Path(work or out.parent)
    work.mkdir(parents=True, exist_ok=True)
    meta = [";FFMETADATA1", f"title={_meta(title)}", f"artist={_meta(author)}", f"album={_meta(title)}",
            "genre=Audiobook"]
    start = 0
    for f, t in zip(chapter_files, titles):
        end = start + round(duration(f) * 1000)
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={_meta(t)}"]
        start = end
    meta_path, listing = work / "chapters.ffmeta", work / "m4b-list.txt"
    meta_path.write_text("\n".join(meta) + "\n", encoding="utf-8")
    _concat_list(chapter_files, listing)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
           "-i", str(meta_path)]
    maps = ["-map", "0:a"]
    if cover:
        cover_path = work / f"cover.{cover_ext}"
        cover_path.write_bytes(cover)
        cmd += ["-i", str(cover_path)]
        maps += ["-map", "2:v", "-disposition:v:0", "attached_pic"]
    tmp = out.with_name(out.stem + ".part.m4b")
    _run(cmd + maps + ["-map_metadata", "1", "-map_chapters", "1", "-c", "copy", "-f", "ipod", str(tmp)])
    tmp.replace(out)
    return start / 1000
