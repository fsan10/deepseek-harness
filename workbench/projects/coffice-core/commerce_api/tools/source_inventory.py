"""Read selected legacy functions without importing or executing their modules."""
from __future__ import annotations

import argparse
import ast
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--names", nargs="*")
    parser.add_argument("--constants", action="store_true")
    args = parser.parse_args()
    source = args.path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if args.names and node.name in args.names:
                print(f"# {args.path}:{node.lineno}\n{ast.get_source_segment(source, node)}\n")
            elif not args.names:
                print(f"{node.lineno}: {type(node).__name__} {node.name}")
        elif args.constants and isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id.isupper() for t in targets):
                print(f"{node.lineno}: {ast.get_source_segment(source, node)}")


if __name__ == "__main__":
    main()
