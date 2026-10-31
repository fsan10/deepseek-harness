"""Canonical dates, account scopes, capabilities and report receipts."""
from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from .errors import UsageError

CN = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    mode: str = "day"

    def __post_init__(self):
        if self.start > self.end:
            raise UsageError("开始日期不能晚于结束日期")
        if self.mode not in ("day", "month", "range"):
            raise UsageError("日期模式必须为 day、month 或 range")

    def public(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "mode": self.mode}

    def timestamp(self, *, end: bool = False, milliseconds: bool = False) -> int:
        value = datetime.combine(self.end if end else self.start, time(23, 59, 59) if end else time.min, CN).timestamp()
        return int(value * (1000 if milliseconds else 1))

    def times(self) -> tuple[str, str]:
        return f"{self.start.isoformat()} 00:00:00", f"{self.end.isoformat()} 23:59:59"

    def timestamps(self, *, milliseconds=False, end_millisecond=0) -> tuple[int, int]:
        return (self.timestamp(milliseconds=milliseconds),
                self.timestamp(end=True, milliseconds=milliseconds) + (end_millisecond if milliseconds else 0))

    @classmethod
    def parse(cls, *, day: str | None = None, month: str | None = None,
              start: str | None = None, end: str | None = None,
              default: str = "yesterday", today: date | None = None) -> "Period":
        if sum([bool(day), bool(month), bool(start or end)]) > 1:
            raise UsageError("--date、--month、--from/--to 只能选择一组")
        try:
            if day:
                target = date.fromisoformat(day)
                return cls(target, target)
            if month:
                if len(month) != 7:
                    raise ValueError()
                first = date.fromisoformat(month + "-01")
                return cls(first, first.replace(day=calendar.monthrange(first.year, first.month)[1]), "month")
            if start or end:
                if not start or not end:
                    raise UsageError("--from 和 --to 必须同时指定")
                return cls(date.fromisoformat(start), date.fromisoformat(end), "range" if start != end else "day")
        except ValueError:
            raise UsageError("日期须为 YYYY-MM-DD，月份须为 YYYY-MM") from None
        current = today or datetime.now(CN).date()
        last = current - timedelta(days=1)
        return cls(current - timedelta(days=30), last, "range") if default == "last30" else cls(last, last)


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    platform: str
    company: str
    shop: str
    enabled: bool = True


@dataclass(frozen=True)
class ReportSpec:
    platform: str
    kind: str
    backend: str
    name: str
    handler: str
    modes: tuple[str, ...] = ("day", "range", "month")
    default_period: str = "yesterday"
    sources: tuple[str, ...] = ()

    def public(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BackendSpec:
    platform: str
    id: str
    label: str
    domains: tuple[str, ...]
    home: str
    client: str
    login: str
    parent: str | None = None


@dataclass(frozen=True)
class PlatformSpec:
    id: str
    name: str
    aliases: tuple[str, ...]
    backends: tuple[BackendSpec, ...]
    reports: tuple[ReportSpec, ...]


@dataclass
class ReportRequest:
    platform: str
    kind: str
    backend: str
    profile: str
    period: Period
    timeout: float = 300
    poll_interval: float = 3
    account_id: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict:
        result = asdict(self)
        result["period"] = self.period.public()
        return result

    @classmethod
    def restore(cls, value: dict) -> "ReportRequest":
        period = value["period"]
        return cls(**{**value, "period": Period(date.fromisoformat(period["start"]), date.fromisoformat(period["end"]), period["mode"])})


@dataclass
class ReportResult:
    status: str
    run_id: str
    platform: str
    backend: str
    kind: str
    profile: str
    requested_period: dict
    actual_period: dict | None = None
    files: list[dict] = field(default_factory=list)
    row_count: int | None = None
    identity: dict = field(default_factory=dict)

    def public(self) -> dict:
        return asdict(self)
