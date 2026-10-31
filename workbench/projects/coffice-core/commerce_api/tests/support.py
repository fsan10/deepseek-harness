import tempfile
from pathlib import Path

from commerce_api.runtime.storage import Paths, atomic_json
from commerce_api.core.contracts import Profile


def owned_temporary(test):
    base = Paths().root / "test-work"
    base.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(dir=base)
    test.addCleanup(temporary.cleanup)
    return Paths(temporary.name)


def fictional_profile(paths):
    profile = Profile("fictional-profile", "Example test shop", "douyin", "Example Company", "Example Shop")
    atomic_json(paths.file("config", "profiles"), {profile.name: profile.__dict__})
    return profile
