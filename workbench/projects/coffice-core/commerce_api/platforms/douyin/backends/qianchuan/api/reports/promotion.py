"""千川日结接口契约；CSV 保持现有十四列。"""
from datetime import datetime

from commerce_api.core.errors import ContractError

COLUMNS = (("date", "日期"), ("cost", "余额总消耗(元)"),
    ("no_grant_cost", "非赠款消耗(元)"), ("grant_cost", "赠款消耗(元)"),
    ("deduction_cost", "消返红包消耗(元)"), ("no_limit_deduction_cost", "立减红包消耗(元)"),
    ("company_wallet_cost", "共享钱包消耗(元)"), ("shared_grant_cost", "共享赠款消耗"),
    ("income", "总存入(元)"), ("transfer_in", "总转入(元)"), ("transfer_out", "总转出(元)"),
    ("balance", "总余额(元)"), ("grant_balance", "赠款余额(元)"), ("no_grant_balance", "非赠款余额(元)"))


def business_date(value):
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ContractError("千川日结行日期格式异常")


def values(row):
    missing = [key for key, _ in COLUMNS if key not in row]
    if missing:
        raise ContractError("千川日结字段缺失", details={"missing_fields": missing})
    return [business_date(row["date"]).isoformat()] + [str(row[key]) for key, _ in COLUMNS[1:]]
