#!/usr/bin/env python3
"""Fetch the Gemma 4 Developer Agent competition data into harness/.
 
Usage:
    python scripts/get_data.py --list       # show what's in the competition
    python scripts/get_data.py              # light: the small text files only
    python scripts/get_data.py --full       # everything (~22 GB) + wheelhouse
    python scripts/get_data.py --wheels     # just the wheelhouse
 
Light mode pulls only what is useful without a GPU: the task file, the harness
spec and the sample submission. Snapshots, graphs and embeddings are large and
useless on a laptop, so they are --full only.
 
Requires the kaggle CLI and credentials (KAGGLE_USERNAME/KAGGLE_KEY, or
~/.kaggle/kaggle.json), and you must have accepted the competition rules.
 
Nothing here is committed: harness/ is gitignored. Competition data must not be
redistributed to anyone who has not joined the competition.
"""
 
from __future__ import annotations
 
import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
 
COMP = "gemma-4-developer-agent"
WHEELHOUSE = "metric/gemma-4-developer-agent-wheelhouse"
 
# Small, useful without a GPU. Paths are best-effort: --list shows the truth,
# and a miss here is reported rather than fatal.
LIGHT_FILES = ["tasks.jsonl", "HARNESS_README.md"]
 
 
def run(cmd: list[str], dry: bool) -> int:
    print("  $ " + " ".join(cmd))
    if dry:
        return 0
    return subprocess.call(cmd)
 
 
def need_cli() -> None:
    if shutil.which("kaggle") is None:
        sys.exit(
            "kaggle CLI not found. Install it with:  pip install kaggle\n"
            "Then set KAGGLE_USERNAME and KAGGLE_KEY, or place kaggle.json in\n"
            "  ~/.kaggle/  (Windows: %USERPROFILE%\\.kaggle\\)"
        )
 
 
def unzip_inplace(dest: Path, dry: bool) -> None:
    """kaggle delivers multi-file downloads as a zip; expand and remove it."""
    for z in sorted(dest.glob("*.zip")):
        print(f"  unzip {z.name}")
        if dry:
            continue
        with zipfile.ZipFile(z) as zf:
            zf.extractall(dest)
        z.unlink()
 
 
def fetch_light(dest: Path, dry: bool) -> None:
    missing = []
    for name in LIGHT_FILES:
        if (dest / name).exists():
            print(f"  have  {name}")
            continue
        rc = run(
            ["kaggle", "competitions", "download", COMP, "-f", name, "-p", str(dest)],
            dry,
        )
        if rc != 0:
            missing.append(name)
    unzip_inplace(dest, dry)
    if missing:
        print(
            "\nCould not fetch: "
            + ", ".join(missing)
            + "\nRun --list to see the real file names, then fetch with -f."
        )
 
 
def fetch_full(dest: Path, dry: bool) -> None:
    print("  ~22 GB — this takes a while")
    run(["kaggle", "competitions", "download", COMP, "-p", str(dest)], dry)
    unzip_inplace(dest, dry)
 
 
def fetch_wheels(dest: Path, dry: bool) -> None:
    wheels = dest / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    run(["kaggle", "datasets", "download", WHEELHOUSE, "-p", str(wheels)], dry)
    unzip_inplace(wheels, dry)
 
 
def check_gitignored(dest: Path) -> None:
    """A loud warning beats 22 GB in git history."""
    try:
        rc = subprocess.call(
            ["git", "check-ignore", "-q", str(dest / "tasks.jsonl")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return
    if rc != 0:
        print(
            f"\nWARNING: {dest}/ does not appear to be gitignored.\n"
            f"         Add '{dest.name}/' to .gitignore and commit it BEFORE\n"
            f"         downloading. Competition data must not be committed."
        )
 
 
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", default=Path("harness"), type=Path)
    ap.add_argument("--full", action="store_true", help="everything (~22 GB)")
    ap.add_argument("--wheels", action="store_true", help="wheelhouse only")
    ap.add_argument("--list", action="store_true", help="list competition files")
    ap.add_argument("--dry-run", action="store_true", help="print commands only")
    args = ap.parse_args()
 
    need_cli()
 
    if args.list:
        return run(
            ["kaggle", "competitions", "files", COMP, "--page-size", "200"],
            args.dry_run,
        )
 
    args.dest.mkdir(parents=True, exist_ok=True)
    check_gitignored(args.dest)
 
    if args.wheels:
        fetch_wheels(args.dest, args.dry_run)
    elif args.full:
        fetch_full(args.dest, args.dry_run)
        fetch_wheels(args.dest, args.dry_run)
    else:
        fetch_light(args.dest, args.dry_run)
 
    print(f"\ndone -> {args.dest}/")
    return 0
 
 
if __name__ == "__main__":
    raise SystemExit(main())

