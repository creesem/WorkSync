"""``worksync-gui`` entry point placeholder."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="worksync-gui", description="Local WorkSync workspace.")
    parser.parse_args(argv)
    print("worksync-gui is not implemented yet (ticket 11).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
