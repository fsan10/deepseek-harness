"""千川财务 API -> 与旧日结一致的 CSV；无浏览器或 DOM 读取。"""
import csv
from pathlib import Path

from commerce_api.core.errors import ContractError, IdentityMismatch, NotReady
from commerce_api.core.parsing import require_rows
from commerce_api.runtime.files import receipt
from ...backends.qianchuan.api.reports.promotion import COLUMNS, business_date, values


async def download(ctx, request):
    if request.account_id and str(request.account_id) != ctx.client.advertiser():
        raise IdentityMismatch("请求广告账户与已认证千川会话不一致")
    params = {"start_day": request.period.start.isoformat(), "end_day": request.period.end.isoformat(),
              "page_num": 1, "page_size": 100}
    rows = []
    expected = None
    for page in range(1, 101):
        body = await ctx.client.finance("finance/transaction", {**params, "page_num": page})
        data = body.get("data") or {}
        metadata = data.get("page") or {}
        try:
            total = int(metadata["total"])
        except (KeyError, ValueError, TypeError):
            raise ContractError("千川日结分页缺少有效 total") from None
        if expected is not None and total != expected:
            raise ContractError("千川日结分页总量发生变化，请重试读取")
        expected = total
        current = require_rows(data.get("result"), "千川日结")
        # The response includes a summary row when has_sum is true. Only rows
        # with an explicit date are business records.
        rows.extend(r for r in current if str(r.get("date", "")) not in {"", "合计", "总计", "汇总", "sum", "total"})
        if len(rows) >= total:
            break
        if not current:
            raise ContractError("千川分页提前结束")
    else:
        raise ContractError("千川日结分页超过上限")
    selected = [r for r in rows if request.period.start <= business_date(r["date"]) <= request.period.end]
    days = [business_date(r["date"]) for r in selected]
    if len(days) != len(set(days)):
        raise ContractError("千川日结日期重复")
    if not selected:
        raise NotReady("千川尚未返回请求日期的日结记录")
    expected_days = (request.period.end - request.period.start).days + 1
    if len(selected) != expected_days:
        raise NotReady("千川日结未覆盖完整请求日期，拒绝将部分数据标为完成")
    directory = ctx.paths.root / "downloads" / ctx.run.id
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"qianchuan_promotion_{request.period.start}_to_{request.period.end}.csv"
    temporary = target.with_suffix(".csv.part")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow([title for _, title in COLUMNS])
            writer.writerows(values(r) for r in sorted(selected, key=lambda r: business_date(r["date"])))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    ctx.run.state["files"].append(receipt(target, period=request.period.public()))
    ctx.run.save()
    return ctx.result(row_count=len(selected))
