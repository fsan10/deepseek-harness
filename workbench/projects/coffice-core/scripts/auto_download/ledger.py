"""Durable, secret-free telemetry for external CLI runs and archive receipts."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(path)


class RunJournal:
    def __init__(self, root: Path, run_id: str, lane: str, *, external: bool = True,
                 trigger_type: str = "manual"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", run_id):
            raise ValueError("非法运行标识")
        self.path = Path(root) / ".automation_logs" / "report_ledger" / f"{run_id}.json"
        self.data = {"version": 1, "run_id": run_id, "execution_lane": lane,
                     "external": external, "process_id": os.getpid(),
                     "trigger_type": trigger_type,
                     "started_at": datetime.now().astimezone().isoformat(), "events": []}

    def emit(self, event: str, payload: dict) -> None:
        if event == "component_event":
            return  # Existing component telemetry owns detailed browser diagnostics.
        allowed = {"profile_name", "metadata", "step_name", "module_name", "execution_lane", "started_at",
                   "finished_at", "duration_seconds", "status", "return_code", "artifacts", "checkpoint_reused",
                   "business_period", "reason", "date", "targets", "ingest"}
        safe = {key: value for key, value in payload.items() if key in allowed}
        if 'ingest' in safe:
            ingest = safe['ingest'] or {}
            safe['ingest'] = {key: ingest[key] for key in ('ingest_run_id', 'submitted', 'reused') if key in ingest}
        if "metadata" in safe:
            safe["metadata"] = {key: value for key, value in safe["metadata"].items() if key in {"platform", "company", "shop"}}
        if "targets" in safe:
            # Never persist arbitrary CLI args or Profile credential fields.
            safe["targets"] = [{"profile_name": t.get("profile_name"), "profile_id": t.get("profile_id"),
                                "metadata": {k: v for k, v in (t.get("metadata") or {}).items() if k in {"platform", "company", "shop"}},
                                "steps": [{"name": s.get("name"), "module": s.get("module"),
                                           "args": (["--report", s["args"][s["args"].index("--report") + 1]] if "--report" in (s.get("args") or []) else [])}
                                          for s in t.get("steps") or []]}
                               for t in safe["targets"]]
        self.data["events"].append({"event": event, "payload": safe})
        atomic_json(self.path, self.data)


def read_receipts(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def confirmed_no_data(module: str, output: str) -> bool:
    """Only an explicit, completed zero-row query proves an empty report."""
    lines = {line.strip() for line in output.splitlines()}
    return module == 'kuaishou_settlement_download' and {
        '结算查询记录数：0', '结算查询无记录，跳过导出',
    }.issubset(lines)


def journal_process_running(data: dict) -> bool | None:
    """False only when process exit is confirmed; unknown stays unknown."""
    pid = data.get("process_id")
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False if ctypes.get_last_error() == 87 else None
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
