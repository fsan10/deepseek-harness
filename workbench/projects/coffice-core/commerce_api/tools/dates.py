"""Inspect business dates only, never whole captured responses or URLs."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from commerce_api.runtime.sessions import protect

FIELDS = {"accDate", "setDate", "businessDate", "billDate", "startTimeStr", "endTimeStr", "date",
          "startDate", "endDate", "beginDate", "start_day", "end_day", "scene", "report_type", "file_type", "templateName",
          "create_time_start", "create_time_end", "timeType", "userType", "order_by", "order", "source", "tab", "page", "pageSize",
          "namespace", "skipStatus", "billType", "querySettleAccount", "_input_charset", "period", "level4Type", "type", "split", "bizType"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--match", required=True)
    args = parser.parse_args()
    value = json.loads(protect((args.directory / "context.enc").read_bytes(), decrypt=True))
    for record in value["records"]:
        if not re.search(args.match, record["url"]):
            continue
        found = {}
        def visit(node):
            if isinstance(node, dict):
                for key, child in node.items():
                    if key in FIELDS and isinstance(child, (str, int)):
                        found.setdefault(key, set()).add(str(child)[:100])
                    elif isinstance(child, (dict, list)):
                        visit(child)
                    elif isinstance(child, str) and child[:1] in {"{", "["}:
                        try:
                            visit(json.loads(child))
                        except ValueError:
                            pass
            elif isinstance(node, list):
                for child in node:
                    visit(child)
        visit(record["response"])
        if record.get("post_data"):
            try:
                visit(json.loads(record["post_data"]))
            except ValueError:
                from urllib.parse import parse_qs
                visit({k: v[0] for k, v in parse_qs(record["post_data"]).items()})
        from urllib.parse import parse_qs
        visit({k: v[0] for k, v in parse_qs(urlsplit(record["url"]).query).items()})
        print(json.dumps({"path": urlsplit(record["url"]).path, "values": {k: sorted(v) for k, v in found.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
