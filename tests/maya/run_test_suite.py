"""Run each Maya integration test file in a fresh mayapy process.

Maya standalone and third-party plug-ins do not reliably support repeated scene
initialization/teardown across an entire pytest suite in one process.  Process
isolation also makes each file reproducible when run by itself.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


TEST_FILES = (
    "test_as_fk_bake.py",
    "test_humanik_session.py",
    "test_semantic_bake.py",
    "test_transaction_scene.py",
    "test_ui_smoke.py",
    "test_validation_scene.py",
    "test_work_mode.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mayapy", required=True, help="Path to mayapy executable")
    args = parser.parse_args()

    test_dir = Path(__file__).resolve().parent
    failures: list[str] = []
    for filename in TEST_FILES:
        path = test_dir / filename
        print(f"\n=== Maya test: {filename} ===", flush=True)
        result = subprocess.run(
            [
                args.mayapy,
                "-m",
                "pytest",
                str(path),
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            env=os.environ.copy(),
            check=False,
        )
        if result.returncode:
            failures.append(f"{filename} (exit {result.returncode})")

    if failures:
        print("\nFailed Maya test processes:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("\nAll Maya test processes passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
