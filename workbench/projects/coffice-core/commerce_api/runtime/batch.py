"""Schema-bound serial batch plans; cannot run shell commands or Python modules."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from ..core.contracts import Period, ReportRequest
from ..core.errors import CommerceError, UsageError
from .storage import atomic_json, read_json


async def run_batch(engine, plan_file: Path | None = None, *, resume: str | None = None, recover=True):
    if resume:
        state = read_json(engine.paths.file("batches", resume))
        if not state:
            raise UsageError("批量任务不存在")
    else:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        if set(plan) - {"name", "reports"} or not isinstance(plan.get("reports"), list) or not plan["reports"]:
            raise UsageError("批量计划只接受 name 和非空 reports")
        requests = []
        for item in plan["reports"]:
            allowed = {"platform", "kind", "backend", "profile", "date", "month", "from", "to", "account_id"}
            if set(item) - allowed:
                raise UsageError("批量计划包含未登记字段")
            spec = engine.registry.report(item["platform"], item["kind"], item.get("backend"))
            period = Period.parse(day=item.get("date"), month=item.get("month"), start=item.get("from"), end=item.get("to"), default=spec.default_period)
            requests.append(ReportRequest(spec.platform, spec.kind, spec.backend, item["profile"], period, account_id=item.get("account_id")).public())
        state = {"id": uuid.uuid4().hex, "name": plan.get("name", "reports"), "requests": requests, "results": {}, "pending_run_id": None, "status": "running"}
    file = engine.paths.file("batches", state["id"])
    atomic_json(file, state)
    for index, value in enumerate(state["requests"]):
        if str(index) in state["results"]:
            continue
        try:
            result = await engine.execute(ReportRequest.restore(value), resume=state.get("pending_run_id"), recover=recover)
            state["results"][str(index)] = result
            state["pending_run_id"] = None
            atomic_json(file, state)
        except CommerceError as exc:
            state.update(status=exc.code.lower(), pending_run_id=exc.details.get("run_id"))
            atomic_json(file, state)
            exc.details["batch_id"] = state["id"]
            raise
    state["status"] = "success"
    atomic_json(file, state)
    return state
