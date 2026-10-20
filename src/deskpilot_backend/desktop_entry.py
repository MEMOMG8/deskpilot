"""Packaged entrypoint, also runnable as a module for diagnostics."""

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    # GUI bootloaders have no console streams; third-party download progress
    # writers must still have a valid file-like object.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    parser = argparse.ArgumentParser(prog="DeskPilot")
    parser.add_argument("--self-test", type=Path, metavar="REPORT_JSON")
    args = parser.parse_args()
    from deskpilot_backend.installation_guard import desktop_installation_guard
    with desktop_installation_guard():
        if args.self_test is not None:
            from deskpilot_backend.packaged_check import run_checks
            return run_checks(args.self_test)
        from deskpilot_backend.desktop import main as run_desktop
        return run_desktop()


if __name__ == "__main__":
    raise SystemExit(main())
