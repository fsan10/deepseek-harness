"""One executable for every platform. No business work happens at import."""
from __future__ import annotations

import asyncio
import sys

from ..core.errors import CommerceError
from ..core.registry import Registry
from .dispatch import dispatch
from .help import build_parser
from .output import envelope, write


def main(argv=None) -> int:
    registry = Registry()
    parser = build_parser(registry)
    try:
        args = parser.parse_args(argv)
        if not args.command and not args.version:
            parser.print_help()
            return 0
        result = asyncio.run(dispatch(args, registry))
        write(envelope(result, meta={"cli": "commerce", "transport": "direct_http"}), sys.stdout)
        return 0
    except CommerceError as exc:
        write(envelope(error=exc.public()), sys.stdout)
        return exc.exit_code
    except KeyboardInterrupt:
        write(envelope(error={"code": "INTERRUPTED", "message": "已中断；已提交任务可按原 run_id 续跑"}), sys.stdout)
        return 130
    except Exception as exc:
        # Tracebacks may contain request URLs and credentials. Diagnostics expose
        # only the exception type; the frozen run retains safe stage information.
        write(envelope(error={"code": "INTERNAL_ERROR", "message": type(exc).__name__}), sys.stdout)
        return 1


def entrypoint():
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
