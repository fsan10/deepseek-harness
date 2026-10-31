from __future__ import annotations

import threading
import time
from collections.abc import Callable


class HealthAggregator:
    """Aggregate module-owned health checks without duplicating their SQL."""

    def __init__(
        self,
        database,
        influencer_module,
        file_ingest_module,
        dashboard_proxy,
        *,
        application_version: str,
        features: list[str],
        cache_seconds: float = 2.0,
        automation_module=None,
    ):
        self.database = database
        self.influencer_module = influencer_module
        self.file_ingest_module = file_ingest_module
        self.dashboard_proxy = dashboard_proxy
        self.application_version = application_version
        self.features = list(features)
        self.cache_seconds = max(0.0, float(cache_seconds))
        self.automation_module = automation_module
        self._lock = threading.Lock()
        self._cached_at = 0.0
        self._cached: dict | None = None

    @staticmethod
    def _check(module: str, callback: Callable[[], dict], errors: list[dict]) -> dict:
        try:
            return dict(callback())
        except Exception as exc:  # individual module failures must not hide the remaining checks
            errors.append({
                "module": module,
                "code": f"{module}.unavailable",
                "kind": "database",
                "message": "数据库连接失败",
                "detail": type(exc).__name__,
            })
            return {"error": True}

    @staticmethod
    def _missing(module: str, data: dict, keys: tuple[str, ...], failures: list[dict]) -> None:
        for key in keys:
            if data.get("error"):
                return
            if data.get(key) is not True:
                failures.append({
                    "module": module,
                    "code": f"{module}.{key}",
                    "kind": "migration",
                    "message": "指标表未初始化" if module in {"bank", "influencer"} else "请先执行迁移",
                })

    @staticmethod
    def _refresh_failure(module: str, data: dict, key: str, failures: list[dict]) -> None:
        refresh = data.get(key)
        if not isinstance(refresh, dict) or refresh.get("status") != "failed":
            return
        failures.append({
            "module": module,
            "code": f"{module}.{key}.failed",
            "kind": "service",
            "message": "后台看板数据刷新失败",
            "detail": refresh.get("last_error") or "unknown",
        })

    def _build(self) -> dict:
        errors: list[dict] = []
        bank = self._check("bank", self.database.health, errors)
        influencer = self._check("influencer", self.influencer_module.database.health, errors)
        product = self._check("influencer_product", self.influencer_module.product_categories.health, errors)
        if not product.get("error"):
            influencer.update(product)
        elif not influencer.get("error"):
            influencer["product_health_error"] = True
        ingest_raw = self._check("ingest", self.file_ingest_module.service.health, errors)
        automation = self._check("automation", self.automation_module.service.health, errors) if self.automation_module else {"enabled": False}
        dashboard = self.dashboard_proxy.health() if self.dashboard_proxy else {"proxy_ready": False}

        worker_keys = ("worker_heartbeat_ready", "active_worker_count", "worker_last_seen_at")
        worker = {key: ingest_raw.get(key) for key in worker_keys}
        ingest = {key: value for key, value in ingest_raw.items() if key not in worker_keys}

        failures: list[dict] = []
        self._missing("bank", bank, ("ods_ready", "dwd_ready", "operation_ready"), failures)
        self._missing(
            "influencer",
            influencer,
            (
                "assignment_ready", "target_ready", "ads_ready", "product_category_ready",
                "product_ready", "product_mapping_ready",
            ),
            failures,
        )
        self._missing("ingest", ingest, ("ingest_ready", "etl_ready", "fee_mapping_ready"), failures)
        self._refresh_failure("influencer", influencer, "metrics_refresh", failures)
        self._refresh_failure("influencer", influencer, "dashboard_refresh", failures)
        if ingest.get("ingest_ready") is True and worker.get("worker_heartbeat_ready") is True:
            if int(worker.get("active_worker_count") or 0) <= 0:
                failures.append({
                    "module": "worker",
                    "code": "worker.inactive",
                    "kind": "worker",
                    "message": "Worker未运行",
                })
        if dashboard.get("proxy_ready") is not True:
            failures.append({
                "module": "dashboard",
                "code": "dashboard.proxy_unavailable",
                "kind": "service",
                "message": "DataEase嵌入代理未运行",
            })
        failures.extend(errors)

        modules = {
            "bank": bank,
            "influencer": influencer,
            "ingest": ingest,
            "worker": worker,
            "dashboard": dashboard,
            "automation": automation,
        }
        result = {
            "ready": not failures,
            "modules": modules,
            "failed": failures,
            "application_version": self.application_version,
            "features": self.features,
        }
        # Transitional flat fields keep existing internal/external readers working.
        result.update(bank)
        result.update(influencer)
        result.update(ingest)
        result.update(worker)
        return result

    def snapshot(self, *, force: bool = False) -> dict:
        now = time.monotonic()
        with self._lock:
            if not force and self._cached is not None and now - self._cached_at < self.cache_seconds:
                return self._cached
            self._cached = self._build()
            self._cached_at = time.monotonic()
            return self._cached

    def legacy_ingest(self) -> dict:
        modules = self.snapshot()["modules"]
        return {**modules["ingest"], **modules["worker"], "deprecated": True, "replacement": "/api/health"}

    def legacy_influencer(self) -> dict:
        data = dict(self.snapshot()["modules"]["influencer"])
        data.update({"deprecated": True, "replacement": "/api/health"})
        return data
