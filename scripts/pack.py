#!/usr/bin/env python3
"""Build and validate submission.zip for the Gemma 4 Developer Agent competition.

Usage:
    python scripts/pack.py                    # build dist/submission.zip
    python scripts/pack.py --check            # validate only, do not write
    python scripts/pack.py --src submission --out dist/submission.zip

Validation performed before anything is written:
  1. agent.yaml exists and will land at the ARCHIVE ROOT (not nested)
  2. every file has an allowed extension
  3. every agent YAML names the required model string
  4. no junk files (__pycache__, .DS_Store, .pyc, dotfiles, empty dirs)
  5. adapter directories contain the two required files
  6. total size is under the size cap

Exit code is 0 on success, 1 on any validation failure. Nothing is written
when validation fails, so a bad submission can never reach dist/.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

# --- competition constants -------------------------------------------------
# Verify these against HARNESS_README.md and the competition Evaluation page.
# They are the values documented at the time of writing; the official sources win.

# One model per submission, enforced by the harness via ALLOWED_MODEL_NAMES.
# Any of these is valid, but every agent YAML in one submission must name the
# SAME one, so a sweep across models cannot accidentally ship a mixed zip.
ALLOWED_MODELS = {
    "gemma-4-31b-it-qat-w4a16-ct",
    "gemma-4-12b-it-qat-w4a16-ct",
    "gemma-4-e4b-it-qat-w4a16-ct",
    "gemma-4-e2b-it-qat-w4a16-ct",
}

ALLOWED_EXTENSIONS = {".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"}

# Reported as 3 GiB. Confirm before relying on it.
MAX_TOTAL_BYTES = 3 * 1024**3

ADAPTER_REQUIRED_FILES = {"adapter_config.json", "adapter_model.safetensors"}

# Official optional files the harness reads directly from the submission root.
# Nothing in agent.yaml references them, so the reachability check below would
# flag them as orphans -- but they MUST ship: HARNESS_README 2.2 / 7.1 documents
# eval_config.yaml as part of the submission contract, loaded by
# load_submission_eval_config() in scripts/inference.py. Leaving it out drops
# the scored run onto the harness defaults of 60 min / 100 tool calls per task.
HARNESS_FILES = {"eval_config.yaml"}

JUNK_NAMES = {
    "__pycache__",
    "dataset-metadata.json",
    ".DS_Store",
    ".ipynb_checkpoints",
    ".pytest_cache",
    ".git",
    ".gitignore",
    "Thumbs.db",
    ".venv",
    "venv",
    ".mypy_cache",
    ".ruff_cache",
}


class Problem(Exception):
    """A validation failure that must stop the build."""


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024.0
    return f"{n}B"


def collect_files(src: Path) -> list[Path]:
    """Every file under src, with junk directories pruned."""
    files: list[Path] = []
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if any(part in JUNK_NAMES for part in rel.parts):
            continue
        if p.is_file():
            files.append(p)
    return files


# --- individual checks -----------------------------------------------------


def check_agent_yaml_at_root(src: Path, errors: list[str]) -> None:
    """agent.yaml must sit at the archive root.

    The commonest packaging mistake is zipping the containing folder, which
    puts agent.yaml one level down and fails validation on Kaggle.
    """
    if not (src / "agent.yaml").is_file():
        errors.append(
            f"agent.yaml not found at {src}/agent.yaml. It must be at the "
            f"ROOT of the archive, not inside a subfolder."
        )


def check_extensions(src: Path, files: list[Path], errors: list[str]) -> None:
    for f in files:
        if f.suffix.lower() not in ALLOWED_EXTENSIONS:
            errors.append(
                f"disallowed extension {f.suffix or '(none)'!r}: "
                f"{f.relative_to(src)}  (allowed: "
                f"{', '.join(sorted(ALLOWED_EXTENSIONS))})"
            )


def check_model_string(src: Path, files: list[Path], errors: list[str]) -> None:
    """Every YAML that declares an agent must name the required model.

    A sub-agent that omits or inherits the model is a common validation
    failure, so this checks each YAML that looks like an agent definition.
    """
    yamls = [f for f in files if f.suffix.lower() in {".yaml", ".yml"}]
    if not yamls:
        errors.append("no YAML files found at all")
        return

    seen_models: set[str] = set()

    for f in yamls:
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"not valid UTF-8: {f.relative_to(src)}")
            continue

        declares_agent = "model:" in text or "instruction:" in text
        if not declares_agent:
            continue

        # Substring matching would accept a typo'd longer name, so compare the
        # value of the model key exactly.
        named = [
            line.split(":", 1)[1].strip().strip("\"'")
            for line in text.splitlines()
            if line.strip().startswith("model:")
        ]
        if not named:
            errors.append(
                f"{f.relative_to(src)} declares an agent but has no model: key. "
                f"A sub-agent that inherits the model fails validation."
            )
        for value in named:
            if value not in ALLOWED_MODELS:
                errors.append(
                    f"{f.relative_to(src)} names model {value!r}, which is not "
                    f"an allowed model. Pick one of: "
                    f"{', '.join(sorted(ALLOWED_MODELS))}"
                )
            seen_models.add(value)


    if len(seen_models) > 1:
        errors.append(
            f"submission names more than one model ({', '.join(sorted(seen_models))}). "
            f"The harness allows exactly one per submission."
        )
    elif seen_models <= ALLOWED_MODELS and seen_models:
        print(f"ok    model {next(iter(seen_models))}")


def check_adapters(src: Path, errors: list[str]) -> None:
    adapters_dir = src / "adapters"
    if not adapters_dir.is_dir():
        return  # adapters are optional

    for d in sorted(adapters_dir.iterdir()):
        if not d.is_dir():
            errors.append(f"unexpected file in adapters/: {d.relative_to(src)}")
            continue
        present = {p.name for p in d.iterdir() if p.is_file()}
        missing = ADAPTER_REQUIRED_FILES - present
        if missing:
            errors.append(
                f"adapter {d.name!r} is missing {', '.join(sorted(missing))}"
            )


def check_adapter_references(src: Path, files: list[Path], errors: list[str]) -> None:
    """Every `adapter: <name>` in a YAML must have a matching directory."""
    adapters_dir = src / "adapters"
    available = (
        {d.name for d in adapters_dir.iterdir() if d.is_dir()}
        if adapters_dir.is_dir()
        else set()
    )

    for f in (f for f in files if f.suffix.lower() in {".yaml", ".yml"}):
        for lineno, line in enumerate(
            f.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped.startswith("adapter:"):
                continue
            name = stripped.split(":", 1)[1].strip().strip("\"'")
            if name and name not in available:
                errors.append(
                    f"{f.relative_to(src)}:{lineno} references adapter {name!r} "
                    f"but adapters/{name}/ does not exist"
                )


def check_includes(src: Path, files: list[Path], errors: list[str]) -> None:
    """!include paths resolve relative to the file containing them.

    A path that is correct in agent.yaml is wrong inside sub_agents/*.yaml,
    which is an easy mistake to make and an annoying one to debug.
    """
    for f in (f for f in files if f.suffix.lower() in {".yaml", ".yml"}):
        for lineno, line in enumerate(
            f.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "!include" not in line:
                continue
            target = line.split("!include", 1)[1].strip().strip("\"'")
            if not target:
                continue
            resolved = (f.parent / target).resolve()
            if not resolved.is_file():
                errors.append(
                    f"{f.relative_to(src)}:{lineno} !include {target!r} does not "
                    f"resolve (looked for {resolved}). Paths are relative to the "
                    f"file containing the directive."
                )


def check_reachable(src: Path, files: list[Path], errors: list[str]) -> None:
    """Every file must be reachable from agent.yaml.

    An unreferenced file is either dead weight or, worse, something the harness
    picks up and parses against a schema we guessed at. The v1 submission
    carried an eval_config.yaml that no directive referenced; it passed every
    other check here and the scored run threw before any task ran.
    """
    root = src / "agent.yaml"
    if not root.is_file():
        return  # already reported by check_agent_yaml_at_root

    seen: set[Path] = set()
    queue = [root]
    while queue:
        current = queue.pop()
        if current in seen or not current.is_file():
            continue
        seen.add(current)
        if current.suffix.lower() not in {".yaml", ".yml"}:
            continue

        text = current.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            target = None
            if "!include" in stripped:
                target = stripped.split("!include", 1)[1].strip().strip("\"'")
            elif stripped.startswith("config_path:"):
                # sub-agents are pulled in by path, not by !include
                target = stripped.split(":", 1)[1].strip().strip("\"'")
            if target:
                queue.append(current.parent / target)

    # adapter directories are referenced by name, not path
    adapter_files = {
        f for f in files if "adapters" in f.relative_to(src).parts
    }

    harness_files = {
        f for f in files
        if str(f.relative_to(src)).replace("\\", "/") in HARNESS_FILES
    }

    orphans = [
        f for f in files
        if f not in seen and f not in adapter_files and f not in harness_files
    ]
    for f in sorted(orphans):
        rel = f.relative_to(src)
        detail = (
            "  <-- a YAML the harness may parse. Official optional files "
            "belong in HARNESS_FILES; anything else is dead weight."
            if f.suffix.lower() in {".yaml", ".yml"}
            else ""
        )
        errors.append(
            f"{rel} is not referenced from agent.yaml by !include or "
            f"config_path:{detail}"
        )


def check_size(src: Path, files: list[Path], errors: list[str]) -> int:
    total = sum(f.stat().st_size for f in files)
    if total > MAX_TOTAL_BYTES:
        errors.append(
            f"total size {human(total)} exceeds the {human(MAX_TOTAL_BYTES)} cap"
        )
    return total


# --- build -----------------------------------------------------------------


def validate(src: Path) -> tuple[list[Path], int]:
    if not src.is_dir():
        raise Problem(f"source directory not found: {src}")

    files = collect_files(src)
    if not files:
        raise Problem(f"no files found under {src}")

    errors: list[str] = []
    check_agent_yaml_at_root(src, errors)
    check_extensions(src, files, errors)
    check_model_string(src, files, errors)
    check_adapters(src, errors)
    check_adapter_references(src, files, errors)
    check_includes(src, files, errors)
    check_reachable(src, files, errors)
    total = check_size(src, files, errors)

    if errors:
        raise Problem(
            "validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )
    return files, total


def build(src: Path, out: Path, files: list[Path]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            # arcname is relative to src, so agent.yaml lands at the root
            z.write(f, arcname=str(f.relative_to(src)).replace("\\", "/"))


def verify_archive(out: Path) -> None:
    """Re-open the finished zip and confirm agent.yaml is at the root."""
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    if "agent.yaml" not in names:
        raise Problem(
            f"agent.yaml is not at the root of the finished archive. "
            f"Top-level entries: {sorted({n.split('/')[0] for n in names})}"
        )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default="submission", type=Path)
    ap.add_argument("--out", default=Path("dist/submission.zip"), type=Path)
    ap.add_argument(
        "--check", action="store_true", help="validate only, write nothing"
    )
    args = ap.parse_args()

    try:
        files, total = validate(args.src)
    except Problem as e:
        print(f"FAIL  {e}", file=sys.stderr)
        return 1

    print(f"ok    {len(files)} files, {human(total)}")
    for f in files:
        print(f"      {str(f.relative_to(args.src)).replace(chr(92), '/')}")

    if args.check:
        print("ok    --check given, nothing written")
        return 0

    try:
        build(args.src, args.out, files)
        verify_archive(args.out)
    except Problem as e:
        print(f"FAIL  {e}", file=sys.stderr)
        args.out.unlink(missing_ok=True)
        return 1

    print(f"ok    wrote {args.out}  ({human(args.out.stat().st_size)} zipped)")
    print(f"      sha256 {sha256(args.out)}")
    print()
    print("submit with:")
    print(
        f'  kaggle competitions submit -c gemma-4-developer-agent '
        f'-f {args.out} -m "describe this run"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

