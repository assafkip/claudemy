"""Bundle a finished class for delivery: audio zips under a size cap, plus all cards in one file.

Chat and file-sharing tools cap uploads (one we hit was 30 MB), so the audio is
split into numbered zips that each stay under --max-mb. Cards are combined in
lesson order into cards.md, and into cards.docx when pandoc is installed.

Usage: python3 package_class.py <workspace> [--max-mb 25]
Writes to <workspace>/deliver/.
"""
import shutil, subprocess, sys, zipfile
from pathlib import Path


def lesson_dirs(ws):
    return sorted(p for p in (ws / "class").glob("[0-9][0-9]-*") if p.is_dir())


def zip_audio(ws, out, max_bytes):
    mp3s, names = [], {}
    for d in lesson_dirs(ws):
        found = sorted(d.glob("*.mp3"))
        if len(found) > 1:
            # Two renders in one folder used to share one member name; whichever
            # extracted last won, silently. Now each keeps its own name, and the run says so.
            print(f"{d.name}: {len(found)} mp3 files, each packed under its own name: "
                  + ", ".join(f.name for f in found), file=sys.stderr)
        for m in found:
            names[m] = f"{d.name}.mp3" if len(found) == 1 else f"{d.name}-{m.stem}.mp3"
        mp3s += found
    groups, current, size = [], [], 0
    for m in mp3s:
        if current and size + m.stat().st_size > max_bytes:
            groups.append(current)
            current, size = [], 0
        current.append(m)
        size += m.stat().st_size
    if current:
        groups.append(current)
    made = []
    for group in groups:
        first, last = group[0].parent.name[:2], group[-1].parent.name[:2]
        path = out / f"audio-lessons-{first}-to-{last}.zip"
        with zipfile.ZipFile(path, "w") as z:
            for m in group:
                z.write(m, names[m])
        made.append(path)
    return made


def combine_cards(ws, out):
    cards = [d / "card.md" for d in lesson_dirs(ws) if (d / "card.md").exists()]
    md = out / "cards.md"
    md.write_text("\n\n---\n\n".join(c.read_text() for c in cards))
    if shutil.which("pandoc"):
        subprocess.run(["pandoc", str(md), "-f", "markdown", "-t", "docx", "-o", str(out / "cards.docx")], check=True)
    return len(cards)


def main(ws, max_mb):
    out = ws / "deliver"
    out.mkdir(exist_ok=True)
    zips = zip_audio(ws, out, max_mb * 1024 * 1024)
    n = combine_cards(ws, out)
    for z in zips:
        # Same unit as the cap (MiB). Printing decimal MB showed 26.0 against a 25 cap for a zip under it.
        print(f"{z}  {z.stat().st_size / (1024 * 1024):.1f} MB (cap {max_mb} MB)")
    print(f"{n} cards combined in {out / 'cards.md'}" + (" and cards.docx" if shutil.which("pandoc") else ""))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cap = int(sys.argv[sys.argv.index("--max-mb") + 1]) if "--max-mb" in sys.argv else 25
    main(Path(sys.argv[1]).expanduser().resolve(), cap)
