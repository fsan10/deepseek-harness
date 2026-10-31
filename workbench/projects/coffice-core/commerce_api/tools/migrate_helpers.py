"""Extract explicitly selected pure legacy helpers into owned platform API files.

This development tool never imports source modules, rewrites the originals, or
copies their browser, CLI, download or profile implementations.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

from ..runtime.storage import PROJECT

HEADER = '''from __future__ import annotations

import copy
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit, urlparse

from commerce_api.core.parsing import (ApiError, CN_TZ, TZ_CN, as_int, clone_payload,
    date_to_ms, parse_period_key, parse_json_value, sff_utc_bounds)

'''


def extract(source: Path, destination: Path, names: list[str]):
    destination = destination.resolve()
    if not destination.is_relative_to(PROJECT.resolve()):
        raise ValueError("Destination must stay inside commerce_api")
    if destination.exists():
        raise ValueError("Refusing to overwrite an existing implementation")
    text = source.read_text(encoding="utf-8-sig")
    tree = ast.parse(text)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    constants = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node
    wanted = set(names)
    pending = list(names)
    selected = {}
    forbidden = {"requests", "httpx", "subprocess", "socket", "async_playwright", "open", "browser", "manager"}
    while pending:
        name = pending.pop()
        node = functions.get(name) or constants.get(name)
        if node is None:
            raise ValueError(f"Unknown pure source helper: {name}")
        dependencies = {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        if dependencies & forbidden:
            raise ValueError(f"Not a pure helper: {name}: {dependencies & forbidden}")
        if any(isinstance(n, ast.Attribute) and n.attr in {"evaluate", "goto", "locator", "get_by_role", "expect_response"} for n in ast.walk(node)):
            raise ValueError(f"Browser operation found: {name}")
        selected[id(node)] = node
        for dependency in dependencies:
            if dependency not in wanted and (dependency in functions or dependency in constants):
                wanted.add(dependency)
                pending.append(dependency)
    segments = [ast.get_source_segment(text, node) for node in sorted(selected.values(), key=lambda n: n.lineno)]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f'"""Pure report contracts migrated from {source.name}; no browser implementation."""\n' + HEADER + "\n\n".join(segments) + "\n", encoding="utf-8")
    print(f"{destination.relative_to(PROJECT)}: {len(segments)} pure definitions")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("names", nargs="+")
    args = parser.parse_args()
    extract(args.source, args.destination, args.names)


if __name__ == "__main__":
    main()
