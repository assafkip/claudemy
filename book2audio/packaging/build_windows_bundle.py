"""Build the portable Windows bundle: one zip that holds its own Python, ffmpeg and book2audio.

    python packaging/build_windows_bundle.py --work C:\\Temp\\b2a-bundle

The person who gets the zip unzips it and double-clicks "Start Book2Audio.bat": no Python, no ffmpeg, no
administrator rights, nothing added to the PATH. Standard library only; run it with any Python 3.10+.

What goes in, and why each piece is pinned:
- Python 3.13 "embeddable package" from python.org (PSF licence).
- ffmpeg from BtbN's LGPL "shared" build (not the GPL build that `winget install Gyan.FFmpeg` gives): the
  script refuses to continue if the build reports --enable-gpl or --enable-nonfree.
- book2audio and its dependencies (including the optional anthropic add-on) as wheels from PyPI, plus pip, so the
  page's "Install it for me" button can fetch the free voice program later.
NOT included: Piper (GPL-3.0) and any voice model. The person installs them on demand, from the page.

Downloads are checked against the SHA-256 the publisher shows. If a pinned file disappears (BtbN keeps only
recent builds), pick a new one from https://github.com/BtbN/FFmpeg-Builds/releases and update FFMPEG below.
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the book2audio folder, where pyproject.toml is

PYTHON = {
    "version": "3.13.17", "tag": "313",
    "url": "https://www.python.org/ftp/python/3.13.17/python-3.13.17-embed-amd64.zip",
    "sha256": "9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38",  # shown on python.org's release page
}
FFMPEG = {
    "version": "n9.0.2-39-g7adfbe40dc",
    "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-30-13-01/"
           "ffmpeg-n9.0.2-39-g7adfbe40dc-win64-lgpl-shared-9.0.zip",
    "sha256": "8aeb11be252902a772ff04ac89b705f7a7b24815f0a21da2ab100b192a5c16e4",  # BtbN's checksums.sha256
}
NAME = "Book2Audio"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, sha256: str, dest: Path) -> Path:
    """Download to dest unless a file with the right hash is already there; a wrong hash stops the build."""
    if dest.exists() and sha256_of(dest) == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    print(f"downloading {url}", flush=True)
    with urllib.request.urlopen(url, timeout=120) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    got = sha256_of(part)
    if got != sha256:
        part.unlink()
        raise SystemExit(f"error: {dest.name} has SHA-256 {got}, expected {sha256}. Not using it. If the publisher "
                         "replaced the file on purpose, check it and update the pinned value in this script.")
    part.replace(dest)
    return dest


def pth_text(original: str) -> str:
    """The embeddable Python ignores PYTHONPATH and site-packages until its ._pth file says otherwise."""
    lines = [ln for ln in original.splitlines() if not ln.strip().startswith(("#import site", "import site"))]
    lines += [r"Lib\site-packages", "import site"]
    return "\n".join(lines) + "\n"


def package_report(site: Path) -> str:
    """One line per installed package with its version and licence, for the notices that ship in the zip."""
    rows = []
    for info in sorted(site.glob("*.dist-info"), key=lambda p: p.name.lower()):
        meta = (info / "METADATA").read_text(encoding="utf-8", errors="replace")
        field = lambda key: next((m.group(1).strip() for m in re.finditer(rf"^{key}: (.+)$", meta, re.M)), "")
        licence = field("License-Expression") or field("License") or next(
            (m.group(1).split("::")[-1].strip() for m in re.finditer(r"^Classifier: License :: (.+)$", meta, re.M)), "see its dist-info folder")
        rows.append(f"{field('Name')} {field('Version')}: {licence.splitlines()[0][:80]}")
    return "\n".join(rows) + "\n"


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def version_of_project() -> str:
    return re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)


def build(work: Path, zip_it=True) -> Path:
    cache, out = work / "cache", work / "out"
    bundle = out / NAME
    if bundle.exists():
        shutil.rmtree(bundle)
    py_zip = fetch(PYTHON["url"], PYTHON["sha256"], cache / "python" / Path(PYTHON["url"]).name)
    ff_zip = fetch(FFMPEG["url"], FFMPEG["sha256"], cache / "ffmpeg" / Path(FFMPEG["url"]).name)

    # Python
    py = bundle / "python"
    with zipfile.ZipFile(py_zip) as z:
        z.extractall(py)
    pth = py / f"python{PYTHON['tag']}._pth"
    pth.write_text(pth_text(pth.read_text()), encoding="utf-8")

    # book2audio and everything it needs, as wheels
    wheels, site = work / "wheels", py / "Lib" / "site-packages"
    shutil.rmtree(wheels, ignore_errors=True)
    run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", wheels, ROOT])
    run([sys.executable, "-m", "pip", "install", "--target", site, "--only-binary=:all:", "--platform", "win_amd64",
         "--python-version", f"{PYTHON['tag'][0]}.{PYTHON['tag'][1:]}", "--implementation", "cp", "--find-links",
         wheels, "book2audio[llm]", "pip"])
    shutil.rmtree(site / "bin", ignore_errors=True)  # console-script launchers point at the build computer's Python

    # ffmpeg (no ffplay: it is 19 MB and nothing here plays audio)
    ff = bundle / "ffmpeg"
    ff.mkdir()
    with zipfile.ZipFile(ff_zip) as z:
        top = z.namelist()[0].split("/")[0]
        for member in z.namelist():
            name = member[len(top) + 1:]
            if member.startswith(f"{top}/bin/") and name != "bin/ffplay.exe" and not member.endswith("/"):
                (ff / Path(name).name).write_bytes(z.read(member))
            elif name == "LICENSE.txt":
                (bundle / "licenses").mkdir(exist_ok=True)
                (bundle / "licenses" / "FFmpeg-LICENSE.txt").write_bytes(z.read(member))

    # the person's files
    lic = bundle / "licenses"
    lic.mkdir(exist_ok=True)
    for src, dst in ((HERE / "bundle" / "Start Book2Audio.bat", bundle), (HERE / "bundle" / "START HERE.txt", bundle),
                     (HERE / "bundle" / "THIRD-PARTY-NOTICES.txt", lic), (ROOT.parent / "LICENSE", lic / "book2audio-LICENSE.txt"),
                     (py / "LICENSE.txt", lic / "Python-LICENSE.txt")):
        shutil.copy(src, dst)
    (lic / "PACKAGES.txt").write_text("Python packages in this bundle (name version: licence). The full licence texts are in "
                                      "python\\Lib\\site-packages\\<package>.dist-info.\n\n" + package_report(site), encoding="utf-8")
    (lic / "BUILD-INFO.txt").write_text(f"book2audio {version_of_project()}\nPython {PYTHON['version']} (embeddable, "
                                        f"sha256 {PYTHON['sha256']})\nFFmpeg {FFMPEG['version']} (BtbN LGPL shared build, "
                                        f"sha256 {FFMPEG['sha256']})\n{FFMPEG['url']}\n", encoding="utf-8")
    verify(bundle)
    if not zip_it:
        return bundle
    target = out / f"{NAME}-{version_of_project()}-windows-x64.zip"
    print(f"zipping {target}", flush=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(bundle.rglob("*")):
            if f.is_file():
                z.write(f, Path(NAME) / f.relative_to(bundle))
    return target


def verify(bundle: Path) -> None:
    """Run what was just assembled, the way the person will: it must start, find its pieces and be LGPL."""
    py, ff = bundle / "python" / "python.exe", bundle / "ffmpeg" / "ffmpeg.exe"
    check = ("import pathlib, book2audio, bs4, pdfminer, pypdf, anthropic, pip; "
             "w = pathlib.Path(book2audio.__file__).parent / 'web'; "
             "assert (w / 'index.html').is_file() and (w / 'app.js').is_file(), 'the page files are missing'; "
             "print('python ok:', book2audio.__version__)")
    run([py, "-c", check])
    run([py, "-m", "book2audio", "--version"])
    banner = subprocess.run([ff, "-version"], capture_output=True, text=True, check=True).stdout
    if "--enable-gpl" in banner or "--enable-nonfree" in banner:
        raise SystemExit("error: this ffmpeg build is GPL or non-free; the bundle promises LGPL. Pick another build.")
    print(banner.splitlines()[0], "(LGPL)")
    run([bundle / "ffmpeg" / "ffprobe.exe", "-version"], stdout=subprocess.DEVNULL)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the portable Windows bundle (a zip with its own Python and ffmpeg).")
    ap.add_argument("--work", type=Path, default=HERE / "work", help="where downloads and the result go (needs ~600 MB; "
                    "not inside OneDrive or another synced folder)")
    ap.add_argument("--no-zip", action="store_true", help="stop after assembling the folder")
    args = ap.parse_args(argv)
    if "onedrive" in str(args.work.resolve()).lower():
        print("warning: this folder is synced by OneDrive and will upload several hundred MB. Use --work elsewhere.",
              file=sys.stderr)
    result = build(args.work.resolve(), not args.no_zip)
    print(f"\nDone: {result} ({result.stat().st_size / 1e6:.0f} MB)" if result.is_file() else f"\nDone: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
