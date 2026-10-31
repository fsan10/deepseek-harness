"""Static undefined-global check using Python's own symbol tables."""
from __future__ import annotations

import builtins
import symtable
from pathlib import Path

from ..runtime.storage import PROJECT


def main():
    errors = []
    for path in PROJECT.rglob("*.py"):
        if any(part in {".venv", ".runtime", "__pycache__"} for part in path.parts):
            continue
        try:
            table = symtable.symtable(path.read_text(encoding="utf-8-sig"), str(path), "exec")
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(PROJECT)}: syntax: {exc.msg}")
            continue
        names = set(table.get_identifiers()) | set(dir(builtins)) | {"__file__", "__name__", "__package__"}

        def inspect(scope):
            for symbol in scope.get_symbols():
                if symbol.is_global() and symbol.is_referenced() and symbol.get_name() not in names:
                    errors.append(f"{path.relative_to(PROJECT)}:{scope.get_lineno()} {scope.get_name()}: {symbol.get_name()}")
            for child in scope.get_children():
                inspect(child)
        inspect(table)
    for error in errors:
        print(error)
    print(f"undefined_globals={len(errors)}")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
