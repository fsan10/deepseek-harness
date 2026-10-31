"""Read connection metadata shape, never proxy addresses or credentials."""
import argparse
import json

from commerce_api.integrations.legacy.profiles import client


def shape(value):
    if isinstance(value, dict):
        return {key: shape(child) for key, child in value.items()}
    if isinstance(value, list):
        return {"count": len(value)}
    if value in (None, ""):
        return "empty"
    if isinstance(value, bool):
        return value
    return type(value).__name__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    instance = client()
    records = instance.call("list_profiles", {})
    if isinstance(records, dict):
        records = records.get("profiles", records.get("data", []))
    matches = [item for item in records if item.get("name") == args.profile]
    if len(matches) != 1:
        raise ValueError("Profile must match exactly once")
    item = matches[0]
    print(json.dumps({"keys": list(item), "connection_fields": {key: shape(value) for key, value in item.items()
        if any(part in key.lower() for part in ("proxy", "network", "ip", "connection"))}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
