"""A single validated registry drives CLI help, schemas and dispatch."""
from __future__ import annotations

import importlib
from .contracts import BackendSpec, PlatformSpec, ReportSpec
from .errors import UsageError, ContractError

KINDS = {"orders": "order", "settlements": "settlement", "funds": "fund", "promotion_fee": "promotion",
         "订单": "order", "结算": "settlement", "资金": "fund", "推广费": "promotion"}


def load_symbol(reference: str):
    module, separator, name = reference.partition(":")
    if not separator or not module.startswith("commerce_api.platforms."):
        raise ContractError("处理函数必须来自代码登记的平台模块")
    return getattr(importlib.import_module(module), name)


class Registry:
    def __init__(self, platforms=None):
        if platforms is None:
            from ..platforms.catalog import platforms as load_platforms
            platforms = load_platforms()
        self.platforms = {p.id: p for p in platforms}
        self.aliases = {alias.casefold(): p.id for p in platforms for alias in (p.id, p.name, *p.aliases)}
        for platform in platforms:
            seen = set()
            backends = {b.id for b in platform.backends}
            for spec in platform.reports:
                key = (spec.kind, spec.backend)
                if key in seen or spec.backend not in backends or spec.platform != platform.id:
                    raise ContractError("报表能力声明重复或后台归属无效")
                seen.add(key)

    def platform(self, value: str) -> PlatformSpec:
        canonical = self.aliases.get(value.casefold())
        if not canonical:
            raise UsageError("未知平台，请运行 commerce platforms")
        return self.platforms[canonical]

    def backend(self, platform: str, backend: str) -> BackendSpec:
        result = next((b for b in self.platform(platform).backends if b.id == backend), None)
        if not result:
            raise UsageError("该平台没有指定后台")
        return result

    def report(self, platform: str, kind: str, backend: str | None = None) -> ReportSpec:
        kind = KINDS.get(kind, kind)
        candidates = [r for r in self.platform(platform).reports if r.kind == kind and (backend is None or r.backend == backend)]
        if len(candidates) != 1:
            choices = ", ".join(f"{r.kind}@{r.backend}" for r in self.platform(platform).reports)
            raise UsageError("报表类型不存在或后台不唯一，请明确 --backend", hint=choices)
        return candidates[0]

    def public(self, platform: str | None = None) -> list[dict]:
        selected = [self.platform(platform)] if platform else self.platforms.values()
        return [{"id": p.id, "name": p.name, "aliases": list(p.aliases),
            "backends": [{"id": b.id, "name": b.label, "parent": b.parent} for b in p.backends],
            "reports": [r.public() for r in p.reports]} for p in selected]

    def schema(self, platform: str) -> dict:
        p = self.platform(platform)
        return {"platform": p.id, "command": f"commerce {p.id} report download",
            "required": ["kind", "profile"], "properties": {
                "kind": {"enum": sorted({r.kind for r in p.reports})},
                "backend": {"enum": [b.id for b in p.backends]},
                "profile": {"type": "string", "description": "完整 Profile 名称"},
                "date": {"type": "string", "format": "date"},
                "month": {"type": "string", "pattern": r"^\\d{4}-\\d{2}$"},
                "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"},
                "timeout": {"type": "number", "exclusiveMinimum": 0},
                "poll_interval": {"type": "number", "exclusiveMinimum": 0}},
            "period_selection": "date OR month OR (from AND to)",
            "capabilities": [r.public() for r in p.reports],
            "effects": {"query": "read", "create_export": "export", "send_code": "verification"},
            "browser": "authentication_only", "automatic_health_checks_default": False}

