"""Run the repository's authoritative local verification commands."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(label: str, args: list[str]) -> None:
    print(f"\n==> {label}", flush=True)
    completed = subprocess.run(args, cwd=ROOT, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--architecture-only",
        action="store_true",
        help="Run only the fast architecture and version contract tests.",
    )
    parser.add_argument(
        "--package",
        action="store_true",
        help="Also build a wheel after tests and static checks pass.",
    )
    args = parser.parse_args()

    if args.architecture_only:
        _run(
            "architecture contracts",
            [sys.executable, "-m", "pytest", "tests/architecture", "-q"],
        )
        return

    _run("test suite", [sys.executable, "-m", "pytest"])
    _run("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"])
    _run("mypy", [sys.executable, "-m", "mypy", "src"])
    if args.package:
        _run("wheel build", [sys.executable, "-m", "build", "--wheel"])


if __name__ == "__main__":
    main()
