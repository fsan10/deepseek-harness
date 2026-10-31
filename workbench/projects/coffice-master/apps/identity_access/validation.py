from __future__ import annotations


def text(value: object, label: str, *, minimum: int = 1, maximum: int = 100) -> str:
    result = str(value or "").strip()
    if not minimum <= len(result) <= maximum:
        raise ValueError(f"{label}长度须为{minimum}-{maximum}位")
    return result


def optional_int(value: object, label: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if result <= 0:
        raise ValueError(f"{label}必须是正整数")
    return result


def boolean(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (1, "1", "true", "True"):
        return True
    if value in (0, "0", "false", "False"):
        return False
    raise ValueError(f"{label}必须是布尔值")


def paging(query: dict[str, str]) -> tuple[int, int, int]:
    try:
        page = max(1, int(query.get("page", "1")))
        size = min(100, max(1, int(query.get("page_size", "20"))))
    except ValueError as exc:
        raise ValueError("分页参数必须是整数") from exc
    return page, size, (page - 1) * size

