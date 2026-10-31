"""Durable run states. Non-idempotent intent is saved before any request."""
from __future__ import annotations

import hashlib
import json
import uuid

from ..core.contracts import ReportRequest, now_iso
from ..core.errors import ContractError, OutcomeUnknown
from .storage import Paths, atomic_json, read_json

SECRET_KEYS = {"cookies", "cookie", "password", "answer", "token", "headers", "url", "payload", "ticket", "signature", "endpoint"}


def business_key(request: ReportRequest, profile_id: str) -> str:
    value = request.public()
    value = {k: v for k, v in value.items() if k not in {"timeout", "poll_interval"}}
    return hashlib.sha256(json.dumps({"request": value, "profile_id": profile_id}, sort_keys=True).encode()).hexdigest()


def public_state(value):
    if isinstance(value, dict):
        return {k: public_state(v) for k, v in value.items() if k.lower() not in SECRET_KEYS and not k.lower().endswith("_url")}
    if isinstance(value, list):
        return [public_state(v) for v in value]
    return value


class Run:
    def __init__(self, paths: Paths, state: dict):
        self.paths = paths
        self.state = state
        self.id = state["id"]

    @classmethod
    def create(cls, paths: Paths, request: ReportRequest, profile_id: str) -> "Run":
        frozen = request.public()
        fingerprint = business_key(request, profile_id)
        run = cls(paths, {"id": uuid.uuid4().hex, "version": 1, "fingerprint": fingerprint,
            "request": frozen, "profile_id": profile_id, "status": "running", "stage": "prepare",
            "created_at": now_iso(), "updated_at": now_iso(), "operations": {}, "files": []})
        run.save()
        return run

    @classmethod
    def load(cls, paths: Paths, identifier: str) -> "Run":
        value = read_json(paths.file("runs", identifier))
        if not value or value.get("id") != identifier or value.get("version") != 1:
            raise ContractError("执行记录不存在或格式不兼容")
        return cls(paths, value)

    def save(self):
        self.state["updated_at"] = now_iso()
        atomic_json(self.paths.file("runs", self.id), public_state(self.state))

    def update(self, **values):
        self.state.update(values)
        self.save()

    def begin(self, name: str, *, reconcile=False):
        previous = self.state["operations"].get(name)
        if previous and previous["status"] in {"sending", "unknown", "confirmed"} and not reconcile:
            raise OutcomeUnknown("上次提交结果未确认，须先查询原任务；禁止自动再次提交", stage=name)
        self.state["operations"][name] = {"status": "sending", "started_at": now_iso()}
        self.update(stage=name)

    def confirmed(self, name: str, **references):
        self.state["operations"][name] = {"status": "confirmed", "confirmed_at": now_iso(), **references}
        self.save()

    def reference(self, name: str, key="task_id"):
        return self.state["operations"].get(name, {}).get(key)
