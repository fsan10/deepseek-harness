"""Verify signing material in an encrypted capture, without network or tokens."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from commerce_api.platforms.douyin.backends.merchant.signing import derive_material
from commerce_api.runtime.sessions import protect
from commerce_api.core.errors import CommerceError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    capture = json.loads(protect((args.directory / "context.enc").read_bytes(), decrypt=True))
    seen = set()
    for record in reversed(capture["records"]):
        parts = urlsplit(record["url"])
        if parts.hostname != "fxg.jinritemai.com" or "a_bogus=" not in parts.query or parts.path in seen:
            continue
        seen.add(parts.path)
        try:
            material = derive_material(record["url"], capture["user_agent"], (record.get("post_data") or "").encode())
            print(json.dumps({"path": parts.path, "verified": True,
                "sdk_version": material["sdk_version"], "sdk_minor": material["sdk_minor"],
                "aid": material["aid"], "page_id": material["page_id"],
                "geometry_fields": len(material["geometry"].split("|"))}, ensure_ascii=False))
        except CommerceError as exc:
            print(json.dumps({"path": parts.path, "verified": False, "code": exc.code}))


if __name__ == "__main__":
    main()
