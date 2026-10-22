# SPDX-License-Identifier: GPL-3.0-or-later
"""Run checkout integration tests in a separate, factory-startup Blender."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", help="Blender executable; otherwise use blender on PATH")
    parser.add_argument("--output", type=Path, default=ROOT / "tests/output/generality.json")
    parser.add_argument("--timeout", type=float, default=180)
    options = parser.parse_args()
    binary = options.blender or shutil.which("blender")
    if not binary:
        parser.error("Pass --blender or add Blender to PATH")
    if options.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [binary, "--background", "--factory-startup", "--disable-autoexec",
               "--python-exit-code", "1", "--python", str(ROOT / "tests/blender/run_tests.py"),
               "--", "--output", str(output)]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=options.timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Could not finish Blender integration tests: {exc}", file=sys.stderr)
        return 1
    log = result.stdout + result.stderr
    (output.parent / "blender.log").write_text(log, encoding="utf-8")
    print(log, end="")
    if result.returncode:
        return result.returncode
    if not output.is_file():
        print("Blender did not create a test report", file=sys.stderr)
        return 1
    report = json.loads(output.read_text(encoding="utf-8"))
    if not report.get("all_passed"):
        print("Blender integration tests failed", file=sys.stderr)
        return 1
    print(f"Blender integration: {report['passed_count']}/{report['case_count']} passed")
    dynamic_path = output.with_name('dynamic.json')
    if not dynamic_path.is_file():
        print('Dynamic modifier report is missing', file=sys.stderr)
        return 1
    dynamic = json.loads(dynamic_path.read_text(encoding='utf-8'))
    if not dynamic.get('all_passed'):
        print('Dynamic modifier integration tests failed', file=sys.stderr)
        return 1
    print(f"Dynamic modifiers: {dynamic['passed_count']}/{dynamic['case_count']} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
