"""Per-run encrypted transient responses; signed links never enter run JSON."""
import json
import os
import uuid

from .sessions import protect


def load(paths, identifier):
    target = paths.file("private", identifier, ".enc")
    return json.loads(protect(target.read_bytes(), decrypt=True)) if target.is_file() else {}


def save(paths, identifier, value):
    target = paths.file("private", identifier, ".enc")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as output:
            output.write(protect(json.dumps(value, ensure_ascii=False).encode()))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
