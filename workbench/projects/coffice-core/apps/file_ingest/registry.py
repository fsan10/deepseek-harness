from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_EXTENSIONS = (".csv", ".xls", ".xlsx", ".xlsm")


@dataclass(frozen=True)
class ReportSpec:
    report_type: str
    report_name: str
    platform_code: str
    platform_name: str
    loader: str
    target_table: str
    data_domain: str
    target_tables: tuple[str, ...] = ()
    default_sheet_name: str | None = None
    header_row_no: int = 1
    data_start_row_no: int = 2
    etl_keys: tuple[str, ...] = ()
    extensions: tuple[str, ...] = SUPPORTED_EXTENSIONS
    note: str = ""

    def public_dict(self) -> dict:
        value = asdict(self)
        value["extensions"] = list(self.extensions)
        value["etl_keys"] = list(self.etl_keys)
        value["target_tables"] = list(self.target_tables)
        return value


@dataclass(frozen=True)
class EtlSpec:
    key: str
    label: str
    script: str
    args: tuple[str, ...] = ()
    priority: int = 100
    feeds_platform_bank_summary: bool = False
    enabled: bool = True
    note: str = ""

    @property
    def command_path(self) -> Path:
        return PROJECT_ROOT / self.script


def report(
    report_type: str,
    report_name: str,
    platform_code: str,
    platform_name: str,
    loader: str,
    target_table: str,
    data_domain: str,
    *etl_keys: str,
    note: str = "",
    default_sheet_name: str | None = None,
    header_row_no: int = 1,
    data_start_row_no: int = 2,
    target_tables: tuple[str, ...] = (),
) -> ReportSpec:
    return ReportSpec(
        report_type=report_type,
        report_name=report_name,
        platform_code=platform_code,
        platform_name=platform_name,
        loader=loader,
        target_table=target_table,
        data_domain=data_domain,
        target_tables=target_tables,
        default_sheet_name=default_sheet_name,
        header_row_no=header_row_no,
        data_start_row_no=data_start_row_no,
        etl_keys=tuple(etl_keys),
        note=note,
    )


ACTIVE_REPORTS: tuple[ReportSpec, ...] = (
    report("douyin_order", "订单", "douyin", "抖音", "etl/douyin/load_douyin_order_ods.py", "ods.ods_douyin_order_raw", "order", "douyin_gsv", "operating_sales", "influencer_performance"),
    report("douyin_fund", "资金", "douyin", "抖音", "etl/douyin/load_douyin_fund_ods.py", "ods.ods_douyin_fund_raw", "fund", "douyin_platform_expense", "douyin_main_business_income"),
    report("douyin_settlement", "结算", "douyin", "抖音", "etl/douyin/load_douyin_settlement_ods.py", "ods.ods_douyin_settlement_raw", "settlement", "douyin_settlement", "douyin_platform_expense", "douyin_main_business_income", data_start_row_no=3),
    report("douyin_qianchuan", "千川推广费", "douyin", "抖音", "etl/douyin/load_douyin_qianchuan_finance_ods.py", "ods.ods_douyin_qianchuan_finance_raw", "ad", "promotion_expense", default_sheet_name="data", data_start_row_no=3),

    report("jd_order", "订单", "jd", "京东", "etl/jd/load_jd_order_ods.py", "ods.ods_jd_order_raw", "order", "jd_gsv", "operating_sales", "influencer_performance"),
    report("jd_fund", "资金", "jd", "京东", "etl/jd/load_jd_fund_ods.py", "ods.ods_jd_fund_raw", "fund", "jd_main_business_finance"),
    report("jd_settlement", "结算", "jd", "京东", "etl/jd/load_jd_settlement_ods.py", "ods.ods_jd_settlement_raw", "settlement", "jd_settlement", "jd_main_business_finance"),
    report("jd_tong_ad", "京东通推广费", "jd", "京东", "etl/jd/load_jd_tong_promotion_expense_ods.py", "ods.ods_jd_tong_promotion_expense_raw", "ad", "promotion_expense", default_sheet_name="sheet1"),
    report("jd_union_ad", "京东联盟推广费", "jd", "京东", "etl/jd/load_jd_union_promotion_expense_ods.py", "ods.ods_jd_union_promotion_expense_raw", "ad", "promotion_expense", default_sheet_name="Sheet1"),

    report("tmall_order", "订单", "tmall", "天猫", "etl/tmall/load_tmall_order_ods.py", "ods.ods_tmall_order_raw", "order", "tmall_gsv", "operating_sales", "influencer_performance"),
    report("tmall_alipay_fund", "支付宝账户资金", "tmall", "天猫", "etl/tmall/load_tmall_alipay_fund_ods.py", "ods.ods_tmall_alipay_fund_raw", "alipay_fund", "tmall_main_business_finance", "tmall_settlement_from_funds", header_row_no=5, data_start_row_no=6),
    report("tmall_aggregate_fund", "聚合账户资金", "tmall", "天猫", "etl/tmall/load_tmall_aggregate_fund_ods.py", "ods.ods_tmall_aggregate_fund_raw", "aggregate_fund", "tmall_main_business_finance", "tmall_settlement_from_funds", default_sheet_name="sheet1"),
    report("tmall_settlement_income", "结算收入", "tmall", "天猫", "etl/tmall/load_tmall_settlement_income_ods.py", "ods.ods_tmall_settlement_income_raw", "settlement", "tmall_settlement_from_funds", "tmall_main_business_finance", note="历史结算单已不再新增导入；补导历史文件时由资金结算ETL按旧结算单口径合并历史月份。"),
    report("tmall_settlement_expense", "结算支出", "tmall", "天猫", "etl/tmall/load_tmall_settlement_expense_ods.py", "ods.ods_tmall_settlement_expense_raw", "settlement", "tmall_settlement_from_funds", "tmall_main_business_finance", note="历史结算单已不再新增导入；补导历史文件时由资金结算ETL按旧结算单口径合并历史月份。"),
    report("tmall_taobao_union_ad", "淘宝联盟推广费", "tmall", "天猫", "etl/tmall/load_tmall_taobao_union_promotion_expense_ods.py", "ods.ods_tmall_taobao_union_promotion_expense_raw", "ad", "promotion_expense"),
    report("tmall_wanxiangtai_ad", "万相台推广费", "tmall", "天猫", "etl/tmall/load_tmall_wanxiangtai_promotion_expense_ods.py", "ods.ods_tmall_wanxiangtai_promotion_expense_raw", "ad", "promotion_expense"),

    report("ks_order", "订单", "ks", "快手", "etl/ks/load_ks_order_ods.py", "ods.ods_ks_order_raw", "order", "ks_gsv", "operating_sales", "influencer_performance"),
    report("ks_fund", "资金", "ks", "快手", "etl/ks/load_ks_fund_ods.py", "ods.ods_ks_fund_raw", "fund", "ks_platform_expense", "ks_main_business_income"),
    report("ks_settlement", "结算", "ks", "快手", "etl/ks/load_ks_settlement_ods.py", "ods.ods_ks_settlement_raw", "settlement", "ks_settlement", "ks_platform_expense", "ks_main_business_income"),

    report("pdd_order", "订单", "pdd", "拼多多", "etl/pdd/load_pdd_order_ods.py", "ods.ods_pdd_order_raw", "order", "pdd_gsv", "operating_sales", "influencer_performance"),
    report("pdd_settlement", "结算", "pdd", "拼多多", "etl/pdd/load_pdd_settlement_ods.py", "ods.ods_pdd_settlement_raw", "settlement", "pdd_settlement", "pdd_main_business_finance", header_row_no=5, data_start_row_no=6),
    report("pdd_ad", "推广费", "pdd", "拼多多", "etl/pdd/load_pdd_promotion_expense_ods.py", "ods.ods_pdd_promotion_expense_raw", "ad", "promotion_expense", default_sheet_name="Sheet0"),

    report("wechat_channels_order", "订单", "wechat_channels", "视频号", "etl/wechat_channels/load_wechat_channels_order_ods.py", "ods.ods_wechat_channels_order_raw", "order", "wechat_channels_gsv", "operating_sales", "influencer_performance", "promotion_expense"),
    report("wechat_channels_settlement", "结算", "wechat_channels", "视频号", "etl/wechat_channels/load_wechat_channels_settlement_ods.py", "ods.ods_wechat_channels_settlement_raw", "settlement", "wechat_channels_settlement", "wechat_channels_main_business_finance"),

    report("xhs_order", "订单", "xhs", "小红书", "etl/xhs/load_xhs_order_ods.py", "ods.ods_xhs_order_raw", "order", "xhs_gsv", "operating_sales", "influencer_performance"),
    report("xhs_fund", "资金", "xhs", "小红书", "etl/xhs/load_xhs_fund_ledger_ods.py", "ods.ods_xhs_fund_ledger_raw", "fund", default_sheet_name="资金账单明细", note="使用新版“资金账单明细”格式；当前仅入ODS，无下游指标。"),
    report(
        "xhs_settlement", "结算", "xhs", "小红书",
        "etl/xhs/load_xhs_settlement_ods.py", "ods.ods_xhs_settlement_income_raw",
        "settlement", "xhs_settlement", "xhs_main_business_finance",
        target_tables=(
            "ods.ods_xhs_settlement_income_raw",
            "ods.ods_xhs_settlement_expense_raw",
        ),
        note="单个结算工作簿按订单结算、其他服务款两个工作表自动分流入ODS。",
    ),
)


DEPRECATED_LOADERS = {
    "etl/tmall/load_tmall_fund_ods.py": "旧天猫日级资金汇总，生产链路已切换为支付宝账户与聚合账户明细。",
    "etl/xhs/load_xhs_fund_ods.py": "旧版小红书“货款明细”格式，资金入口已切换为“资金账单明细”；历史原始表保留。",
    "etl/xhs/load_xhs_settlement_income_ods.py": "小红书结算已切换为单文件多工作表自动分流。",
    "etl/xhs/load_xhs_settlement_expense_ods.py": "小红书结算已切换为单文件多工作表自动分流。",
}


ETL_SPECS: dict[str, EtlSpec] = {
    "douyin_gsv": EtlSpec("douyin_gsv", "抖音GSV", "etl/douyin/run_douyin_gsv_etl.py", priority=10),
    "jd_gsv": EtlSpec("jd_gsv", "京东GSV", "etl/jd/run_jd_gsv_etl.py", priority=10),
    "tmall_gsv": EtlSpec("tmall_gsv", "天猫GSV", "etl/tmall/run_tmall_gsv_etl.py", priority=10),
    "ks_gsv": EtlSpec("ks_gsv", "快手GSV", "etl/ks/run_ks_gsv_etl.py", priority=10),
    "pdd_gsv": EtlSpec("pdd_gsv", "拼多多GSV", "etl/pdd/run_pdd_gsv_etl.py", priority=10),
    "wechat_channels_gsv": EtlSpec("wechat_channels_gsv", "视频号GSV", "etl/wechat_channels/run_wechat_channels_gsv_etl.py", priority=10),
    "xhs_gsv": EtlSpec("xhs_gsv", "小红书GSV", "etl/xhs/run_xhs_gsv_etl.py", priority=10),
    "douyin_settlement": EtlSpec("douyin_settlement", "抖音结算指标", "etl/douyin/run_douyin_settlement_metrics_etl.py", priority=20),
    "jd_settlement": EtlSpec("jd_settlement", "京东结算指标", "etl/jd/run_jd_settlement_metrics_etl.py", priority=20),
    "ks_settlement": EtlSpec("ks_settlement", "快手结算指标", "etl/ks/run_ks_settlement_metrics_etl.py", priority=20),
    "pdd_settlement": EtlSpec("pdd_settlement", "拼多多结算指标", "etl/pdd/run_pdd_settlement_metrics_etl.py", priority=20),
    "wechat_channels_settlement": EtlSpec("wechat_channels_settlement", "视频号结算指标", "etl/wechat_channels/run_wechat_channels_settlement_metrics_etl.py", priority=20),
    "xhs_settlement": EtlSpec("xhs_settlement", "小红书结算指标", "etl/xhs/run_xhs_settlement_metrics_etl.py", priority=20),
    "tmall_settlement_from_funds": EtlSpec("tmall_settlement_from_funds", "天猫资金结算指标", "etl/tmall/run_tmall_settlement_from_funds_etl.py", priority=21, note="从支付宝账户资金与聚合账户资金提取结算收入和费用；同月存在旧结算单时以资金来源为准。"),
    "settlement_shared_ads": EtlSpec("settlement_shared_ads", "七平台共享结算 ADS", "etl/platform_finance/run_settlement_shared_ads_etl.py", priority=25),
    "douyin_platform_expense": EtlSpec("douyin_platform_expense", "抖音平台费用", "etl/douyin/run_douyin_platform_expense_etl.py", priority=30, feeds_platform_bank_summary=True),
    "ks_platform_expense": EtlSpec("ks_platform_expense", "快手平台费用", "etl/ks/run_ks_platform_expense_etl.py", priority=30, feeds_platform_bank_summary=True),
    "jd_main_business_finance": EtlSpec("jd_main_business_finance", "京东主营财务", "etl/jd/run_jd_main_business_finance_etl.py", priority=30, feeds_platform_bank_summary=True),
    "tmall_main_business_finance": EtlSpec("tmall_main_business_finance", "天猫主营财务", "etl/tmall/run_tmall_main_business_finance_etl.py", priority=30, feeds_platform_bank_summary=True),
    "pdd_main_business_finance": EtlSpec("pdd_main_business_finance", "拼多多主营财务", "etl/platform_finance/run_pdd_main_business_finance_etl.py", priority=30, feeds_platform_bank_summary=True),
    "wechat_channels_main_business_finance": EtlSpec("wechat_channels_main_business_finance", "视频号主营财务", "etl/platform_finance/run_wechat_channels_main_business_finance_etl.py", priority=30, feeds_platform_bank_summary=True),
    "xhs_main_business_finance": EtlSpec("xhs_main_business_finance", "小红书主营财务", "etl/platform_finance/run_xhs_main_business_finance_etl.py", priority=30, feeds_platform_bank_summary=True),
    "pdd_wechat_xhs_main_business_finance": EtlSpec(
        "pdd_wechat_xhs_main_business_finance",
        "拼多多视频号小红书主营财务（旧版兼容入口）",
        "etl/platform_finance/run_pdd_wechat_xhs_main_business_finance_etl.py",
        priority=30,
        feeds_platform_bank_summary=True,
        note="生产调度已拆分为拼多多、视频号和小红书三个独立主营财务ETL；保留旧入口供历史任务兼容。",
    ),
    "douyin_main_business_income": EtlSpec("douyin_main_business_income", "抖音主营收入", "etl/platform_finance/run_douyin_main_business_income_etl.py", priority=35),
    "ks_main_business_income": EtlSpec("ks_main_business_income", "快手主营收入", "etl/platform_finance/run_ks_main_business_income_etl.py", priority=35),
    "platform_main_business_income_shared_ads": EtlSpec("platform_main_business_income_shared_ads", "七平台共享主营收入 ADS", "etl/platform_finance/run_platform_main_business_income_shared_ads_etl.py", priority=40, feeds_platform_bank_summary=True),
    "douyin_ks_main_business_income": EtlSpec(
        "douyin_ks_main_business_income",
        "抖音快手主营收入（旧版兼容入口）",
        "etl/platform_finance/run_douyin_ks_main_business_income_etl.py",
        priority=35,
        feeds_platform_bank_summary=True,
        enabled=True,
        note="已拆分为抖音主营收入、快手主营收入和七平台共享主营收入 ADS；保留旧脚本供历史任务兼容。",
    ),
    "operating_sales": EtlSpec("operating_sales", "七平台运营成交", "etl/operating_sales/run_operating_sales_etl.py", priority=50),
    "influencer_performance": EtlSpec("influencer_performance", "七平台达人业绩", "etl/influencer_performance/run_multiplatform_influencer_performance_etl.py", priority=50),
    "influencer_commission": EtlSpec(
        "influencer_commission",
        "达人佣金（旧版已停用）",
        "etl/influencer_commission/run_influencer_commission_etl.py",
        priority=50,
        enabled=False,
        note="旧版独立指标链路；当前看板改用统一平台费用ADS按一级分类动态汇总。",
    ),
    "promotion_expense": EtlSpec("promotion_expense", "推广费", "etl/promotion_expense/run_promotion_expense_etl.py", args=("--skip-ods-load",), priority=50, feeds_platform_bank_summary=True),
    "finance_operating_config": EtlSpec("finance_operating_config", "经营预算配置", "etl/finance_operating_config/run_finance_operating_config_etl.py", priority=55),
    "bank_management": EtlSpec("bank_management", "银行经营指标", "etl/bank/run_bank_management_metrics_etl.py", priority=60, feeds_platform_bank_summary=True),
    "platform_bank_summary": EtlSpec("platform_bank_summary", "平台银行汇总", "etl/platform_bank_summary/run_platform_bank_summary_etl.py", priority=100),
}

# 银行经营指标只允许在财务提交锁定银行批次后触发。经营预算配置仍处于
# 测试阶段，暂不进入夜间/手动全量刷新；需要时仍可在测试库按ETL名称手动执行。
# 平台银行汇总由受影响的平台任务自动追加，不作为全量独立入口。
FULL_REFRESH_EXCLUDED_ETLS = frozenset({
    "bank_management",
    "platform_bank_summary",
    "finance_operating_config",
    "douyin_ks_main_business_income",
    "pdd_wechat_xhs_main_business_finance",
})

# 各平台结算指标刷新后统一收口七平台共享结算 ADS；主营财务刷新仍由
# platform_main_business_income_shared_ads 依赖负责，之后再进入平台银行汇总。
ETL_DEPENDENCIES = {
    "douyin_settlement": {"settlement_shared_ads"},
    "jd_settlement": {"settlement_shared_ads"},
    "tmall_settlement_from_funds": {"settlement_shared_ads"},
    "ks_settlement": {"settlement_shared_ads"},
    "pdd_settlement": {"settlement_shared_ads"},
    "wechat_channels_settlement": {"settlement_shared_ads"},
    "xhs_settlement": {"settlement_shared_ads"},
    "douyin_main_business_income": {"platform_main_business_income_shared_ads"},
    "ks_main_business_income": {"platform_main_business_income_shared_ads"},
    "jd_main_business_finance": {"platform_main_business_income_shared_ads"},
    "tmall_main_business_finance": {"platform_main_business_income_shared_ads"},
    "pdd_main_business_finance": {"platform_main_business_income_shared_ads"},
    "wechat_channels_main_business_finance": {"platform_main_business_income_shared_ads"},
    "xhs_main_business_finance": {"platform_main_business_income_shared_ads"},
    "pdd_wechat_xhs_main_business_finance": {"platform_main_business_income_shared_ads"},
}

ETL_TASK_PREREQUISITES = {
    # 视频号订单刷新 GSV 后，推广费 ETL 还负责重算共享的月度
    # GSV/推广费 ADS；没有这个依赖时月度表会继续保留旧快照。
    "promotion_expense": {
        "wechat_channels_gsv",
    },
    "settlement_shared_ads": {
        "douyin_settlement",
        "jd_settlement",
        "tmall_settlement_from_funds",
        "ks_settlement",
        "pdd_settlement",
        "wechat_channels_settlement",
        "xhs_settlement",
    },
    "platform_main_business_income_shared_ads": {
        "douyin_main_business_income",
        "ks_main_business_income",
        "jd_main_business_finance",
        "tmall_main_business_finance",
        "pdd_main_business_finance",
        "wechat_channels_main_business_finance",
        "xhs_main_business_finance",
        "pdd_wechat_xhs_main_business_finance",
    },
}


# 多平台汇总任务会读取所有平台的事实表，但“没有数据”是平台停用/店铺关闭
# 时的合法状态，不能作为调度失败条件。各平台 ETL 会把空来源按 0 值刷新，
# 只有来源对象不存在才属于配置/部署错误；来源表为空由各 ETL 自身按 0 值
# 刷新并输出警告。调度层不再把任何多平台汇总任务标成“待数据就绪”，这样
# 店铺关闭或平台尚未启用都不会阻断其它平台的刷新。
ETL_SOURCE_READINESS: dict[str, tuple[str, ...]] = {}
ETL_SOURCE_READINESS_FEEDERS: dict[str, dict[str, frozenset[str]]] = {}


REPORT_BY_TYPE = {item.report_type: item for item in ACTIVE_REPORTS}


def find_report(*, report_type: str | None = None, platform_name: str | None = None, report_name: str | None = None) -> ReportSpec:
    if report_type:
        item = REPORT_BY_TYPE.get(report_type.strip())
        if not item:
            raise ValueError(f"不支持的report_type：{report_type}")
        if platform_name and item.platform_name != platform_name.strip():
            raise ValueError("report_type与平台名称不一致")
        if report_name and item.report_name != report_name.strip():
            raise ValueError("report_type与报表名称不一致")
        return item
    matches = [
        item for item in ACTIVE_REPORTS
        if item.platform_name == (platform_name or "").strip()
        and item.report_name == (report_name or "").strip()
    ]
    if len(matches) != 1:
        raise ValueError(f"平台与报表名称必须唯一匹配：platform={platform_name}, report={report_name}, matched={len(matches)}")
    return matches[0]


def plan_etls(keys: set[str], *, include_summary: bool = True) -> list[EtlSpec]:
    unknown = keys.difference(ETL_SPECS)
    if unknown:
        raise ValueError(f"存在未登记ETL：{sorted(unknown)}")
    selected = {key for key in keys if ETL_SPECS[key].enabled}
    pending = list(selected)
    while pending:
        key = pending.pop()
        for dependency in ETL_DEPENDENCIES.get(key, set()):
            if dependency not in ETL_SPECS:
                raise ValueError(f"ETL依赖未登记：{key} -> {dependency}")
            if ETL_SPECS[dependency].enabled and dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    if include_summary and any(ETL_SPECS[key].feeds_platform_bank_summary for key in selected):
        selected.add("platform_bank_summary")
    return sorted((ETL_SPECS[key] for key in selected), key=lambda item: (item.priority, item.key))


def full_refresh_etl_keys() -> set[str]:
    return {
        key for key, spec in ETL_SPECS.items()
        if spec.enabled and key not in FULL_REFRESH_EXCLUDED_ETLS
    }
