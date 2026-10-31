"""TCP health check that does not require an authenticated HTTP session."""

from __future__ import annotations

import argparse
import socket


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    with socket.create_connection((args.host, args.port), timeout=args.timeout):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
