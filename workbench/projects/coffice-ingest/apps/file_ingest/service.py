from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

VENDOR_DIR = Path(__file__).resolve().parents[1] / "fund_split_adjust" / ".vendor"
if VENDOR_DIR.is_dir():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import Json, RealDictCursor
except ImportError as exc:  # pragma: no cover - deployment dependency
    raise RuntimeError("数据导入中心需要psycopg2-binary") from exc

from .naming import guess_filename, normalize_name
from .registry import (
    ACTIVE_REPORTS,
    ETL_SPECS,
    ETL_SOURCE_READINESS_FEEDERS,
    ETL_SOURCE_READINESS,
    ETL_TASK_PREREQUISITES,
    PROJECT_ROOT,
    REPORT_BY_TYPE,
    find_report,
    full_refresh_etl_keys,
    plan_etls,
)


MIGRATION_FILES = [
    PROJECT_ROOT / "sql/common/368_file_ingest_automation_postgres.sql",
    PROJECT_ROOT / "sql/dim/369_dim_platform_fee_primary_category_postgres.sql",
    PROJECT_ROOT / "sql/common/370_xhs_settlement_multi_sheet_ingest_postgres.sql",
    PROJECT_ROOT / "sql/common/383_finance_operating_configuration_postgres.sql",
    PROJECT_ROOT / "sql/common/384_dwd_finance_operating_configuration_detail_postgres.sql",
    PROJECT_ROOT / "sql/common/385_dws_finance_operating_configuration_monthly_postgres.sql",
    PROJECT_ROOT / "sql/ads/386_ads_finance_operating_configuration_monthly_postgres.sql",
    PROJECT_ROOT / "sql/common/391_ingest_file_loader_diagnostics_postgres.sql",
    PROJECT_ROOT / "sql/douyin/ods/392_ods_douyin_order_phone_text_postgres.sql",
    PROJECT_ROOT / "sql/common/399_finance_permission_granularity_postgres.sql",
    PROJECT_ROOT / "sql/common/400_finance_configuration_console_postgres.sql",
    PROJECT_ROOT / "sql/common/401_finance_configuration_merge_postgres.sql",
    PROJECT_ROOT / "sql/common/403_etl_deferred_status_postgres.sql",
    PROJECT_ROOT / "sql/wechat_channels/ods/419_ods_wechat_channels_order_discount_split_postgres.sql",
    PROJECT_ROOT / "sql/common/421_platform_shop_company_current_context_postgres.sql",
    PROJECT_ROOT / "sql/douyin/ods/422_mask_douyin_order_sensitive_fields_postgres.sql",
    PROJECT_ROOT / "sql/dim/425_xhs_appeal_adjustment_income_policy_postgres.sql",
    PROJECT_ROOT / "sql/dim/426_dim_platform_fee_primary_category_auto_code_postgres.sql",
    PROJECT_ROOT / "sql/common/434_report_source_selection_postgres.sql",
    PROJECT_ROOT / "sql/dim/435_ks_xiyin_account_identity_postgres.sql",
    PROJECT_ROOT / "sql/common/438_ingest_api_source_postgres.sql",
]
from etl.platform_finance.operating_treatment import MIGRATION as OPERATING_MIGRATION, CREATE_FILES as OPERATING_CREATE_FILES, ADS_FILES as OPERATING_ADS_FILES
MIGRATION_FILES.extend(PROJECT_ROOT / "sql" / path for path in ('dim/464_platform_scene_normalization_postgres.sql', OPERATING_MIGRATION, *OPERATING_CREATE_FILES, OPERATING_ADS_FILES[0]))
MIGRATION_FILES.append(PROJECT_ROOT / 'sql/common/466_etl_execution_ownership_postgres.sql')
MIGRATION_FILES.append(PROJECT_ROOT / 'sql/common/467_incremental_etl_context_postgres.sql')
MIGRATION_FILES.extend(PROJECT_ROOT / 'sql/common' / name for name in (
    '468_ingest_source_day_selection_postgres.sql', '436_settlement_source_registry_postgres.sql',
    '460_finance_source_selection_postgres.sql', '469_ingest_coverage_workflow_postgres.sql',
    '470_wechat_settlement_source_selection_postgres.sql'))

MAX_UPLOAD_BYTES = int(os.getenv("INGEST_MAX_UPLOAD_MB", "200")) * 1024 * 1024
OUTPUT_LIMIT = 100_000
STALE_DRAFT_MINUTES = max(1, int(os.getenv("INGEST_DRAFT_TIMEOUT_MINUTES", "10")))

# ETL 子进程必须使用项目锁定的解释器，避免网关/Worker 的系统 Python
# 缺少 psycopg2 或 openpyxl 时出现“任务已创建但指标未刷新”。部署环境
# 没有项目虚拟环境时才回退到当前进程解释器。
ETL_PYTHON_CANDIDATES = (
    PROJECT_ROOT / ".venv/Scripts/python.exe",
    PROJECT_ROOT / ".venv/bin/python",
)

# 候选场景只使用稳定的业务类型/费用项。天猫、拼多多的二级分类由DWD同口径地
# 标准化为“业务类型 + 场景”，这样新增描述会进入原始费用列表，等待财务
# 人工决定一级分类；其他平台继续只暴露平台原生的稳定场景。
FEE_ODS_CANDIDATE_QUERIES = {
    "douyin": """
        SELECT 'fund'::text source_document_type,
               NULLIF(BTRIM("计费类型"),'') source_business_type,
               NULL::text source_description,
               BTRIM("动账场景") secondary_category_name
        FROM ods.ods_douyin_fund_raw WHERE NULLIF(BTRIM("动账场景"),'') IS NOT NULL
    """,
    "jd": """
        SELECT 'settlement'::text, NULLIF(BTRIM("单据类型"),''),
               NULL::text, BTRIM("费用项") AS secondary_category_name
        FROM ods.ods_jd_settlement_raw WHERE NULLIF(BTRIM("费用项"),'') IS NOT NULL
        UNION ALL
        SELECT 'fund', NULLIF(BTRIM("交易类型"),''),
               BTRIM("资金动账备注"),
               BTRIM("交易类型")
        FROM ods.ods_jd_fund_raw
        WHERE NULLIF(BTRIM("交易类型"),'') IS NOT NULL
    """,
    "ks": """
        SELECT 'fund'::text, NULLIF(BTRIM("业务类型"),''), BTRIM("描述"),
               CASE WHEN NULLIF(BTRIM("描述"),'') IS NULL THEN BTRIM("业务类型")
                    ELSE BTRIM("业务类型") || ' + ' || BTRIM("描述") END AS secondary_category_name
        FROM ods.ods_ks_fund_raw WHERE NULLIF(BTRIM("业务类型"),'') IS NOT NULL
    """,
    "pdd": """
        SELECT 'settlement'::text, NULLIF(BTRIM("账务类型"),''),
               BTRIM("业务描述"),
               BTRIM("账务类型") || ' + ' || BTRIM("业务描述") AS secondary_category_name
        FROM ods.ods_pdd_settlement_raw
        WHERE NULLIF(BTRIM("账务类型"),'') IS NOT NULL
    """,
    "wechat_channels": """
        SELECT 'settlement'::text, NULLIF(BTRIM("动帐类型"),''), NULL::text, BTRIM("动帐类型") AS secondary_category_name
        FROM ods.ods_wechat_channels_settlement_raw WHERE NULLIF(BTRIM("动帐类型"),'') IS NOT NULL
    """,
    "xhs": """
        SELECT 'settlement'::text, NULLIF(BTRIM("业务款项"),''), NULL::text, BTRIM("业务款项") AS secondary_category_name
        FROM ods.ods_xhs_settlement_expense_raw
        WHERE NULLIF(BTRIM("业务款项"),'') IS NOT NULL
          AND BTRIM("业务款项") <> '申诉调账'
        UNION ALL SELECT 'settlement',NULL,NULL,'平台佣金' FROM ods.ods_xhs_settlement_income_raw WHERE NULLIF(BTRIM("平台佣金"),'') IS NOT NULL
        UNION ALL SELECT 'settlement',NULL,NULL,'买手佣金' FROM ods.ods_xhs_settlement_income_raw WHERE NULLIF(BTRIM("买手佣金"),'') IS NOT NULL
        UNION ALL SELECT 'settlement',NULL,NULL,'花呗分期手续费' FROM ods.ods_xhs_settlement_income_raw WHERE NULLIF(BTRIM("花呗分期手续费"),'') IS NOT NULL
    """,
    "tmall": """
        WITH aggregate_clean AS (
            SELECT
                NULLIF(BTRIM("入帐类型"),'') AS source_business_type,
                COALESCE(BTRIM("备注"),'') AS source_description
            FROM ods.ods_tmall_aggregate_fund_raw
        ), aggregate_standardized AS (
            SELECT
                source_business_type,
                CASE
                    WHEN source_business_type = '交易收款' THEN '订单收款'
                    WHEN source_business_type = '交易退款(售后)' THEN '销售退款'
                    WHEN source_business_type = '提现' THEN '账户提现'
                    WHEN source_description LIKE '%品牌新享-首单拉新计划%' THEN '品牌新享-首单拉新计划'
                    WHEN source_description LIKE '%限时红包代商家垫付扣回%' THEN '限时红包代商家垫付扣回'
                    WHEN source_description LIKE '%淘金币软件服务费%' THEN '淘金币软件服务费'
                    WHEN source_description LIKE '%基础软件服务费%' THEN '基础软件服务费'
                    WHEN source_description LIKE '%光合平台软件服务费%' THEN '光合平台软件服务费'
                    WHEN source_description LIKE '%淘宝内容推广服务费%' THEN '淘宝内容推广服务费'
                    ELSE BTRIM(REGEXP_REPLACE(source_description, '[0-9]{10,}', '<ID>', 'g'))
                END AS standardized_note
            FROM aggregate_clean
        ), alipay_clean AS (
            SELECT
                NULLIF(BTRIM(REPLACE("业务类型",E'\\t','')),'') AS source_business_type,
                COALESCE(BTRIM(REPLACE("备注",E'\\t','')),'') AS source_description
            FROM ods.ods_tmall_alipay_fund_raw
        ), alipay_standardized AS (
            SELECT
                source_business_type,
                CASE
                    WHEN source_business_type = '交易付款' THEN '订单收款'
                    WHEN source_business_type = '交易退款' THEN '销售退款'
                    WHEN source_business_type = '提现' THEN '账户提现'
                    WHEN source_description LIKE '%品牌新享-首单拉新计划%' THEN '品牌新享-首单拉新计划'
                    WHEN source_description LIKE '%限时红包代商家垫付扣回%' THEN '限时红包代商家垫付扣回'
                    WHEN source_description LIKE '%淘金币软件服务费%' THEN '淘金币软件服务费'
                    WHEN source_description LIKE '%基础软件服务费%' THEN '基础软件服务费'
                    WHEN source_description LIKE '%光合平台软件服务费%' THEN '光合平台软件服务费'
                    WHEN source_description LIKE '%淘宝内容推广服务费%' THEN '淘宝内容推广服务费'
                    WHEN source_description LIKE '%淘宝客佣金代扣款%' THEN '淘宝客佣金'
                    WHEN source_description LIKE '%先用后付技术服务费%' THEN '先用后付技术服务费'
                    WHEN source_description LIKE '%天猫佣金（类目系统）%' THEN '天猫佣金（类目系统）'
                    WHEN source_description LIKE '%代扣返点积分%'
                      OR source_description LIKE '%代扣交易退回积分%' THEN '代扣返点积分'
                    WHEN source_description LIKE '%消费者体验提升计划服务费%' THEN '消费者体验提升计划服务费'
                    WHEN source_description LIKE '%商家集运物流服务费%' THEN '商家集运物流服务费'
                    WHEN source_description LIKE '%商家集运中转操作费%' THEN '商家集运中转操作费'
                    WHEN source_description LIKE '%淘宝联盟佣金代扣%'
                      OR source_description LIKE '%淘宝联盟推广佣金返还%' THEN '淘宝联盟佣金'
                    WHEN source_description LIKE '%天猫保证金履约险追偿%' THEN '天猫保证金履约险追偿'
                    WHEN source_description LIKE '%支付宝转账小额打款%' THEN '小额打款'
                    ELSE BTRIM(REGEXP_REPLACE(source_description, '[0-9]{10,}', '<ID>', 'g'))
                END AS standardized_note
            FROM alipay_clean
        )
        SELECT 'fund',source_business_type,NULL::text,
               source_business_type || ' + ' || standardized_note
        FROM aggregate_standardized
        WHERE source_business_type IS NOT NULL
        UNION ALL
        SELECT 'fund',source_business_type,NULL::text,
               source_business_type || ' + ' || standardized_note
        FROM alipay_standardized
        WHERE source_business_type IS NOT NULL
    """,
}

FEE_PLATFORM_ETLS = {
    "douyin": {"douyin_platform_expense"},
    "ks": {"ks_platform_expense", "ks_main_business_income"},
    "jd": {"jd_main_business_finance"},
    "tmall": {"tmall_main_business_finance"},
    "pdd": {"pdd_main_business_finance"},
    "wechat_channels": {"wechat_channels_main_business_finance"},
    "xhs": {"xhs_main_business_finance"},
}

OPERATION_TYPE_LABELS = {
    "run_create": "创建采集会话",
    "file_upload": "文件上传",
    "parameter_correction": "参数修正",
    "run_complete": "提交采集会话",
    "run_failed": "上传会话失败",
    "run_delete": "删除未完成采集会话",
    "file_retry": "重试文件任务",
    "run_timeout": "上传会话超时",
    "run_resume": "继续确认导入",
    "run_draft_save": "保存导入草稿",
    "etl_retry": "重试ETL任务",
    "etl_interrupted": "ETL中断收尾",
    "etl_schedule_update": "更新夜间全量刷新配置",
    "finance_config_save": "保存经营预算配置",
    "finance_config_delete": "删除经营预算配置",
    "finance_expense_type_save": "维护营销费用类型",
    "finance_expense_type_delete": "删除营销费用类型",
    "fee_category_create": "新增平台费用一级分类",
    "fee_category_update": "修改平台费用一级分类",
    "fee_category_delete": "删除平台费用一级分类",
    "fee_mapping_assign": "批量映射费用场景",
    "fee_mapping_rejected": "收支配置校验未通过",
    "fee_mapping_status": "启停费用映射",
    "fee_mapping_delete": "清除收支分类，保留经营归属",
}


class ConflictError(ValueError):
    http_status = 409


class NotFoundError(ValueError):
    http_status = 404


def row_dict(row) -> dict:
    return dict(row) if row else {}


class FileIngestService:
    def __init__(self, args, storage_root: Path | None = None):
        self.connect_kwargs = {
            "host": args.host,
            "port": getattr(args, "pg_port", getattr(args, "port", 5432)),
            "dbname": args.dbname,
            "user": args.user,
            "password": args.password,
        }
        self.storage_root = Path(
            storage_root or os.getenv("INGEST_FILE_ROOT") or PROJECT_ROOT / ".uploads" / "file_ingest"
        )
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def connect(self):
        return psycopg2.connect(**self.connect_kwargs)

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> list[str]:
        applied: list[str] = []
        with self.transaction() as cursor:
            for path in MIGRATION_FILES:
                cursor.execute(path.read_text(encoding="utf-8"))
                applied.append(str(path.relative_to(PROJECT_ROOT)))
            from etl.platform_finance.category_catalog import ensure_catalog, CATALOG_SQL
            ensure_catalog(cursor)
            applied.append('sql/' + CATALOG_SQL)
            from etl.platform_finance.operating_policy import initialize_policy, MIGRATION
            initialize_policy(cursor)
            applied.append('sql/' + MIGRATION)
        return applied

    def health(self) -> dict:
        with self.transaction() as cursor:
            cursor.execute(
                """
                SELECT to_regclass('ops.ingest_run') IS NOT NULL AS ingest_ready,
                       to_regclass('ops.etl_run') IS NOT NULL AS etl_ready,
                       to_regclass('dim.dim_platform_fee_mapping') IS NOT NULL AS fee_mapping_ready,
                       to_regclass('ops.worker_heartbeat') IS NOT NULL AS worker_heartbeat_ready,
                       (to_regclass('common.ingest_source_day_selection') IS NOT NULL AND EXISTS (
                           SELECT 1 FROM information_schema.columns WHERE table_schema='ops'
                             AND table_name='ingest_run' AND column_name='coverage_result'
                       )) AS ingest_coverage_ready
                """
            )
            result = row_dict(cursor.fetchone())
            if result.get("ingest_ready"):
                cursor.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE status IN ('ready','processing')) AS active_ingest_runs,
                           (SELECT COUNT(*) FROM ops.etl_run WHERE status IN ('queued','running')) AS active_etl_runs
                    FROM ops.ingest_run
                    """
                )
                result.update(row_dict(cursor.fetchone()))
                if result.get("worker_heartbeat_ready"):
                    cursor.execute(
                        """
                        SELECT COUNT(*) AS active_worker_count,
                               MAX(last_seen_at) AS worker_last_seen_at
                        FROM ops.worker_heartbeat
                        WHERE (status IN ('starting','idle') AND last_seen_at >= NOW() - INTERVAL '15 seconds')
                           OR (status='busy' AND last_seen_at >= NOW() - INTERVAL '3 hours')
                        """
                    )
                    result.update(row_dict(cursor.fetchone()))
                else:
                    result.update({"active_worker_count": 0, "worker_last_seen_at": None})
            result["active_report_count"] = len(ACTIVE_REPORTS)
            result["operating_treatment_version"] = 2
            result['scene_normalization_version']=1
            result['ingest_coverage_version']=1 if result.get('ingest_coverage_ready') else 0
            result['ingest_review_version']=3 if result.get('ingest_coverage_ready') else 0
            return result

    def list_reports(self) -> dict:
        from .coverage import SUPPORTED
        items=[]
        for spec in ACTIVE_REPORTS:
            item=spec.public_dict()
            item['coverage_modes']=['fill_gaps','replace_range','refresh_only'] if spec.report_type in SUPPORTED else ['fill_gaps','refresh_only']
            item['coverage_note']='支持逐日比较与人工范围替换' if spec.report_type in SUPPORTED else '沿用本报表的来源校验，暂不支持人工范围替换'
            items.append(item)
        return {"items":items,"total":len(items)}

    def list_shops(self, platform_code: str | None = None) -> list[dict]:
        with self.transaction() as cursor:
            params: list[Any] = []
            condition = ""
            if platform_code:
                condition = "AND platform_code=%s"
                params.append(platform_code)
            cursor.execute(
                f"""
                SELECT platform_code,platform_name,company_code,company_name,shop_code,shop_name,
                       shop_type,account_id,shop_identity_key
                FROM dim.dim_platform_shop_company
                WHERE is_active AND CURRENT_DATE >= valid_from
                  AND (valid_to IS NULL OR CURRENT_DATE <= valid_to)
                  {condition}
                ORDER BY platform_name,company_name,shop_name
                """,
                params,
            )
            return [dict(row) for row in cursor.fetchall()]

    def guess(self, filename: str) -> dict:
        if not filename:
            raise ValueError("filename不能为空")
        return guess_filename(filename, self.list_shops())

    def _resolve_shop(self, cursor, spec, metadata: dict, filename: str) -> dict:
        shop_code = normalize_name(metadata.get("shop_code", ""))
        if not shop_code:
            from .errors import ShopCodeRequired
            raise ShopCodeRequired()
        cursor.execute(
            """
            SELECT platform_code,platform_name,company_code,company_name,shop_code,shop_name,shop_identity_key
            FROM dim.dim_platform_shop_company
            WHERE platform_code=%s AND shop_code=%s AND is_active
              AND CURRENT_DATE >= valid_from AND (valid_to IS NULL OR CURRENT_DATE <= valid_to)
            """,
            (spec.platform_code, shop_code),
        )
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise ValueError(f"店铺映射必须唯一：platform={spec.platform_code}, shop_code={shop_code}, matched={len(rows)}")
        resolved = dict(rows[0])
        comparisons = {
            "platform_name": resolved["platform_name"],
            "company_name": resolved["company_name"],
            "shop_name": resolved["shop_name"],
        }
        for key, expected in comparisons.items():
            requested = normalize_name(metadata.get(key, ""))
            if requested and requested != normalize_name(expected):
                raise ValueError(f"{key}与DIM不一致：requested={requested}, dim={expected}")
        return resolved

    @staticmethod
    def _list_shops_cursor(cursor) -> list[dict]:
        cursor.execute(
            """
            SELECT platform_code,platform_name,company_code,company_name,shop_code,shop_name,shop_identity_key
            FROM dim.dim_platform_shop_company
            WHERE is_active AND CURRENT_DATE >= valid_from
              AND (valid_to IS NULL OR CURRENT_DATE <= valid_to)
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def create_run(self, payload: dict, operator: str, source: str) -> dict:
        source = normalize_name(source or payload.get("source", "manual")).lower()
        if source not in {"api", "robot", "manual"}:
            raise ValueError("source必须为api、robot或manual")
        idempotency_key = normalize_name(payload.get("idempotency_key", ""))
        if not idempotency_key:
            raise ValueError("idempotency_key不能为空")
        expected = int(payload.get("expected_file_count", 0))
        if expected <= 0:
            raise ValueError("expected_file_count必须大于0")
        from .coverage import MODES
        import_mode = str(payload.get('import_mode') or 'fill_gaps')
        if import_mode not in MODES or (source != 'manual' and import_mode == 'replace_range'):
            raise ValueError('采信模式无效；以本次文件为准仅适用于人工上传')
        run_id = uuid.uuid4()
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT * FROM ops.ingest_run WHERE source=%s AND idempotency_key=%s",
                (source, idempotency_key),
            )
            existing = cursor.fetchone()
            if existing:
                if existing['expected_file_count'] != expected or existing.get('import_mode','fill_gaps') != import_mode:
                    raise ConflictError('同一幂等键不能改变文件数量或采信模式')
                return dict(existing)
            cursor.execute(
                """
                INSERT INTO ops.ingest_run(run_id,source,idempotency_key,expected_file_count,auto_refresh,status,operator,import_mode)
                VALUES(%s,%s,%s,%s,%s,'draft',%s,%s) RETURNING *
                """,
                (str(run_id), source, idempotency_key, expected, bool(payload.get("auto_refresh", True)), operator, import_mode),
            )
            result = dict(cursor.fetchone())
            self._write_log(cursor, "run_create", "ingest_run", str(run_id), operator, None, "创建采集会话", payload)
        return result

    def run_source(self, run_id: str) -> str:
        with self.transaction() as cursor:
            cursor.execute("SELECT source FROM ops.ingest_run WHERE run_id=%s", (run_id,))
            row = cursor.fetchone()
            if not row:
                raise NotFoundError("采集会话不存在")
            return row["source"]

    def save_upload(
        self,
        run_id: str,
        *,
        filename: str,
        content: bytes,
        metadata: dict,
        operator: str,
        ip_address: str | None,
    ) -> dict:
        if not content or len(content) > MAX_UPLOAD_BYTES:
            raise ValueError(f"文件为空或超过{MAX_UPLOAD_BYTES // 1024 // 1024}MB")
        safe_filename = Path(filename).name
        if len(safe_filename) > 255:
            raise ValueError("上传文件名不能超过255个字符")
        client_file_id = normalize_name(metadata.get("client_file_id", ""))
        if not client_file_id:
            raise ValueError("client_file_id不能为空")
        from .coverage import normalize_claim
        coverage = normalize_claim(metadata.get('coverage'))
        digest = hashlib.sha256(content).hexdigest()
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.ingest_run WHERE run_id=%s FOR UPDATE", (run_id,))
            run = cursor.fetchone()
            if not run:
                raise NotFoundError("采集会话不存在")
            cursor.execute(
                "SELECT * FROM ops.ingest_file_task WHERE run_id=%s AND client_file_id=%s",
                (run_id, client_file_id),
            )
            existing_task = cursor.fetchone()
            if existing_task:
                if existing_task['file_hash'] != digest or normalize_claim(existing_task.get('coverage',{})) != coverage or any(
                    metadata.get(key) and str(metadata[key]) != str(existing_task[field]) for key,field in (
                        ('report_type','report_type'),('shop_code','resolved_shop_code'))):
                    raise ConflictError('同一client_file_id不能改变文件内容、店铺、报表或覆盖声明')
                return dict(existing_task)
            if run["status"] != "draft":
                raise ConflictError("只有draft会话可以上传文件")
            report_type = normalize_name(metadata.get("report_type", "")) or None
            platform_name = normalize_name(metadata.get("platform_name", "")) or None
            report_name = normalize_name(metadata.get("report_name", "")) or None
            if report_type or (platform_name and report_name):
                spec = find_report(report_type=report_type, platform_name=platform_name, report_name=report_name)
            else:
                guessed = guess_filename(safe_filename, self._list_shops_cursor(cursor))
                if not guessed.get("matched"):
                    raise ValueError(guessed.get("message") or "缺少报表参数且文件名无法识别")
                spec = REPORT_BY_TYPE[guessed["report_type"]]
            suffix = Path(safe_filename).suffix.lower()
            if suffix not in spec.extensions:
                raise ValueError(f"{spec.report_name}不支持扩展名{suffix}")
            resolved = self._resolve_shop(cursor, spec, metadata, safe_filename)
            target_tables = tuple(
                table.split(".", 1)[-1]
                for table in (spec.target_tables or (spec.target_table,))
            )
            cursor.execute(
                """
                SELECT batch_id,target_table FROM ods.ods_file_ingest_log
                WHERE file_hash=%s AND platform_code=%s AND shop_identity_key=%s
                  AND target_table = ANY(%s) AND ingest_status='success'
                ORDER BY batch_id
                """,
                (digest, spec.platform_code, resolved["shop_identity_key"], list(target_tables)),
            )
            duplicate_rows = cursor.fetchall()
            duplicate_by_table = {row["target_table"]: row["batch_id"] for row in duplicate_rows}
            duplicate = duplicate_by_table if set(duplicate_by_table) == set(target_tables) else None
            if not duplicate:
                cursor.execute(
                    """
                    SELECT batch_id FROM ops.ingest_file_task
                    WHERE run_id=%s AND file_hash=%s AND resolved_platform_code=%s
                      AND shop_identity_key=%s AND report_type=%s
                    ORDER BY created_at LIMIT 1
                    """,
                    (run_id, digest, spec.platform_code, resolved["shop_identity_key"], spec.report_type),
                )
                prior = cursor.fetchone()
                if prior:
                    raise ConflictError('同一会话已包含相同文件，请移除重复项并调整预期文件数')
            file_task_id = uuid.uuid4()
            relative = Path(datetime.now().strftime("%Y/%m")) / str(run_id) / f"{digest[:16]}_{safe_filename}"
            target = self.storage_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(content)
            status = "duplicate" if duplicate else "uploaded"
            batch_id = duplicate_by_table.get(target_tables[0]) if duplicate else None
            cursor.execute(
                """
                INSERT INTO ops.ingest_file_task(
                    file_task_id,run_id,client_file_id,source_file_name,report_type,
                    requested_platform_name,requested_company_name,requested_shop_code,requested_shop_name,
                    resolved_platform_code,resolved_platform_name,resolved_company_code,resolved_company_name,
                    resolved_shop_code,resolved_shop_name,shop_identity_key,file_hash,file_size_bytes,
                    storage_path,batch_id,status,finished_at
                ) VALUES(
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    CASE WHEN %s='duplicate' THEN NOW() ELSE NULL END
                ) RETURNING *
                """,
                (
                    str(file_task_id), run_id, client_file_id, safe_filename, spec.report_type,
                    metadata.get("platform_name"), metadata.get("company_name"), metadata.get("shop_code"), metadata.get("shop_name"),
                    resolved["platform_code"], resolved["platform_name"], resolved["company_code"], resolved["company_name"],
                    resolved["shop_code"], resolved["shop_name"], resolved["shop_identity_key"], digest, len(content),
                    str(relative), batch_id, status, status,
                ),
            )
            result = dict(cursor.fetchone())
            cursor.execute('UPDATE ops.ingest_file_task SET coverage=%s WHERE file_task_id=%s',
                           (Json(coverage), str(file_task_id)))
            result['coverage'] = coverage
            if duplicate:
                for target_table in target_tables:
                    cursor.execute(
                        """
                        INSERT INTO ops.ingest_file_task_batch(file_task_id,batch_id,target_table)
                        VALUES(%s,%s,%s)
                        ON CONFLICT (file_task_id,batch_id) DO NOTHING
                        """,
                        (str(file_task_id), duplicate_by_table[target_table], target_table),
                    )
            self._write_log(cursor, "file_upload", "ingest_file_task", str(file_task_id), operator, ip_address, f"上传{safe_filename}", {"report_type": spec.report_type, "status": status})
            if str(metadata.get("manual_correction", "")).lower() == "true":
                self._write_log(cursor, "parameter_correction", "ingest_file_task", str(file_task_id), operator, ip_address, "人工修正文件识别参数", {"report_type": spec.report_type, "shop_code": resolved["shop_code"]})
            cursor.execute("UPDATE ops.ingest_run SET updated_at=NOW() WHERE run_id=%s", (run_id,))
        return result

    def reuse_run_files(self, run_id: str, payload: dict, operator: str, ip_address: str | None) -> dict:
        """Create a reviewable draft referencing successful ODS and stored bytes."""
        request_key = str(payload.get('idempotency_key') or '')
        if not request_key or len(request_key)>80:
            raise ValueError('复用请求必须提供不超过80字符的idempotency_key')
        key='reuse:'+str(run_id)+':'+request_key
        if len(key)>128:
            raise ValueError('复用幂等键过长')
        with self.transaction() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",(key,))
            cursor.execute("SELECT run_id FROM ops.ingest_run WHERE source='manual' AND idempotency_key=%s",(key,))
            existing=cursor.fetchone()
            if existing:
                return self._run_detail_cursor(cursor,str(existing['run_id']))
            cursor.execute('SELECT * FROM ops.ingest_run WHERE run_id=%s FOR SHARE',(run_id,))
            original=cursor.fetchone()
            if not original:
                raise NotFoundError('原导入会话不存在')
            cursor.execute('SELECT * FROM ops.ingest_file_task WHERE run_id=%s ORDER BY created_at',(run_id,))
            tasks=[dict(row) for row in cursor.fetchall()]
            if not tasks or len(tasks)!=original['expected_file_count'] or any(t['status'] not in {'success','duplicate'} or not t['batch_id'] for t in tasks):
                raise ConflictError('只有全部文件已成功入库或绑定重复批次的会话可以复用')
            new_id=str(uuid.uuid4())
            cursor.execute("""INSERT INTO ops.ingest_run(run_id,source,idempotency_key,expected_file_count,auto_refresh,status,operator)
                VALUES(%s,'manual',%s,%s,TRUE,'draft',%s)""",(new_id,key,len(tasks),operator))
            columns=('source_file_name','report_type','requested_platform_name','requested_company_name','requested_shop_code',
                'requested_shop_name','resolved_platform_code','resolved_platform_name','resolved_company_code',
                'resolved_company_name','resolved_shop_code','resolved_shop_name','shop_identity_key','file_hash',
                'file_size_bytes','storage_path','batch_id','coverage')
            for task in tasks:
                task_id=str(uuid.uuid4())
                cursor.execute(sql.SQL("""INSERT INTO ops.ingest_file_task(file_task_id,run_id,client_file_id,{},status,finished_at)
                    SELECT %s,%s,%s,{},'duplicate',NOW() FROM ops.ingest_file_task WHERE file_task_id=%s""").format(
                    sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(map(sql.Identifier,columns))),
                    (task_id,new_id,str(task['file_task_id']),str(task['file_task_id'])))
                cursor.execute('''INSERT INTO ops.ingest_file_task_batch(file_task_id,batch_id,target_table)
                    SELECT %s,batch_id,target_table FROM ops.ingest_file_task_batch WHERE file_task_id=%s''',
                    (task_id,str(task['file_task_id'])))
            self._write_log(cursor,'run_reuse','ingest_run',new_id,operator,ip_address,'复用已导入文件创建待核对草稿',{'original_run_id':str(run_id)})
            return self._run_detail_cursor(cursor,new_id)

    @staticmethod
    def _run_actions(run: dict, counts: dict[str, int]) -> dict:
        expected = int(run['expected_file_count'])
        total = sum(counts.values())
        complete_files = total == expected and expected > 0
        reviewable = complete_files and not any(count for status,count in counts.items()
            if status not in {'uploaded','success','duplicate'})
        can_resume = (run['source']=='manual' and run['status']=='failed'
            and not run.get('has_related_etl',False)
            and run.get('coverage_result') is None and complete_files
            and counts.get('uploaded',0)>0
            and counts.get('uploaded',0)+counts.get('duplicate',0)==expected)
        return {'can_complete':run['status']=='draft' and reviewable,
                'can_resume':can_resume,
                'can_reuse':complete_files and counts.get('success',0)+counts.get('duplicate',0)==expected}

    def resume_run(self, run_id: str, operator: str, ip_address: str | None) -> dict:
        """Recover an interrupted manual upload; never queue loaders or ETL."""
        with self.transaction() as cursor:
            cursor.execute('SELECT * FROM ops.ingest_run WHERE run_id=%s FOR UPDATE',(run_id,))
            run=cursor.fetchone()
            if not run:
                raise NotFoundError('导入记录不存在')
            if run['source']!='manual':
                raise ConflictError('只有人工上传草稿可以从此入口继续')
            cursor.execute('SELECT * FROM ops.ingest_file_task WHERE run_id=%s ORDER BY created_at',(run_id,))
            tasks=[dict(row) for row in cursor.fetchall()]
            if run['status']=='draft':
                return self._run_detail_cursor(cursor,run_id)
            counts={status:sum(t['status']==status for t in tasks) for status in {t['status'] for t in tasks}}
            if not self._run_actions(run,counts)['can_resume']:
                raise ConflictError('当前记录不能恢复为待确认；已入库文件请复用，失败文件请先重试')
            cursor.execute('SELECT 1 FROM ops.etl_run WHERE ingest_run_id=%s LIMIT 1',(run_id,))
            if cursor.fetchone():
                raise ConflictError('此记录已有关联刷新任务，请在详情中查看处理阶段')
            for task in tasks:
                path=(self.storage_root/task['storage_path']).resolve()
                if not path.is_relative_to(self.storage_root.resolve()) or not path.is_file():
                    raise ConflictError('已上传文件缺失，请从原文件重新上传')
                if hashlib.sha256(path.read_bytes()).hexdigest()!=task['file_hash']:
                    raise ConflictError('已上传文件摘要不一致，不能继续原草稿')
            cursor.execute('''UPDATE ops.ingest_run SET status='draft',error_message=NULL,completed_at=NULL,
                coverage_preflight=NULL,updated_at=NOW() WHERE run_id=%s''',(run_id,))
            self._write_log(cursor,'run_resume','ingest_run',run_id,operator,ip_address,
                '恢复未入库文件，等待重新核对',{'previous_error':run.get('error_message')})
            return self._run_detail_cursor(cursor,run_id)

    @staticmethod
    def _save_coverage_input(cursor, run, payload, *, draft=False):
        from .coverage import MODES, normalize_claim, normalize_draft_claim
        mode=str(payload.get('import_mode') or run.get('import_mode','fill_gaps'))
        if mode not in MODES or (mode=='replace_range' and run['source']!='manual'):
            raise ValueError('处理方式无效；替换已有来源需要人工确认')
        normalize=normalize_draft_claim if draft else normalize_claim
        if 'coverage' in payload:
            cursor.execute("""UPDATE ops.ingest_file_task SET coverage=%s::jsonb ||
                CASE WHEN coverage ? 'bill_date' THEN jsonb_build_object('bill_date',coverage->'bill_date') ELSE '{}'::jsonb END
                WHERE run_id=%s""",(Json(normalize(payload['coverage'])),str(run['run_id'])))
        for item in payload.get('items',[]):
            cursor.execute('UPDATE ops.ingest_file_task SET coverage=%s WHERE run_id=%s AND file_task_id=%s',
                (Json(normalize(item['coverage'])),str(run['run_id']),item['file_task_id']))
            if cursor.rowcount!=1:
                raise ValueError('核对文件不属于本次导入记录')
        cursor.execute('UPDATE ops.ingest_run SET import_mode=%s,coverage_preflight=NULL,updated_at=NOW() WHERE run_id=%s',
            (mode,str(run['run_id'])))
        return {**run,'import_mode':mode}

    def save_run_draft(self, run_id: str, payload: dict, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            cursor.execute('SELECT * FROM ops.ingest_run WHERE run_id=%s FOR UPDATE',(run_id,))
            run=cursor.fetchone()
            if not run:
                raise NotFoundError('导入记录不存在')
            if run['source']!='manual' or run['status']!='draft':
                raise ConflictError('只能保存人工待确认草稿，请先继续原导入记录')
            self._save_coverage_input(cursor,run,payload,draft=True)
            self._write_log(cursor,'run_draft_save','ingest_run',run_id,operator,ip_address,
                '保存待确认草稿；未提交入库或刷新',None)
            return self._run_detail_cursor(cursor,run_id)

    def coverage_preflight(self, run_id: str, payload: dict, operator: str) -> dict:
        from .coverage import preview, public_preview
        with self.transaction() as cursor:
            cursor.execute('SELECT * FROM ops.ingest_run WHERE run_id=%s FOR UPDATE', (run_id,))
            run = cursor.fetchone()
            if not run:
                raise NotFoundError('采集会话不存在')
            if run['status'] != 'draft':
                raise ConflictError('此记录当前不可核对；未入库的失败记录请先继续确认，已入库文件请复用')
            run=self._save_coverage_input(cursor,run,payload)
            cursor.execute('SELECT * FROM ops.ingest_file_task WHERE run_id=%s ORDER BY created_at', (run_id,))
            tasks = [dict(r) for r in cursor.fetchall()]
            if len(tasks) != run['expected_file_count']:
                raise ConflictError('全部文件上传完成后才能预检')
            report = preview(cursor, run, tasks, self.storage_root)
            cursor.execute('UPDATE ops.ingest_run SET coverage_preflight=%s,updated_at=NOW() WHERE run_id=%s', (Json(report),run_id))
            return public_preview(report)

    def complete_run(self, run_id: str, operator: str, ip_address: str | None, *, payload: dict | None = None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.ingest_run WHERE run_id=%s FOR UPDATE", (run_id,))
            run = cursor.fetchone()
            if not run:
                raise NotFoundError("采集会话不存在")
            if run["status"] in {"ready", "processing", "success", "no_change"}:
                return self._run_detail_cursor(cursor, run_id)
            # Preserve the existing automation completion retry contract;
            # manual users resume a draft explicitly before reviewing it.
            automation_retry=run['status']=='failed' and run['source'] in {'api','robot'}
            if run['status']!='draft' and not automation_retry:
                raise ConflictError('请先恢复待确认草稿并重新核对，再提交入库')
            cursor.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER(WHERE status='duplicate') AS duplicate_count,
                       COUNT(*) FILTER(WHERE status='failed') AS failed_count
                FROM ops.ingest_file_task WHERE run_id=%s
                """,
                (run_id,),
            )
            counts = cursor.fetchone()
            if counts["total"] != run["expected_file_count"]:
                raise ConflictError(f"预期{run['expected_file_count']}个文件，当前{counts['total']}个")
            if counts["failed_count"]:
                raise ConflictError("会话存在失败文件，请修正并重试")
            from .coverage import preview, CoverageConflict
            cursor.execute('SELECT * FROM ops.ingest_file_task WHERE run_id=%s ORDER BY created_at', (run_id,))
            tasks = [dict(r) for r in cursor.fetchall()]
            report = preview(cursor, run, tasks, self.storage_root)
            if report['blocked']:
                raise CoverageConflict('来源预检发现内容差异；请选择仅补缺或核对后以本次文件为准。已保留上传文件，尚未写入ODS')
            if run.get('import_mode') == 'replace_range' and (payload or {}).get('preflight_token') != report['token']:
                raise CoverageConflict('范围替换必须先查看预检并提交对应preflight_token；来源变化后需重新预检')
            cursor.execute('UPDATE ops.ingest_run SET coverage_preflight=%s WHERE run_id=%s', (Json(report),run_id))
            new_count = counts["total"] - counts["duplicate_count"]
            status = "ready" if new_count or report['items'] or run.get('import_mode')=='refresh_only' else "no_change"
            cursor.execute(
                """
                UPDATE ops.ingest_run SET status=%s,duplicate_file_count=%s,
                    completed_at=CASE WHEN %s='no_change' THEN NOW() ELSE NULL END,updated_at=NOW()
                WHERE run_id=%s
                """,
                (status, counts["duplicate_count"], status, run_id),
            )
            self._write_log(cursor, "run_complete", "ingest_run", str(run_id), operator, ip_address, "提交采集会话", {"status": status})
            return self._run_detail_cursor(cursor, run_id)

    def fail_run(self, run_id: str, operator: str, ip_address: str | None, message: str) -> dict:
        """把上传阶段未完成的会话标记为失败，但保留已上传文件以便后续完成或删除。"""
        reason = str(message or "文件上传未完成")[:500]
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.ingest_run WHERE run_id=%s FOR UPDATE", (run_id,))
            run = cursor.fetchone()
            if not run:
                raise NotFoundError("采集会话不存在")
            if run["status"] in {"ready", "processing", "success", "no_change"}:
                raise ConflictError("当前会话已经进入处理流程，不能标记为上传失败")
            cursor.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status='success') AS success_count,
                       COUNT(*) FILTER (WHERE status='duplicate') AS duplicate_count,
                       COUNT(*) FILTER (WHERE status='failed') AS failed_count
                FROM ops.ingest_file_task
                WHERE run_id=%s
                """,
                (run_id,),
            )
            counts = cursor.fetchone()
            missing_count = max(int(run["expected_file_count"]) - int(counts["total"]), 0)
            failed_count = int(counts["failed_count"]) + missing_count
            cursor.execute(
                """
                UPDATE ops.ingest_run
                SET status='failed', success_file_count=%s, duplicate_file_count=%s,
                    failed_file_count=%s, error_message=%s, completed_at=NOW(), updated_at=NOW()
                WHERE run_id=%s
                """,
                (
                    counts["success_count"], counts["duplicate_count"], failed_count,
                    reason, run_id,
                ),
            )
            self._write_log(cursor, "run_failed", "ingest_run", str(run_id), operator, ip_address, "上传会话失败", {"message": reason})
            return self._run_detail_cursor(cursor, run_id)

    def delete_run(self, run_id: str, operator: str, ip_address: str | None) -> dict:
        """删除未进入ODS的草稿/失败会话及其上传文件，保护已成功导入的会话。"""
        stored_paths: list[Path] = []
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.ingest_run WHERE run_id=%s FOR UPDATE", (run_id,))
            run = cursor.fetchone()
            if not run:
                raise NotFoundError("采集会话不存在")
            if run["status"] in {"ready", "processing", "success", "no_change"}:
                raise ConflictError("已进入处理流程的会话不能删除")
            cursor.execute(
                """
                SELECT storage_path FROM ops.ingest_file_task
                WHERE run_id=%s AND status='success'
                """,
                (run_id,),
            )
            if cursor.fetchone():
                raise ConflictError("会话已有成功导入文件，不能删除")
            cursor.execute(
                "SELECT storage_path FROM ops.ingest_file_task WHERE run_id=%s",
                (run_id,),
            )
            stored_paths = [self.storage_root / row["storage_path"] for row in cursor.fetchall()]
            self._write_log(cursor, "run_delete", "ingest_run", str(run_id), operator, ip_address, "删除未完成采集会话", {"status": run["status"]})
            cursor.execute("DELETE FROM ops.ingest_run WHERE run_id=%s", (run_id,))
        for stored_path in stored_paths:
            # Reused drafts reference the original successful run's file. Only
            # remove an upload physically owned by the deleted draft.
            stored_path = stored_path.resolve()
            if not stored_path.is_relative_to(self.storage_root.resolve()) or str(run_id) not in stored_path.parts:
                continue
            try:
                stored_path.unlink(missing_ok=True)
            except OSError:
                pass
        return {"run_id": str(run_id), "deleted": True}

    def retry_file(self, file_task_id: str, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.ingest_file_task WHERE file_task_id=%s FOR UPDATE", (file_task_id,))
            task = cursor.fetchone()
            if not task:
                raise NotFoundError("文件任务不存在")
            if task["status"] != "failed":
                raise ConflictError("只有failed文件任务可以重试")
            cursor.execute("UPDATE ops.ingest_file_task SET status='uploaded',error_message=NULL,updated_at=NOW() WHERE file_task_id=%s RETURNING *", (file_task_id,))
            result = dict(cursor.fetchone())
            cursor.execute(
                "UPDATE ops.ingest_run SET status='draft',error_message=NULL,completed_at=NULL,updated_at=NOW() WHERE run_id=%s",
                (task["run_id"],),
            )
            self._write_log(cursor, "file_retry", "ingest_file_task", file_task_id, operator, ip_address, "重试文件任务", None)
        return result

    def _mark_stale_drafts(self, cursor, operator: str = "系统") -> None:
        cursor.execute(
            """
            WITH stale_runs AS (
                SELECT run_id,expected_file_count FROM ops.ingest_run
                WHERE status='draft' AND source<>'manual'
                  AND updated_at < NOW() - (%s * INTERVAL '1 minute')
                FOR UPDATE SKIP LOCKED
            )
            SELECT r.run_id, r.expected_file_count,
                   COUNT(f.file_task_id) AS task_count,
                   COUNT(f.file_task_id) FILTER (WHERE f.status='success') AS success_count,
                   COUNT(f.file_task_id) FILTER (WHERE f.status='duplicate') AS duplicate_count,
                   COUNT(f.file_task_id) FILTER (WHERE f.status='failed') AS failed_count
            FROM stale_runs r
            LEFT JOIN ops.ingest_file_task f ON f.run_id=r.run_id
            GROUP BY r.run_id, r.expected_file_count
            """,
            (STALE_DRAFT_MINUTES,),
        )
        stale = cursor.fetchall()
        for row in stale:
            missing_count = max(int(row["expected_file_count"]) - int(row["task_count"]), 0)
            failed_count = int(row["failed_count"]) + missing_count
            cursor.execute(
                """
                UPDATE ops.ingest_run
                SET status='failed', success_file_count=%s, duplicate_file_count=%s,
                    failed_file_count=%s, error_message='上传会话超时，未完成文件提交',
                    completed_at=NOW(), updated_at=NOW()
                WHERE run_id=%s AND status='draft'
                """,
                (row["success_count"], row["duplicate_count"], failed_count, row["run_id"]),
            )
            if cursor.rowcount:
                self._write_log(cursor, "run_timeout", "ingest_run", str(row["run_id"]), operator, None, "上传会话超时并标记失败", {"timeout_minutes": STALE_DRAFT_MINUTES})

    def list_runs(self, page: int = 1, page_size: int = 10, operator: str = "系统", query: dict[str, Any] | None = None) -> dict:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 200))
        query = query or {}
        filters = ["TRUE"]
        params: list[Any] = []
        operators = [value.strip() for value in str(query.get("operator") or "").replace("，", ",").split(",") if value.strip()]
        if operators:
            filters.append("r.operator=ANY(%s)")
            params.append(operators)
        status = str(query.get("status") or "").strip()
        if status:
            filters.append("r.status=%s")
            params.append(status)
        date_field = str(query.get("date_field") or "created_at").strip()
        date_column = {"created_at": "r.created_at", "completed_at": "r.completed_at"}.get(date_field, "r.created_at")
        for raw_value, label, operator in (
            (query.get("date_from"), "开始日期", ">="),
            (query.get("date_to"), "结束日期", "<="),
        ):
            value = str(raw_value or "").strip()
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(f"{label}格式必须为YYYY-MM-DD") from exc
                filters.append(f"({date_column} AT TIME ZONE 'Asia/Shanghai')::date {operator} %s")
                params.append(value)
        keyword = str(query.get("keyword") or "").strip()
        if keyword:
            filters.append("CONCAT_WS(' ',r.operator,r.run_id::text,r.source,CASE r.source WHEN 'api' THEN 'API' WHEN 'robot' THEN '影刀' ELSE '网页' END) ILIKE %s")
            params.append(f"%{keyword}%")
        where = " AND ".join(filters)
        with self.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM ops.ingest_run r WHERE {where}", params)
            total = int(cursor.fetchone()["total"])
            try:
                cursor.execute("SELECT DISTINCT operator FROM ops.ingest_run WHERE operator IS NOT NULL AND operator<>'' ORDER BY operator")
                operator_options = [row["operator"] for row in cursor.fetchall()]
            except IndexError:  # 兼容仅模拟主查询的轻量测试游标
                operator_options = []
            cursor.execute(
                f"""
                SELECT r.*,
                       EXISTS(SELECT 1 FROM ops.etl_run e WHERE e.ingest_run_id=r.run_id) AS has_related_etl,
                       COALESCE(f.task_file_count, 0) AS task_file_count,
                       COALESCE(f.uploaded_file_count, 0) AS uploaded_file_count,
                       COALESCE(f.processing_file_count, 0) AS processing_file_count,
                       COALESCE(f.warning_file_count, 0) > 0 AS has_warning,
                       COALESCE(f.success_task_count, 0) AS success_task_count,
                       COALESCE(f.duplicate_task_count, 0) AS duplicate_task_count,
                       COALESCE(f.failed_task_count, 0) AS failed_task_count,
                       CASE WHEN r.status IN ('draft','failed')
                                   AND NOT EXISTS (
                                       SELECT 1 FROM ops.ingest_file_task t
                                       WHERE t.run_id = r.run_id AND t.batch_id IS NOT NULL
                                   )
                             THEN TRUE ELSE FALSE END AS can_delete
                FROM ops.ingest_run r
                LEFT JOIN (
                    SELECT run_id,
                           COUNT(*) AS task_file_count,
                           COUNT(*) FILTER (WHERE status='uploaded') AS uploaded_file_count,
                           COUNT(*) FILTER (WHERE status='processing') AS processing_file_count,
                            COUNT(*) FILTER (WHERE status='success') AS success_task_count,
                            COUNT(*) FILTER (WHERE status='duplicate') AS duplicate_task_count,
                           COUNT(*) FILTER (WHERE status='failed') AS failed_task_count,
                           COUNT(*) FILTER (WHERE output_summary ILIKE '%%警告%%'
                                                 OR output_summary ILIKE '%%告警%%'
                                                 OR output_summary ILIKE '%%提醒%%'
                                                 OR output_summary ILIKE '%%warn%%'
                                                 OR output_summary ILIKE '%%商品编码未配置%%'
                                                 OR output_summary ILIKE '%%warning%%'
                                                 OR error_message ILIKE '%%警告%%'
                                                 OR error_message ILIKE '%%告警%%'
                                                 OR error_message ILIKE '%%提醒%%'
                                                 OR error_message ILIKE '%%warn%%'
                                                 OR error_message ILIKE '%%商品编码未配置%%'
                                                 OR error_message ILIKE '%%warning%%') AS warning_file_count
                    FROM ops.ingest_file_task
                    GROUP BY run_id
                ) f ON f.run_id = r.run_id
                WHERE {where}
                ORDER BY r.created_at DESC
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            try:
                items = [dict(row) for row in cursor.fetchall()]
            except IndexError:  # 兼容仅模拟主查询的轻量测试游标
                items = []
            for item in items:
                counts={'uploaded':int(item.get('uploaded_file_count',0)),
                        'processing':int(item.get('processing_file_count',0)),
                        'success':int(item.get('success_task_count',0)),
                        'duplicate':int(item.get('duplicate_task_count',0)),
                        'failed':int(item.get('failed_task_count',0))}
                item.update(self._run_actions(item,counts))
            return {"items": items, "operators": operator_options, "pagination": {"total": total, "page": page, "page_size": page_size}}

    def run_detail(self, run_id: str) -> dict:
        with self.transaction() as cursor:
            detail = self._run_detail_cursor(cursor, run_id)
        # ODS统计是详情的增强信息，不能让它阻塞已经提交的导入任务详情。
        # ETL初始化DDL可能在长事务中持有ods_file_ingest_log的锁；核心详情
        # 已经从ops表读完后，再用独立连接限时补充统计，锁不可用时保留批次信息。
        return self._attach_ods_batch_metrics(detail)

    def file_review_context(self, file_task_id: str) -> dict:
        with self.transaction() as cursor:
            cursor.execute('SELECT run_id FROM ops.ingest_file_task WHERE file_task_id=%s',(file_task_id,))
            task=cursor.fetchone()
            if not task:
                raise NotFoundError('原上传记录不存在，请从原文件重新上传')
            return self._run_detail_cursor(cursor,str(task['run_id']))

    @staticmethod
    def _run_detail_cursor(cursor, run_id: str) -> dict:
        cursor.execute("SELECT * FROM ops.ingest_run WHERE run_id=%s", (run_id,))
        run = cursor.fetchone()
        if not run:
            raise NotFoundError("采集会话不存在")
        cursor.execute("SELECT * FROM ops.ingest_file_task WHERE run_id=%s ORDER BY created_at,client_file_id", (run_id,))
        files = [dict(row) for row in cursor.fetchall()]
        if files:
            cursor.execute(
                """
                SELECT b.file_task_id,b.batch_id,b.target_table
                FROM ops.ingest_file_task_batch b
                WHERE b.file_task_id = ANY(%s::uuid[])
                ORDER BY target_table,batch_id
                """,
                ([str(item["file_task_id"]) for item in files],),
            )
            batches_by_task: dict[str, list[dict]] = {}
            for row in cursor.fetchall():
                payload = dict(row)
                batches_by_task.setdefault(str(payload.pop("file_task_id")), []).append(payload)
            for item in files:
                item["ods_batches"] = batches_by_task.get(str(item["file_task_id"]), [])
        counts={status:sum(f['status']==status for f in files) for status in {f['status'] for f in files}}
        run={**run,**FileIngestService._run_actions(run,counts)}
        if any(not file.get('batch_id') for file in files):
            run['can_reuse']=False
        cursor.execute("SELECT etl_run_id,status,created_at,completed_at FROM ops.etl_run WHERE ingest_run_id=%s ORDER BY created_at", (run_id,))
        etls=[dict(row) for row in cursor.fetchall()]
        if etls:
            run['can_resume']=False
        return {"run": run, "files": files, "etl_runs": etls}

    def _attach_ods_batch_metrics(self, detail: dict) -> dict:
        batch_items = [
            batch
            for file_task in detail.get("files", [])
            for batch in file_task.get("ods_batches", [])
            if batch.get("batch_id") is not None
        ]
        batch_ids = list(dict.fromkeys(batch["batch_id"] for batch in batch_items))
        if not batch_ids:
            return detail
        try:
            with self.transaction() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '100ms'")
                cursor.execute("SET LOCAL statement_timeout = '1000ms'")
                cursor.execute(
                    """
                    SELECT batch_id,total_rows,parsed_rows,success_rows,failed_rows,
                           ingest_status,error_message AS ods_error_message
                    FROM ods.ods_file_ingest_log
                    WHERE batch_id = ANY(%s)
                    """,
                    (batch_ids,),
                )
                metrics_by_batch = {
                    row["batch_id"]: dict(row)
                    for row in cursor.fetchall()
                }
        except Exception as exc:
            # PostgreSQL 55P03=lock_not_available, 57014=query_canceled.
            # 这两种情况只表示统计暂时不可读，核心任务详情仍然有效；
            # 其它数据库错误继续抛出，避免掩盖真实配置/结构问题。
            if getattr(exc, "pgcode", None) in {"55P03", "57014"}:
                return detail
            raise
        for batch in batch_items:
            metrics = metrics_by_batch.get(batch["batch_id"])
            if metrics:
                batch.update(metrics)
        return detail

    @staticmethod
    def _relation_count(cursor, relation: str) -> int | None:
        """Return a whitelisted relation's row count, or ``None`` if absent."""
        cursor.execute("SELECT to_regclass(%s) AS relation", (relation,))
        row = cursor.fetchone()
        registered = row.get("relation") if isinstance(row, dict) else row[0]
        if registered is None:
            return None
        schema_name, table_name = relation.split(".", 1)
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS row_count FROM {}.{}").format(
                sql.Identifier(schema_name), sql.Identifier(table_name)
            )
        )
        row = cursor.fetchone()
        value = row.get("row_count") if isinstance(row, dict) else row[0]
        return int(value or 0)

    def _deferred_etl_reasons(self, specs: Iterable[Any], *, trigger_type: str, scope: str, cursor) -> dict[str, str]:
        """Evaluate optional source-readiness contracts for affected ETL runs.

        An empty platform source is valid and is handled by the ETL as zero values;
        only a future explicit contract in the registry can defer a node here.
        """
        if scope != "affected" or trigger_type != "ingest_complete":
            return {}
        reasons: dict[str, str] = {}
        spec_list = list(specs)
        planned_keys = {spec.key for spec in spec_list}
        for spec in spec_list:
            required_relations = ETL_SOURCE_READINESS.get(spec.key)
            if not required_relations:
                continue
            missing: list[str] = []
            for relation in required_relations:
                feeder_keys = ETL_SOURCE_READINESS_FEEDERS.get(spec.key, {}).get(relation, frozenset())
                if feeder_keys & planned_keys:
                    continue
                count = self._relation_count(cursor, relation)
                if count is None:
                    missing.append(f"{relation}不存在")
                elif count == 0:
                    missing.append(f"{relation}=0")
            if missing:
                reasons[spec.key] = (
                    f"来源未就绪，暂不执行{spec.label}；请导入缺少的平台数据后重试："
                    + "、".join(missing)
                )
        return reasons

    def create_etl_run(
        self,
        keys: Iterable[str],
        *,
        trigger_type: str,
        scope: str,
        operator: str,
        ingest_run_id: str | None = None,
        cursor=None,
        deferred_reasons: dict[str, str] | None = None,
        reuse: bool = True,
    ) -> dict:
        if scope == 'all' and trigger_type != 'manual':
            raise ValueError('全量刷新只能由人工创建；自动任务必须按受影响范围刷新')
        key_set = set(keys)
        specs = plan_etls(key_set)
        if cursor is None:
            with self.transaction() as owned:
                return self.create_etl_run(
                    key_set,
                    trigger_type=trigger_type,
                    scope=scope,
                    operator=operator,
                    ingest_run_id=ingest_run_id,
                    cursor=owned,
                    deferred_reasons=deferred_reasons,
                    reuse=reuse,
                )
        deferred = dict(deferred_reasons or {})
        if reuse and trigger_type == 'ingest_complete' and ingest_run_id:
            # FileIngest and a flow's explicit ETL node can both request the
            # same import. Keep one execution and one truthful linkage.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ('ingest-refresh:' + str(ingest_run_id),))
            cursor.execute('''SELECT etl_run_id,status,requested_etls FROM ops.etl_run
                WHERE ingest_run_id=%s AND trigger_type='ingest_complete'
                AND status IN ('queued','running','success','success_with_warnings','no_change')
                ORDER BY created_at DESC LIMIT 1''', (str(ingest_run_id),))
            existing = cursor.fetchone()
            if existing and {item.key for item in specs}.issubset(set(existing['requested_etls'] or [])):
                return {'etl_run_id': existing['etl_run_id'], 'status': existing['status'],
                        'tasks': existing['requested_etls'], 'deferred': {}, 'reused': True}
        for key, reason in self._deferred_etl_reasons(specs, trigger_type=trigger_type, scope=scope, cursor=cursor).items():
            deferred.setdefault(key, reason)
        etl_run_id = uuid.uuid4()
        cursor.execute(
            """
            INSERT INTO ops.etl_run(etl_run_id,ingest_run_id,trigger_type,scope,status,requested_etls,operator)
            VALUES(%s,%s,%s,%s,%s,%s,%s)
            """,
            (str(etl_run_id), ingest_run_id, trigger_type, scope, "no_change" if not specs else "queued", Json([item.key for item in specs]), operator),
        )
        task_keys = {item.key for item in specs}
        feeding_keys = [item.key for item in specs if item.feeds_platform_bank_summary]
        for sequence_no, spec in enumerate(specs, start=1):
            if spec.key == "platform_bank_summary":
                dependencies = feeding_keys
            else:
                dependencies = sorted(
                    dependency
                    for dependency in ETL_TASK_PREREQUISITES.get(spec.key, set())
                    if dependency in task_keys
                )
            cursor.execute(
                """
                INSERT INTO ops.etl_task(
                    etl_task_id,etl_run_id,etl_key,etl_label,sequence_no,
                    dependencies,command_args,status,error_message,finished_at
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,CASE WHEN %s='deferred' THEN NOW() END)
                """,
                (
                    str(uuid.uuid4()), str(etl_run_id), spec.key, spec.label,
                    sequence_no, Json(dependencies), Json(list(spec.args)),
                    "deferred" if spec.key in deferred else "queued",
                    deferred.get(spec.key),
                    "deferred" if spec.key in deferred else "queued",
                ),
            )
        return {
            "etl_run_id": etl_run_id,
            "status": "no_change" if not specs else "queued",
            "tasks": [item.key for item in specs],
            "deferred": deferred,
        }

    def create_manual_etl(self, payload: dict, operator: str) -> dict:
        scope = payload.get("scope", "selected")
        if scope == "all":
            keys = full_refresh_etl_keys()
        elif scope == "selected":
            keys = set(payload.get("etls") or [])
            if "bank_management" in keys:
                raise ValueError("银行经营指标只能在财务提交锁定银行批次后刷新")
        else:
            raise ValueError("scope仅支持all或selected")
        return self.create_etl_run(keys, trigger_type="manual", scope=scope, operator=operator)

    def enqueue_bank_refresh(self, cursor, operator: str) -> dict:
        return self.create_etl_run({"bank_management"}, trigger_type="bank_submit", scope="affected", operator=operator, cursor=cursor)

    def etl_detail(self, etl_run_id: str) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.etl_run WHERE etl_run_id=%s", (etl_run_id,))
            run = cursor.fetchone()
            if not run:
                raise NotFoundError("ETL运行不存在")
            cursor.execute("SELECT * FROM ops.etl_task WHERE etl_run_id=%s ORDER BY sequence_no", (etl_run_id,))
            detail = {"run": dict(run), "tasks": [dict(row) for row in cursor.fetchall()]}
        detail['snapshot_diagnostics'] = self.snapshot_diagnostics(detail['run'].get('refresh_context'),detail['run']['requested_etls'])
        return detail

    def snapshot_diagnostics(self, context, etl_keys):
        if not context or context.get('mode') != 'incremental':
            return {'status':'not_applicable','snapshot_stale':False}
        from .source_diagnostics import observe
        try:
            with self.transaction() as cursor:
                return observe(cursor,context,etl_keys)
        except Exception as exc:
            # Observation must never change/expand inputs or fail a metric.
            return {'status':'unavailable','snapshot_stale':None,'error_type':type(exc).__name__,
                    'message':'相关来源快照对比暂不可用；计算仍使用原冻结范围。'}

    def list_etl_runs(self, page: int = 1, page_size: int = 10, query: dict[str, Any] | None = None) -> dict:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 200))
        query = query or {}
        filters = ["TRUE"]
        params: list[Any] = []
        operators = [value.strip() for value in str(query.get("operator") or "").replace("，", ",").split(",") if value.strip()]
        if operators:
            filters.append("r.operator=ANY(%s)")
            params.append(operators)
        status = str(query.get("status") or "").strip()
        if status:
            filters.append("r.status=%s")
            params.append(status)
        date_field = str(query.get("date_field") or "started_at").strip()
        date_column = {"started_at": "r.started_at", "completed_at": "r.completed_at"}.get(date_field, "r.started_at")
        for raw_value, label, operator in (
            (query.get("date_from"), "开始日期", ">="),
            (query.get("date_to"), "结束日期", "<="),
        ):
            value = str(raw_value or "").strip()
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(f"{label}格式必须为YYYY-MM-DD") from exc
                filters.append(f"({date_column} AT TIME ZONE 'Asia/Shanghai')::date {operator} %s")
                params.append(value)
        keyword = str(query.get("keyword") or "").strip()
        if keyword:
            filters.append("CONCAT_WS(' ',r.operator,r.etl_run_id::text,r.trigger_type,CASE r.trigger_type WHEN 'manual' THEN '人工创建' WHEN 'nightly' THEN '夜间全量' WHEN 'ingest_complete' THEN '导入完成' ELSE r.trigger_type END) ILIKE %s")
            params.append(f"%{keyword}%")
        where = " AND ".join(filters)
        with self.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM ops.etl_run r WHERE {where}", params)
            total = int(cursor.fetchone()["total"])
            try:
                cursor.execute("SELECT DISTINCT operator FROM ops.etl_run WHERE operator IS NOT NULL AND operator<>'' ORDER BY operator")
                operator_options = [row["operator"] for row in cursor.fetchall()]
            except IndexError:  # 兼容仅模拟主查询的轻量测试游标
                operator_options = []
            cursor.execute(
                f"""
                SELECT r.*,
                       EXISTS (
                           SELECT 1
                           FROM ops.etl_task t
                           WHERE t.etl_run_id = r.etl_run_id
                             AND (t.output_summary ILIKE '%%警告%%'
                                  OR t.output_summary ILIKE '%%告警%%'
                                  OR t.output_summary ILIKE '%%提醒%%'
                                  OR t.output_summary ILIKE '%%warn%%'
                                  OR t.output_summary ILIKE '%%商品编码未配置%%'
                                  OR t.output_summary ILIKE '%%warning%%'
                                  OR t.error_message ILIKE '%%警告%%'
                                  OR t.error_message ILIKE '%%告警%%'
                                  OR t.error_message ILIKE '%%提醒%%'
                                  OR t.error_message ILIKE '%%warn%%'
                                  OR t.error_message ILIKE '%%商品编码未配置%%'
                                  OR t.error_message ILIKE '%%warning%%')
                       ) AS has_warning
                FROM ops.etl_run r
                WHERE {where}
                ORDER BY r.created_at DESC
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            try:
                items = [dict(row) for row in cursor.fetchall()]
            except IndexError:  # 兼容仅模拟主查询的轻量测试游标
                items = []
            return {"items": items, "operators": operator_options, "pagination": {"total": total, "page": page, "page_size": page_size}}

    def retry_etl_task(self, task_id: str, operator: str, ip_address: str | None, *, snapshot_policy: str = 'latest', confirm_replay_publish: bool = False) -> dict:
        if snapshot_policy not in {'latest','replay'}:
            raise ValueError('snapshot_policy必须为latest或replay')
        if snapshot_policy == 'replay' and confirm_replay_publish is not True:
            raise ConflictError('原快照重放会写回并替换原范围的当前指标，并非只读诊断；必须显式确认 confirm_replay_publish=true。普通补数据请使用latest。')
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.etl_task WHERE etl_task_id=%s", (task_id,))
            task = cursor.fetchone()
            if not task:
                raise NotFoundError("ETL任务不存在")
            if task["status"] not in {"failed", "skipped", "deferred"}:
                raise ConflictError("只有failed、skipped或deferred任务可以重试")
            spec = ETL_SPECS.get(task["etl_key"])
            if spec is not None and not spec.enabled:
                raise ConflictError(f"ETL任务已停用，不能重试：{spec.label}")
            cursor.execute('SELECT * FROM ops.etl_run WHERE etl_run_id=%s FOR UPDATE', (task['etl_run_id'],))
            parent = dict(cursor.fetchone())
            if parent['status'] in {'queued','running'}:
                raise ConflictError('原运行仍在处理，请等待结束后重试')
            cursor.execute("SELECT etl_run_id,status,refresh_context FROM ops.etl_run WHERE parent_etl_run_id=%s AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1", (task['etl_run_id'],))
            existing = cursor.fetchone()
            if existing:
                existing_policy=(existing.get('refresh_context') or {}).get('snapshot_policy','latest')
                if existing_policy != snapshot_policy:
                    raise ConflictError('该运行已有不同快照方式的重跑正在处理，不能将原快照重放与最新数据重跑相互复用；请等待该运行结束。')
                return {'etl_run_id':existing['etl_run_id'],'status':existing['status'],
                        'snapshot_policy':existing_policy,'reused':True,'message':'该运行已有相同快照方式的重跑正在处理'}
            from .refresh_scope import retry_refresh_context
            recovery = None
            if snapshot_policy == 'latest':
                from .coverage import recover_legacy_ingest
                recovery = recover_legacy_ingest(cursor, parent['ingest_run_id'], self.storage_root, operator)
            context = retry_refresh_context(cursor, parent, replay=snapshot_policy=='replay')
            context['snapshot_policy'] = snapshot_policy
            result = self.create_etl_run(parent['requested_etls'], trigger_type=parent['trigger_type'],
                scope=parent['scope'], operator=operator, ingest_run_id=parent['ingest_run_id'], cursor=cursor, reuse=False)
            cursor.execute('UPDATE ops.etl_run SET parent_etl_run_id=%s,refresh_context=%s WHERE etl_run_id=%s',
                           (parent['etl_run_id'],Json(context),str(result['etl_run_id'])))
            result.update({'etl_run_id':str(result['etl_run_id']), 'parent_etl_run_id':str(parent['etl_run_id']), 'snapshot_policy':snapshot_policy,
                'batch_cutoff':context.get('batch_cutoff'), 'months':context.get('months'), 'shops':context.get('shops'),
                'message':'已创建关联运行，使用最新数据重跑原店铺和原月份的相关任务链；不会扩展到新月份，历史记录保留'})
            if snapshot_policy == 'replay':
                result['message']='已按明确确认的原快照创建重放运行，将写回原店铺和原月份的指标；不会纳入后来数据。'
                result['confirm_replay_publish']=True
            if recovery:
                result['coverage_recovery'] = recovery
                counts = recovery['summary']
                result['message'] = (f"已核对并恢复历史文件采信：{counts.get('same',0)}个重叠日期内容一致、"
                    f"{counts.get('new_only',0)}个缺失日期已补入；已按新采信快照创建关联重试运行")
            self._write_log(cursor, "etl_retry", "etl_task", task_id, operator, ip_address, "创建关联ETL重试运行", result)
        return result

    @staticmethod
    def _write_log(cursor, operation_type: str, target_type: str, target_key: str | None, operator: str, ip_address: str | None, description: str, detail: dict | None) -> None:
        cursor.execute(
            """
            INSERT INTO ops.operation_log(operation_type,target_type,target_key,operator,ip_address,description,change_detail)
            VALUES(%s,%s,%s,%s,%s,%s,%s)
            """,
            (operation_type, target_type, target_key, operator, ip_address, description, Json(detail) if detail is not None else None),
        )

    def list_operation_logs(self, page: int = 1, page_size: int = 10, query: dict[str, Any] | None = None) -> dict:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        query = query or {}
        filters: list[str] = []
        params: list[Any] = []
        date_from = str(query.get("date_from") or "").strip()
        date_to = str(query.get("date_to") or "").strip()
        for value, label, expression in (
            (date_from, "开始日期", "(created_at AT TIME ZONE 'Asia/Shanghai')::date >= %s"),
            (date_to, "结束日期", "(created_at AT TIME ZONE 'Asia/Shanghai')::date <= %s"),
        ):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(f"{label}格式必须为YYYY-MM-DD") from exc
                filters.append(expression)
                params.append(value)
        operation_type = str(query.get("operation_type") or "").strip()
        if operation_type:
            filters.append("operation_type=%s")
            params.append(operation_type)
        operators = [value.strip() for value in str(query.get("operator") or "").replace("，", ",").split(",") if value.strip()]
        if operators:
            if len(operators) == 1:
                filters.append("operator=%s")
                params.append(operators[0])
            else:
                filters.append("operator=ANY(%s)")
                params.append(operators)
        keyword = str(query.get("keyword") or "").strip()
        if keyword:
            pattern = f"%{keyword}%"
            filters.append(
                """
                (
                    operator ILIKE %s
                    OR operation_type ILIKE %s
                    OR description ILIKE %s
                    OR CASE operation_type
                        WHEN 'run_create' THEN '创建采集会话'
                        WHEN 'file_upload' THEN '文件上传'
                        WHEN 'parameter_correction' THEN '参数修正'
                        WHEN 'run_complete' THEN '提交采集会话'
                        WHEN 'run_failed' THEN '上传会话失败'
                        WHEN 'run_delete' THEN '删除未完成采集会话'
                        WHEN 'file_retry' THEN '重试文件任务'
                        WHEN 'run_timeout' THEN '上传会话超时'
                        WHEN 'run_resume' THEN '继续确认导入'
                        WHEN 'run_draft_save' THEN '保存导入草稿'
                        WHEN 'etl_retry' THEN '重试ETL任务'
                        WHEN 'etl_schedule_update' THEN '更新夜间全量刷新配置'
                        WHEN 'finance_config_save' THEN '保存经营预算配置'
                        WHEN 'finance_config_delete' THEN '删除经营预算配置'
                        WHEN 'finance_expense_type_save' THEN '维护营销费用类型'
                        WHEN 'finance_expense_type_delete' THEN '删除营销费用类型'
                        WHEN 'fee_category_create' THEN '新增平台费用一级分类'
                        WHEN 'fee_category_update' THEN '修改平台费用一级分类'
                        WHEN 'fee_category_delete' THEN '删除平台费用一级分类'
                        WHEN 'fee_mapping_assign' THEN '批量映射费用场景'
                        WHEN 'fee_mapping_status' THEN '启停费用映射'
                        WHEN 'fee_mapping_delete' THEN '删除费用映射'
                        ELSE operation_type
                    END ILIKE %s
                )
                """
            )
            params.extend([pattern, pattern, pattern, pattern])
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.transaction() as cursor:
            cursor.execute("SELECT DISTINCT operation_type FROM ops.operation_log WHERE operation_type IS NOT NULL ORDER BY operation_type")
            stored_types = [row["operation_type"] for row in cursor.fetchall()]
            type_codes = list(OPERATION_TYPE_LABELS)
            type_codes.extend(code for code in stored_types if code not in OPERATION_TYPE_LABELS)
            operation_types = [{"value": code, "label": OPERATION_TYPE_LABELS.get(code, code)} for code in type_codes]
            cursor.execute("SELECT DISTINCT operator FROM ops.operation_log WHERE operator IS NOT NULL AND operator<>'' ORDER BY operator")
            operators = [row["operator"] for row in cursor.fetchall()]
            cursor.execute(f"SELECT COUNT(*) AS total FROM ops.operation_log {where}", params)
            total = int(cursor.fetchone()["total"])
            final_params = params + [page_size, (page - 1) * page_size]
            cursor.execute(f"SELECT * FROM ops.operation_log {where} ORDER BY created_at DESC LIMIT %s OFFSET %s", final_params)
            return {
                "items": [dict(row) for row in cursor.fetchall()],
                "operation_types": operation_types,
                "operators": operators,
                "pagination": {"total": total, "page": page, "page_size": page_size},
            }

    @staticmethod
    def _finance_date(value: Any, label: str, *, month_start: bool = False) -> date:
        try:
            parsed = date.fromisoformat(str(value or ""))
        except ValueError as exc:
            raise ValueError(f"{label}格式必须为YYYY-MM-DD") from exc
        if month_start and parsed.day != 1:
            raise ValueError(f"{label}必须选择当月1日")
        return parsed

    @staticmethod
    def _finance_amount(value: Any, label: str, *, positive: bool = False, nonnegative: bool = False) -> Decimal:
        try:
            amount = Decimal(str(value if value not in {None, ""} else "0")).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{label}必须是有效金额") from exc
        if positive and amount <= 0:
            raise ValueError(f"{label}必须大于0")
        if nonnegative and amount < 0:
            raise ValueError(f"{label}不能小于0")
        return amount

    @staticmethod
    def _finance_resource(resource: str) -> dict:
        resources = {
            "budgets": {"table": "config.finance_budget_monthly", "pk": "budget_month", "soft": False},
            "shop-plans": {"table": "config.finance_shop_plan_monthly", "pk": "shop_plan_id", "soft": True},
            "gsv-targets": {"table": "config.finance_shop_plan_monthly", "pk": "shop_plan_id", "soft": True},
            "shop-budgets": {"table": "config.finance_shop_plan_monthly", "pk": "shop_plan_id", "soft": True},
            "recharges": {"table": "config.finance_promotion_recharge_detail", "pk": "recharge_id", "soft": True},
            "adjustments": {"table": "config.finance_promotion_budget_adjustment", "pk": "adjustment_id", "soft": True},
            "marketing-expenses": {"table": "config.finance_marketing_expense_detail", "pk": "marketing_expense_id", "soft": True},
            "marketing-budget-history": {"table": "config.finance_marketing_budget_change_history", "pk": "history_id", "soft": False},
            "expense-types": {"table": "config.finance_marketing_expense_type", "pk": "expense_type_id", "soft": False},
        }
        if resource not in resources:
            raise NotFoundError("经营配置类型不存在")
        return resources[resource]

    @staticmethod
    def _finance_values(query: dict, *names: str) -> list[str]:
        values: list[str] = []
        for name in names:
            raw = query.get(name)
            if raw is None:
                continue
            raw_values = raw if isinstance(raw, (list, tuple)) else str(raw).replace("，", ",").split(",")
            for value in raw_values:
                normalized = normalize_name(value)
                if normalized and normalized not in values:
                    values.append(normalized)
        return values

    @staticmethod
    def _finance_month_bounds(month: date) -> tuple[date, date]:
        next_month = date(
            month.year + (1 if month.month == 12 else 0),
            1 if month.month == 12 else month.month + 1,
            1,
        )
        return month, next_month

    @staticmethod
    def _finance_dim_date(month: date) -> date:
        today = date.today()
        return today if (today.year, today.month) == (month.year, month.month) else month

    def _finance_shop_console_rows(self, cursor, month: date, query: dict | None = None) -> list[dict]:
        """返回某月DIM全量有效店铺，配置、充值和实际指标均使用左连接。"""
        query = query or {}
        month_start, next_month = self._finance_month_bounds(month)
        dim_date = self._finance_dim_date(month)
        conditions = ["TRUE"]
        dim_active_condition = "d.is_active" if (month.year, month.month) >= (date.today().year, date.today().month) else "TRUE"
        params: list[Any] = [month_start, next_month, month_start, next_month, dim_date, dim_date, month_start, month_start, next_month]
        filters = (
            ("platform_codes", "platform_code", "d.platform_code"),
            ("company_codes", "company_code", "d.company_code"),
            ("shop_codes", "shop_code", "d.shop_code"),
        )
        for plural, singular, expression in filters:
            values = self._finance_values(query, plural, singular)
            if values:
                conditions.append(f"{expression}=ANY(%s)")
                params.append(values)
        keyword = normalize_name(query.get("keyword", ""))
        if keyword:
            conditions.append(
                "CONCAT_WS(' ',d.platform_name,d.platform_code,d.company_name,d.company_code,d.shop_name,d.shop_code) ILIKE %s"
            )
            params.append(f"%{keyword}%")
        cursor.execute(
            f"""
            WITH gsv AS (
                SELECT platform_code, company_code, shop_code,
                       SUM(gsv_amount)::numeric(18,2) AS actual_gsv_amount
                FROM ads.ads_gsv_company_daily
                WHERE stat_date >= %s AND stat_date < %s
                GROUP BY platform_code, company_code, shop_code
            ), promotion AS (
                SELECT platform_code, company_code, shop_code,
                       SUM(promotion_expense_amount)::numeric(18,2) AS promotion_expense_amount
                FROM ads.ads_promotion_expense_company_shop_daily
                WHERE stat_date >= %s AND stat_date < %s
                GROUP BY platform_code, company_code, shop_code
            ), actual AS (
                SELECT COALESCE(gsv.platform_code,promotion.platform_code) AS platform_code,
                       COALESCE(gsv.company_code,promotion.company_code) AS company_code,
                       COALESCE(gsv.shop_code,promotion.shop_code) AS shop_code,
                       COALESCE(gsv.actual_gsv_amount,0)::numeric(18,2) AS actual_gsv_amount,
                       COALESCE(promotion.promotion_expense_amount,0)::numeric(18,2) AS promotion_expense_amount
                FROM gsv
                FULL JOIN promotion
                  ON promotion.platform_code=gsv.platform_code
                 AND promotion.company_code=gsv.company_code
                 AND promotion.shop_code=gsv.shop_code
            ), dim_rows AS (
                SELECT d.*
                FROM dim.dim_platform_shop_company d
                WHERE {dim_active_condition}
                  AND %s >= d.valid_from
                  AND (d.valid_to IS NULL OR %s <= d.valid_to)
            ), plans AS (
                SELECT p.*
                FROM config.finance_shop_plan_monthly p
                WHERE p.budget_month=%s AND p.deleted_at IS NULL
            ), recharges AS (
                SELECT r.shop_code,
                       SUM(r.recharge_amount)::numeric(18,2) AS recharge_amount,
                       COUNT(*) AS recharge_count,
                       MAX(r.recharge_date) AS latest_recharge_date,
                       (ARRAY_AGG(r.recharge_amount ORDER BY r.recharge_date DESC,r.recharge_id DESC))[1]::numeric(18,2) AS latest_recharge_amount
                FROM config.finance_promotion_recharge_detail r
                WHERE r.recharge_date >= %s AND r.recharge_date < %s AND r.deleted_at IS NULL
                GROUP BY r.shop_code
            )
            SELECT d.platform_code,d.platform_name,d.company_code,d.company_name,
                   d.shop_code,d.shop_name,d.shop_type,d.account_id,d.shop_company_sk,
                   p.shop_plan_id,
                   p.promotion_budget_amount,
                   p.gsv_target_amount,
                   p.remark AS plan_remark,
                   (p.shop_plan_id IS NOT NULL) AS budget_or_target_is_set,
                   COALESCE(r.recharge_amount,0)::numeric(18,2) AS recharge_amount,
                   COALESCE(r.recharge_count,0)::integer AS recharge_count,
                   r.latest_recharge_date,r.latest_recharge_amount,
                   COALESCE(a.actual_gsv_amount,0)::numeric(18,2) AS actual_gsv_amount,
                   COALESCE(a.promotion_expense_amount,0)::numeric(18,2) AS promotion_expense_amount
            FROM dim_rows d
            LEFT JOIN plans p ON p.shop_code=d.shop_code
            LEFT JOIN recharges r ON r.shop_code=d.shop_code
            LEFT JOIN actual a
              ON a.platform_code=d.platform_code
             AND a.company_code=d.company_code
             AND a.shop_code=d.shop_code
            WHERE {' AND '.join(conditions)}
            ORDER BY d.platform_name,d.company_name,d.shop_name,d.shop_code
            """,
            params,
        )
        rows: list[dict] = []
        for raw in cursor.fetchall():
            row = dict(raw)
            promotion_budget = Decimal(str(row.get("promotion_budget_amount") or 0))
            recharge_amount = Decimal(str(row.get("recharge_amount") or 0))
            actual_gsv = Decimal(str(row.get("actual_gsv_amount") or 0))
            actual_promotion = Decimal(str(row.get("promotion_expense_amount") or 0))
            gsv_target = row.get("gsv_target_amount")
            target_amount = Decimal(str(gsv_target or 0))
            row["target_is_set"] = row.get("shop_plan_id") is not None
            row["budget_is_set"] = row.get("shop_plan_id") is not None
            row["gsv_target_amount"] = gsv_target
            row["promotion_budget_amount"] = promotion_budget
            row["pending_recharge_amount"] = (promotion_budget - recharge_amount).quantize(Decimal("0.01"))
            row["over_recharge_amount"] = max(recharge_amount - promotion_budget, Decimal("0.00")).quantize(Decimal("0.01"))
            row["theoretical_account_balance"] = (recharge_amount - actual_promotion).quantize(Decimal("0.01"))
            row["gsv_completion_rate"] = (actual_gsv * Decimal("100") / target_amount).quantize(Decimal("0.01")) if target_amount else Decimal("0.00")
            row["promotion_execution_rate"] = (actual_promotion * Decimal("100") / promotion_budget).quantize(Decimal("0.01")) if promotion_budget else Decimal("0.00")
            rows.append(row)
        return rows

    @staticmethod
    def _refresh_finance_configuration(cursor) -> None:
        for relative in (
            "sql/common/387_refresh_dwd_finance_operating_configuration_detail_postgres.sql",
            "sql/common/388_refresh_dws_finance_operating_configuration_monthly_postgres.sql",
            "sql/ads/389_refresh_ads_finance_operating_configuration_monthly_postgres.sql",
        ):
            cursor.execute((PROJECT_ROOT / relative).read_text(encoding="utf-8"))

    def list_finance_expense_types(self, query: dict | None = None) -> dict:
        query = query or {}
        page = max(1, int(query.get("page", 1)))
        page_size = max(1, min(int(query.get("page_size", 10)), 200))
        conditions = ["TRUE"]
        params: list[Any] = []
        status = normalize_name(query.get("status", ""))
        if status in {"active", "inactive"}:
            conditions.append("t.is_active=%s")
            params.append(status == "active")
        keyword = normalize_name(query.get("keyword", ""))
        if keyword:
            conditions.append("CONCAT_WS(' ',t.expense_type_code,t.expense_type_name,COALESCE(t.remark,'')) ILIKE %s")
            params.append(f"%{keyword}%")
        where = " AND ".join(conditions)
        with self.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM config.finance_marketing_expense_type t WHERE {where}", params)
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""SELECT t.* FROM config.finance_marketing_expense_type t
                    WHERE {where}
                    ORDER BY t.is_active DESC,t.expense_type_name,t.expense_type_id
                    LIMIT %s OFFSET %s""",
                [*params, page_size, (page - 1) * page_size],
            )
            items = [dict(row) for row in cursor.fetchall()]
        return {"items": items, "pagination": {"total": total, "page": page, "page_size": page_size}}

    def list_finance_marketing_budget_history(self, query: dict | None = None) -> dict:
        query = query or {}
        page = max(1, int(query.get("page", 1)))
        page_size = max(1, min(int(query.get("page_size", 10)), 200))
        conditions = ["TRUE"]
        params: list[Any] = []
        month = normalize_name(query.get("budget_month", ""))
        if month:
            conditions.append("budget_month=%s")
            params.append(self._finance_date(month, "月份", month_start=True))
        date_from = normalize_name(query.get("date_from", ""))
        if date_from:
            self._finance_date(date_from, "开始日期")
            conditions.append("(changed_at AT TIME ZONE 'Asia/Shanghai')::date >= %s")
            params.append(date_from)
        date_to = normalize_name(query.get("date_to", ""))
        if date_to:
            self._finance_date(date_to, "结束日期")
            conditions.append("(changed_at AT TIME ZONE 'Asia/Shanghai')::date <= %s")
            params.append(date_to)
        changed_by_values = self._finance_values(query, "changed_by")
        if changed_by_values:
            conditions.append("changed_by=ANY(%s)")
            params.append(changed_by_values)
        keyword = normalize_name(query.get("keyword", ""))
        if keyword:
            conditions.append("CONCAT_WS(' ',changed_by,remark) ILIKE %s")
            params.append(f"%{keyword}%")
        where = " AND ".join(conditions)
        with self.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM config.finance_marketing_budget_change_history WHERE {where}", params)
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""SELECT * FROM config.finance_marketing_budget_change_history
                    WHERE {where}
                    ORDER BY changed_at DESC,history_id DESC
                    LIMIT %s OFFSET %s""",
                [*params, page_size, (page - 1) * page_size],
            )
            items = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT DISTINCT changed_by FROM config.finance_marketing_budget_change_history WHERE changed_by IS NOT NULL AND changed_by<>'' ORDER BY changed_by")
            operator_options = [row["changed_by"] for row in cursor.fetchall()]
        return {"items": items, "operators": operator_options, "pagination": {"total": total, "page": page, "page_size": page_size}}

    def list_finance_configuration(self, resource: str, query: dict) -> dict:
        if resource == "expense-types":
            return self.list_finance_expense_types(query)
        if resource == "marketing-budget-history":
            return self.list_finance_marketing_budget_history(query)
        if resource in {"shop-plans", "gsv-targets", "shop-budgets", "promotion-spend"} or (
            resource == "recharges" and query.get("console", "true") != "false"
        ):
            page = max(1, int(query.get("page", 1)))
            page_size = max(1, min(int(query.get("page_size", 10)), 200))
            month_text = normalize_name(query.get("budget_month", ""))
            month = self._finance_date(month_text, "月份", month_start=True) if month_text else date(date.today().year, date.today().month, 1)
            with self.transaction() as cursor:
                rows = self._finance_shop_console_rows(cursor, month, query)
            start = (page - 1) * page_size
            return {"items": rows[start:start + page_size], "pagination": {"total": len(rows), "page": page, "page_size": page_size}}
        meta = self._finance_resource(resource)
        page = max(1, int(query.get("page", 1)))
        page_size = max(1, min(int(query.get("page_size", 10)), 200))
        conditions = ["t.deleted_at IS NULL"] if meta["soft"] else ["TRUE"]
        if resource == "adjustments":
            conditions.append("t.approval_status='approved'")
        params: list[Any] = []
        month = normalize_name(query.get("budget_month", ""))
        if month:
            month_column = {
                "budgets": "t.budget_month", "shop-plans": "t.budget_month",
                "recharges": "t.recharge_date", "adjustments": "t.budget_month",
                "marketing-expenses": "t.expense_date",
            }[resource]
            conditions.append(f"DATE_TRUNC('month', {month_column})::date=%s")
            params.append(self._finance_date(month, "月份", month_start=True))
        if resource == "shop-plans":
            select = "t.*,d.platform_code,d.platform_name,d.company_code,d.company_name,d.shop_name"
            join = "JOIN dim.dim_platform_shop_company d ON d.shop_code=t.shop_code AND d.is_active AND t.budget_month>=d.valid_from AND (d.valid_to IS NULL OR t.budget_month<=d.valid_to)"
            order = "t.budget_month DESC,d.platform_name,d.company_name,d.shop_name"
        elif resource == "recharges":
            select = "t.*,d.platform_code,d.platform_name,d.company_code,d.company_name,d.shop_name"
            history_query = query.get("console", "true") == "false"
            dim_activity = "" if history_query else "d.is_active AND "
            join = f"JOIN dim.dim_platform_shop_company d ON d.shop_code=t.shop_code AND {dim_activity}t.recharge_date>=d.valid_from AND (d.valid_to IS NULL OR t.recharge_date<=d.valid_to)"
            order = "t.recharge_date DESC,t.recharge_id DESC"
        else:
            select, join = "t.*", ""
            order = {
                "budgets": "t.budget_month DESC", "adjustments": "t.adjustment_date DESC,t.adjustment_id DESC",
                "marketing-expenses": "t.expense_date DESC,t.marketing_expense_id DESC",
            }[resource]
        platform_code = normalize_name(query.get("platform_code", ""))
        if platform_code and resource in {"shop-plans", "recharges"}:
            conditions.append("d.platform_code=%s")
            params.append(platform_code)
        company_code = normalize_name(query.get("company_code", ""))
        if company_code and resource in {"shop-plans", "recharges"}:
            conditions.append("d.company_code=%s")
            params.append(company_code)
        shop_code = normalize_name(query.get("shop_code", ""))
        if shop_code and resource == "recharges":
            conditions.append("t.shop_code=%s")
            params.append(shop_code)
        approval_status = normalize_name(query.get("approval_status", ""))
        if approval_status and resource == "adjustments":
            conditions.append("t.approval_status=%s")
            params.append(approval_status)
        if resource == "adjustments":
            changed_by_values = self._finance_values(query, "changed_by")
            if changed_by_values:
                conditions.append("COALESCE(NULLIF(BTRIM(t.changed_by),''),NULLIF(BTRIM(t.updated_by),''),NULLIF(BTRIM(t.created_by),''))=ANY(%s)")
                params.append(changed_by_values)
            for value, label in ((query.get("date_from"), "开始日期"), (query.get("date_to"), "结束日期")):
                normalized = normalize_name(value or "")
                if normalized:
                    self._finance_date(normalized, label)
                    conditions.append(f"(t.created_at AT TIME ZONE 'Asia/Shanghai')::date {'>=' if label == '开始日期' else '<='} %s")
                    params.append(normalized)
        if resource == "marketing-expenses":
            for value, label, operator in ((query.get("date_from"), "开始日期", ">="), (query.get("date_to"), "结束日期", "<=")):
                normalized = normalize_name(value or "")
                if normalized:
                    self._finance_date(normalized, label)
                    conditions.append(f"t.expense_date {operator} %s")
                    params.append(normalized)
        expense_types = self._finance_values(query, "expense_types", "expense_type")
        if expense_types and resource == "marketing-expenses":
            conditions.append(
                "(t.expense_type=ANY(%s) OR EXISTS ("
                "SELECT 1 FROM config.finance_marketing_expense_type et "
                "WHERE et.expense_type_code=ANY(%s) AND et.expense_type_name=t.expense_type))"
            )
            params.extend([expense_types, expense_types])
        keyword = normalize_name(query.get("keyword", ""))
        if keyword:
            keyword_columns = {
                "budgets": "COALESCE(t.remark,'')",
                "shop-plans": "CONCAT_WS(' ',d.platform_name,d.company_name,d.shop_name,d.shop_code,COALESCE(t.remark,''))",
                "recharges": "CONCAT_WS(' ',d.platform_name,d.company_name,d.shop_name,d.shop_code,COALESCE(t.document_no,''),COALESCE(t.remark,''))",
                "adjustments": "CONCAT_WS(' ',COALESCE(t.approval_no,''),COALESCE(t.reason,''),COALESCE(t.change_remark,''),COALESCE(t.changed_by,''),COALESCE(t.updated_by,''))",
                "marketing-expenses": "CONCAT_WS(' ',t.expense_type,COALESCE(t.counterparty,''),COALESCE(t.document_no,''),COALESCE(t.remark,''))",
            }
            conditions.append(f"{keyword_columns[resource]} ILIKE %s")
            params.append(f"%{keyword}%")
        where = " AND ".join(conditions)
        with self.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM {meta['table']} t {join} WHERE {where}", params)
            total = int(cursor.fetchone()["total"])
            cursor.execute(f"SELECT {select} FROM {meta['table']} t {join} WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s", [*params, page_size, (page - 1) * page_size])
            items = [dict(row) for row in cursor.fetchall()]
            operator_options = []
            if resource == "adjustments":
                cursor.execute("""SELECT DISTINCT COALESCE(NULLIF(BTRIM(changed_by),''),NULLIF(BTRIM(updated_by),''),NULLIF(BTRIM(created_by),'')) AS operator
                                  FROM config.finance_promotion_budget_adjustment
                                  WHERE deleted_at IS NULL AND approval_status='approved' AND COALESCE(NULLIF(BTRIM(changed_by),''),NULLIF(BTRIM(updated_by),''),NULLIF(BTRIM(created_by),'')) IS NOT NULL
                                  ORDER BY operator""")
                operator_options = [row["operator"] for row in cursor.fetchall()]
        return {"items": items, "operators": operator_options if resource == "adjustments" else [], "pagination": {"total": total, "page": page, "page_size": page_size}}

    def _finance_configuration_summary_full(self, query: dict) -> dict:
        month_text = normalize_name(query.get("budget_month", ""))
        selected_month = self._finance_date(month_text, "月份", month_start=True) if month_text else date(date.today().year, date.today().month, 1)
        month_start, next_month = self._finance_month_bounds(selected_month)
        with self.transaction() as cursor:
            shops = self._finance_shop_console_rows(cursor, selected_month)
            cursor.execute("SELECT * FROM config.finance_budget_monthly WHERE budget_month=%s", (selected_month,))
            budget_row = row_dict(cursor.fetchone())
            cursor.execute(
                """SELECT
                       COALESCE(SUM(CASE WHEN adjustment_amount > 0 THEN adjustment_amount ELSE 0 END),0)::numeric(18,2) AS approved_increase_amount,
                       COALESCE(SUM(CASE WHEN adjustment_amount < 0 THEN ABS(adjustment_amount) ELSE 0 END),0)::numeric(18,2) AS approved_decrease_amount,
                       COALESCE(SUM(adjustment_amount),0)::numeric(18,2) AS approved_adjustment_amount,
                       MAX(updated_at) AS adjustment_updated_at
                   FROM config.finance_promotion_budget_adjustment
                  WHERE budget_month=%s AND approval_status='approved' AND deleted_at IS NULL""",
                (selected_month,),
            )
            adjustment = row_dict(cursor.fetchone())
            cursor.execute(
                """SELECT COALESCE(SUM(expense_amount),0)::numeric(18,2) AS marketing_expense_amount,
                          MAX(updated_at) AS marketing_expense_updated_at
                     FROM config.finance_marketing_expense_detail
                    WHERE expense_date >= %s AND expense_date < %s AND deleted_at IS NULL""",
                (month_start, next_month),
            )
            expense = row_dict(cursor.fetchone())

        zero = Decimal("0.00")
        initial_promotion = Decimal(str(budget_row.get("promotion_budget_amount") or 0))
        adjustment_amount = Decimal(str(adjustment.get("approved_adjustment_amount") or 0))
        effective_promotion = (initial_promotion + adjustment_amount).quantize(Decimal("0.01"))
        gsv_target = Decimal(str(budget_row.get("gsv_target_amount") or 0))
        marketing_budget = Decimal(str(budget_row.get("marketing_budget_amount") or 0))
        marketing_expense = Decimal(str(expense.get("marketing_expense_amount") or 0))
        allocated = sum((Decimal(str(row.get("promotion_budget_amount") or 0)) for row in shops), zero)
        recharge = sum((Decimal(str(row.get("recharge_amount") or 0)) for row in shops), zero)
        actual_gsv = sum((Decimal(str(row.get("actual_gsv_amount") or 0)) for row in shops), zero)
        promotion_expense = sum((Decimal(str(row.get("promotion_expense_amount") or 0)) for row in shops), zero)
        shop_gsv_target = sum((Decimal(str(row.get("gsv_target_amount") or 0)) for row in shops), zero)

        def percentage(numerator: Decimal, denominator: Decimal) -> Decimal:
            if not denominator:
                return zero
            return (numerator * Decimal("100") / denominator).quantize(Decimal("0.01"))

        alerts: list[dict] = []
        enriched_shops: list[dict] = []
        for shop in shops:
            item = dict(shop)
            target = Decimal(str(item.get("gsv_target_amount") or 0))
            budget = Decimal(str(item.get("promotion_budget_amount") or 0))
            recharge_amount = Decimal(str(item.get("recharge_amount") or 0))
            actual = Decimal(str(item.get("actual_gsv_amount") or 0))
            spend = Decimal(str(item.get("promotion_expense_amount") or 0))
            item["gsv_completion_rate"] = percentage(actual, target)
            item["promotion_execution_rate"] = percentage(spend, budget)
            item["theoretical_account_balance"] = (recharge_amount - spend).quantize(Decimal("0.01"))
            enriched_shops.append(item)
            if Decimal(str(item.get("over_recharge_amount") or 0)) > 0:
                alerts.append({
                    "level": "danger", "resource": "recharges",
                    "title": f"{item['platform_name']} · {item['shop_name']} 超预算充值",
                    "description": f"已充值超过店铺预算 {Decimal(str(item['over_recharge_amount'])):,.2f} 元",
                })
            elif Decimal(str(item.get("pending_recharge_amount") or 0)) > 0:
                alerts.append({
                    "level": "warning", "resource": "recharges",
                    "title": f"{item['platform_name']} · {item['shop_name']} 待充值",
                    "description": f"当前待充值额度 {Decimal(str(item['pending_recharge_amount'])):,.2f} 元",
                })
            if item.get("target_is_set") and target > 0 and item["gsv_completion_rate"] < Decimal("80"):
                alerts.append({
                    "level": "info", "resource": "gsv-targets",
                    "title": f"{item['platform_name']} · {item['shop_name']} 目标进度待关注",
                    "description": f"当前 GSV 目标完成率 {item['gsv_completion_rate']:.1f}%",
                })

        global_row = {
            **budget_row,
            "budget_month": selected_month,
            "gsv_target_amount": gsv_target.quantize(Decimal("0.01")),
            "initial_promotion_budget_amount": initial_promotion.quantize(Decimal("0.01")),
            "approved_adjustment_amount": adjustment_amount.quantize(Decimal("0.01")),
            "approved_increase_amount": Decimal(str(adjustment.get("approved_increase_amount") or 0)),
            "approved_decrease_amount": Decimal(str(adjustment.get("approved_decrease_amount") or 0)),
            "effective_promotion_budget_amount": effective_promotion,
            "allocated_promotion_budget_amount": allocated.quantize(Decimal("0.01")),
            "unallocated_promotion_budget_amount": (effective_promotion - allocated).quantize(Decimal("0.01")),
            "recharge_amount": recharge.quantize(Decimal("0.01")),
            "pending_recharge_amount": (effective_promotion - recharge).quantize(Decimal("0.01")),
            "marketing_budget_amount": marketing_budget.quantize(Decimal("0.01")),
            "marketing_expense_amount": marketing_expense.quantize(Decimal("0.01")),
            "marketing_remaining_amount": (marketing_budget - marketing_expense).quantize(Decimal("0.01")),
        }
        actuals = {
            "budget_month": selected_month,
            "gsv_target_amount": gsv_target.quantize(Decimal("0.01")),
            "shop_gsv_target_amount": shop_gsv_target.quantize(Decimal("0.01")),
            "actual_gsv_amount": actual_gsv.quantize(Decimal("0.01")),
            "gsv_completion_rate": percentage(actual_gsv, gsv_target),
            "promotion_expense_amount": promotion_expense.quantize(Decimal("0.01")),
            "promotion_execution_rate": percentage(promotion_expense, effective_promotion),
            "marketing_execution_rate": percentage(marketing_expense, marketing_budget),
            "theoretical_account_balance": (recharge - promotion_expense).quantize(Decimal("0.01")),
            "approved_increase_amount": Decimal(str(adjustment.get("approved_increase_amount") or 0)),
            "approved_decrease_amount": Decimal(str(adjustment.get("approved_decrease_amount") or 0)),
            "shop_count": len(enriched_shops),
            "pending_recharge_shop_count": sum(1 for item in enriched_shops if Decimal(str(item.get("pending_recharge_amount") or 0)) > 0),
            "alert_count": len(alerts),
        }
        return {"global": global_row, "shops": enriched_shops, "actuals": actuals, "alerts": alerts}

    def finance_configuration_summary(self, query: dict) -> dict:
        return self._finance_configuration_summary_full(query)

    def _legacy_finance_configuration_summary(self, query: dict) -> dict:
        month = normalize_name(query.get("budget_month", ""))
        selected_month = self._finance_date(month, "月份", month_start=True) if month else None
        with self.transaction() as cursor:
            if selected_month:
                cursor.execute("SELECT * FROM ads.ads_finance_budget_global_monthly WHERE budget_month=%s", (selected_month,))
                global_row = row_dict(cursor.fetchone())
            else:
                cursor.execute("SELECT * FROM ads.ads_finance_budget_global_monthly ORDER BY budget_month DESC LIMIT 1")
                global_row = row_dict(cursor.fetchone())
            summary_month = selected_month or global_row.get("budget_month")
            if summary_month:
                cursor.execute(
                    "SELECT * FROM ads.ads_finance_promotion_budget_company_shop_monthly WHERE budget_month=%s ORDER BY platform_name,company_name,shop_name",
                    (summary_month,),
                )
            else:
                cursor.execute("SELECT * FROM ads.ads_finance_promotion_budget_company_shop_monthly WHERE FALSE")
            shops = [dict(row) for row in cursor.fetchall()]
            actual_rows: list[dict] = []
            approved_increase = Decimal("0")
            approved_decrease = Decimal("0")
            if summary_month:
                next_month = date(summary_month.year + (1 if summary_month.month == 12 else 0), 1 if summary_month.month == 12 else summary_month.month + 1, 1)
                cursor.execute(
                    """WITH gsv AS (
                           SELECT platform_code,company_code,shop_code,SUM(gsv_amount)::numeric(18,2) AS actual_gsv_amount
                           FROM ads.ads_gsv_company_daily
                           WHERE stat_date >= %s AND stat_date < %s
                           GROUP BY platform_code,company_code,shop_code
                       ), promotion AS (
                           SELECT platform_code,company_code,shop_code,SUM(promotion_expense_amount)::numeric(18,2) AS promotion_expense_amount
                           FROM ads.ads_promotion_expense_company_shop_daily
                           WHERE stat_date >= %s AND stat_date < %s
                           GROUP BY platform_code,company_code,shop_code
                       )
                       SELECT COALESCE(gsv.platform_code,promotion.platform_code) AS platform_code,
                              COALESCE(gsv.company_code,promotion.company_code) AS company_code,
                              COALESCE(gsv.shop_code,promotion.shop_code) AS shop_code,
                              COALESCE(gsv.actual_gsv_amount,0)::numeric(18,2) AS actual_gsv_amount,
                              COALESCE(promotion.promotion_expense_amount,0)::numeric(18,2) AS promotion_expense_amount
                       FROM gsv FULL JOIN promotion
                         ON promotion.platform_code=gsv.platform_code
                        AND promotion.company_code=gsv.company_code
                        AND promotion.shop_code=gsv.shop_code""",
                    (summary_month, next_month, summary_month, next_month),
                )
                actual_rows = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    """SELECT
                           COALESCE(SUM(CASE WHEN adjustment_amount > 0 THEN adjustment_amount ELSE 0 END),0)::numeric(18,2) AS approved_increase_amount,
                           COALESCE(SUM(CASE WHEN adjustment_amount < 0 THEN ABS(adjustment_amount) ELSE 0 END),0)::numeric(18,2) AS approved_decrease_amount
                       FROM config.finance_promotion_budget_adjustment
                       WHERE budget_month=%s AND approval_status='approved' AND deleted_at IS NULL""",
                    (summary_month,),
                )
                adjustment = row_dict(cursor.fetchone())
                approved_increase = adjustment.get("approved_increase_amount") or Decimal("0")
                approved_decrease = adjustment.get("approved_decrease_amount") or Decimal("0")

        actual_lookup = {
            (row["platform_code"], row["company_code"], row["shop_code"]): row
            for row in actual_rows
        }
        enriched_shops: list[dict] = []
        alerts: list[dict] = []

        def percentage(numerator: Decimal, denominator: Decimal) -> Decimal:
            if not denominator:
                return Decimal("0.00")
            return (numerator * Decimal("100") / denominator).quantize(Decimal("0.01"))

        for shop in shops:
            actual = actual_lookup.get((shop["platform_code"], shop["company_code"], shop["shop_code"]), {})
            actual_gsv = Decimal(str(actual.get("actual_gsv_amount") or 0))
            promotion_expense = Decimal(str(actual.get("promotion_expense_amount") or 0))
            target = Decimal(str(shop.get("gsv_target_amount") or 0))
            recharge = Decimal(str(shop.get("recharge_amount") or 0))
            effective_shop_budget = Decimal(str(shop.get("promotion_budget_amount") or 0))
            enriched = {
                **shop,
                "actual_gsv_amount": actual_gsv,
                "gsv_completion_rate": percentage(actual_gsv, target),
                "promotion_expense_amount": promotion_expense,
                "promotion_execution_rate": percentage(promotion_expense, effective_shop_budget),
                "theoretical_account_balance": (recharge - promotion_expense).quantize(Decimal("0.01")),
            }
            enriched_shops.append(enriched)
            if Decimal(str(shop.get("over_recharge_amount") or 0)) > 0:
                alerts.append({
                    "level": "danger", "resource": "recharges",
                    "title": f"{shop['platform_name']} · {shop['shop_name']} 超预算充值",
                    "description": f"已充值超过店铺预算 {Decimal(str(shop['over_recharge_amount'])):,.2f} 元",
                })
            elif Decimal(str(shop.get("pending_recharge_amount") or 0)) > 0:
                alerts.append({
                    "level": "warning", "resource": "recharges",
                    "title": f"{shop['platform_name']} · {shop['shop_name']} 待充值",
                    "description": f"当前待充值额度 {Decimal(str(shop['pending_recharge_amount'])):,.2f} 元",
                })
            if target > 0 and enriched["gsv_completion_rate"] < Decimal("80"):
                alerts.append({
                    "level": "info", "resource": "shop-plans",
                    "title": f"{shop['platform_name']} · {shop['shop_name']} 目标进度待关注",
                    "description": f"当前 GSV 目标完成率 {enriched['gsv_completion_rate']:.1f}%",
                })

        total_gsv = sum((Decimal(str(row.get("actual_gsv_amount") or 0)) for row in actual_rows), Decimal("0"))
        total_promotion_expense = sum((Decimal(str(row.get("promotion_expense_amount") or 0)) for row in actual_rows), Decimal("0"))
        shop_gsv_target = sum((Decimal(str(row.get("gsv_target_amount") or 0)) for row in shops), Decimal("0"))
        total_gsv_target = Decimal(str(global_row.get("gsv_target_amount") or 0))
        effective_budget = Decimal(str(global_row.get("effective_promotion_budget_amount") or 0))
        recharge_amount = Decimal(str(global_row.get("recharge_amount") or 0))
        marketing_budget = Decimal(str(global_row.get("marketing_budget_amount") or 0))
        marketing_expense = Decimal(str(global_row.get("marketing_expense_amount") or 0))
        actuals = {
            "budget_month": summary_month,
            "gsv_target_amount": total_gsv_target.quantize(Decimal("0.01")),
            "shop_gsv_target_amount": shop_gsv_target.quantize(Decimal("0.01")),
            "actual_gsv_amount": total_gsv.quantize(Decimal("0.01")),
            "gsv_completion_rate": percentage(total_gsv, total_gsv_target),
            "promotion_expense_amount": total_promotion_expense.quantize(Decimal("0.01")),
            "promotion_execution_rate": percentage(total_promotion_expense, effective_budget),
            "marketing_execution_rate": percentage(marketing_expense, marketing_budget),
            "theoretical_account_balance": (recharge_amount - total_promotion_expense).quantize(Decimal("0.01")),
            "approved_increase_amount": approved_increase,
            "approved_decrease_amount": approved_decrease,
            "shop_count": len(enriched_shops),
            "pending_recharge_shop_count": sum(1 for shop in shops if Decimal(str(shop.get("pending_recharge_amount") or 0)) > 0),
            "alert_count": len(alerts),
        }
        return {"global": global_row, "shops": enriched_shops, "actuals": actuals, "alerts": alerts}

    def _validate_finance_shop(
        self,
        cursor,
        shop_code: str,
        business_date: date,
        platform_code: str | None = None,
        company_code: str | None = None,
    ) -> dict:
        conditions = [
            "shop_code=%s", "(is_active OR %s < DATE_TRUNC('month', CURRENT_DATE)::date)",
            "valid_from<=%s", "(valid_to IS NULL OR valid_to>=%s)",
        ]
        params: list[Any] = [shop_code, business_date, business_date, business_date]
        if platform_code:
            conditions.append("platform_code=%s")
            params.append(platform_code)
        if company_code:
            conditions.append("company_code=%s")
            params.append(company_code)
        cursor.execute(
            f"SELECT platform_code,platform_name,company_code,company_name,shop_code,shop_name,shop_company_sk "
            f"FROM dim.dim_platform_shop_company WHERE {' AND '.join(conditions)}",
            params,
        )
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise ConflictError("平台、公司、店铺在业务日期必须且只能匹配一条有效DIM")
        return dict(rows[0])

    def save_finance_configuration(self, resource: str, payload: dict, operator: str, ip_address: str | None, record_id: str | None = None) -> dict:
        if resource == "adjustments":
            raise ValueError("预算调整记录由总预算修改自动生成，不支持直接新增、审批或覆盖")
        if resource == "expense-types":
            return self.save_finance_expense_type(payload, operator, ip_address, record_id)
        if resource not in {"budgets", "shop-plans", "gsv-targets", "shop-budgets", "recharges", "marketing-expenses"}:
            raise NotFoundError("经营配置类型不存在")

        expected_updated_at = payload.get("updated_at") or None
        note = normalize_name(payload.get("remark", ""))[:500] or None
        permission_action = normalize_name(payload.get("permission_action", "")) or None
        with self.transaction() as cursor:
            if resource == "budgets":
                if permission_action not in {None, "gsv_total", "promotion_total", "marketing_budget"}:
                    raise ValueError("月度总控操作无效")
                month = self._finance_date(payload.get("budget_month"), "预算月份", month_start=True)
                requested_gsv = self._finance_amount(payload.get("gsv_target_amount"), "GSV总目标", nonnegative=True)
                requested_promotion = self._finance_amount(payload.get("promotion_budget_amount"), "推广预算", nonnegative=True)
                requested_marketing = self._finance_amount(payload.get("marketing_budget_amount"), "营销预算", nonnegative=True)
                cursor.execute(
                    """SELECT * FROM config.finance_budget_monthly
                       WHERE budget_month=%s FOR UPDATE""",
                    (month,),
                )
                current = cursor.fetchone()
                current_row = dict(current) if current else {}
                base_promotion = Decimal(str(current_row.get("promotion_budget_amount") or 0))
                current_marketing = Decimal(str(current_row.get("marketing_budget_amount") or 0))
                current_gsv = Decimal(str(current_row.get("gsv_target_amount") or 0))
                promotion_initialized_at = current_row.get("promotion_budget_initialized_at")
                marketing_initialized_at = current_row.get("marketing_budget_initialized_at")
                if current:
                    cursor.execute(
                        """SELECT COALESCE(SUM(adjustment_amount),0)::numeric(18,2) AS amount
                             FROM config.finance_promotion_budget_adjustment
                            WHERE budget_month=%s AND approval_status='approved' AND deleted_at IS NULL""",
                        (month,),
                    )
                    prior_adjustment = Decimal(str(cursor.fetchone()["amount"] or 0))
                else:
                    prior_adjustment = Decimal("0")

                touches_gsv = permission_action in {None, "gsv_total"}
                touches_promotion = permission_action in {None, "promotion_total"}
                touches_marketing = permission_action in {None, "marketing_budget"}
                gsv_target = requested_gsv if touches_gsv else current_gsv
                marketing_budget = requested_marketing if touches_marketing else current_marketing
                budget_remark = note if note is not None else current_row.get("remark")
                initial_time = datetime.now(timezone.utc)

                if touches_promotion:
                    if not current or promotion_initialized_at is None:
                        base_promotion = requested_promotion
                        promotion_initialized_at = initial_time
                    else:
                        before_amount = (base_promotion + prior_adjustment).quantize(Decimal("0.01"))
                        if requested_promotion != before_amount:
                            if not note:
                                raise ValueError("本月推广总预算已设置，再次修改必须填写备注")
                            delta = (requested_promotion - before_amount).quantize(Decimal("0.01"))
                            cursor.execute(
                                """INSERT INTO config.finance_promotion_budget_adjustment(
                                    budget_month,adjustment_date,adjustment_amount,approval_no,reason,approval_status,
                                    before_amount,after_amount,change_remark,changed_by,change_type,created_by,updated_by
                                ) VALUES(%s,%s,%s,NULL,%s,'approved',%s,%s,%s,%s,'budget_update',%s,%s)
                                RETURNING adjustment_id""",
                                (month, date.today(), delta, note, before_amount, requested_promotion, note, operator, operator, operator),
                            )
                        base_promotion = current_row["promotion_budget_amount"]

                if touches_marketing:
                    if not current or marketing_initialized_at is None:
                        marketing_initialized_at = initial_time
                    elif requested_marketing != current_marketing:
                        if not note:
                            raise ValueError("本月营销预算已设置，再次修改必须填写备注")
                        cursor.execute(
                            """INSERT INTO config.finance_marketing_budget_change_history(
                                budget_month,before_amount,after_amount,change_amount,changed_at,changed_by,remark
                            ) VALUES(%s,%s,%s,%s,NOW(),%s,%s)""",
                            (month, current_marketing, requested_marketing, requested_marketing - current_marketing, operator, note),
                        )

                cursor.execute(
                    """INSERT INTO config.finance_budget_monthly(
                        budget_month,gsv_target_amount,promotion_budget_amount,marketing_budget_amount,remark,
                        promotion_budget_initialized_at,marketing_budget_initialized_at,created_by,updated_by
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(budget_month) DO UPDATE SET
                        gsv_target_amount=EXCLUDED.gsv_target_amount,
                        promotion_budget_amount=EXCLUDED.promotion_budget_amount,
                        marketing_budget_amount=EXCLUDED.marketing_budget_amount,
                        remark=EXCLUDED.remark,
                        promotion_budget_initialized_at=EXCLUDED.promotion_budget_initialized_at,
                        marketing_budget_initialized_at=EXCLUDED.marketing_budget_initialized_at,
                        updated_by=EXCLUDED.updated_by
                    WHERE %s::timestamptz IS NULL OR config.finance_budget_monthly.updated_at=%s::timestamptz
                    RETURNING *""",
                    (
                        month, gsv_target, base_promotion, marketing_budget, budget_remark,
                        promotion_initialized_at, marketing_initialized_at, operator, operator,
                        expected_updated_at, expected_updated_at,
                    ),
                )
                row = cursor.fetchone()
                if not row:
                    raise ConflictError("记录不存在、已被删除或已被他人修改，请刷新页面")
                result = dict(row)
                target_key = str(result["budget_month"])

            elif resource in {"shop-plans", "gsv-targets", "shop-budgets"}:
                if permission_action not in {None, "gsv_detail", "shop_budget"}:
                    raise ValueError("店铺配置操作无效")
                month = self._finance_date(payload.get("budget_month"), "预算月份", month_start=True)
                shop_code = normalize_name(payload.get("shop_code", ""))
                platform_code = normalize_name(payload.get("platform_code", "")) or None
                company_code = normalize_name(payload.get("company_code", "")) or None
                self._validate_finance_shop(cursor, shop_code, self._finance_dim_date(month), platform_code, company_code)
                requested_promotion = self._finance_amount(payload.get("promotion_budget_amount"), "店铺推广预算", nonnegative=True)
                requested_gsv = self._finance_amount(payload.get("gsv_target_amount"), "GSV目标", nonnegative=True)
                if record_id:
                    cursor.execute(
                        """SELECT * FROM config.finance_shop_plan_monthly
                           WHERE shop_plan_id=%s AND deleted_at IS NULL FOR UPDATE""",
                        (int(record_id),),
                    )
                else:
                    cursor.execute(
                        """SELECT * FROM config.finance_shop_plan_monthly
                           WHERE budget_month=%s AND shop_code=%s AND deleted_at IS NULL FOR UPDATE""",
                        (month, shop_code),
                    )
                current = cursor.fetchone()
                if current and current["shop_code"] != shop_code:
                    raise ConflictError("不能把店铺配置改绑到其他DIM店铺")
                current_row = dict(current) if current else {}
                promotion = requested_promotion if permission_action in {None, "shop_budget"} else Decimal(str(current_row.get("promotion_budget_amount") or 0))
                gsv_target = requested_gsv if permission_action in {None, "gsv_detail"} else Decimal(str(current_row.get("gsv_target_amount") or 0))
                plan_remark = note if note is not None else current_row.get("remark")
                if current:
                    cursor.execute(
                        """UPDATE config.finance_shop_plan_monthly
                            SET budget_month=%s,shop_code=%s,promotion_budget_amount=%s,gsv_target_amount=%s,
                                remark=%s,updated_by=%s
                          WHERE shop_plan_id=%s AND deleted_at IS NULL
                            AND (%s::timestamptz IS NULL OR updated_at=%s::timestamptz)
                        RETURNING *""",
                        (month, shop_code, promotion, gsv_target, plan_remark, operator, current_row["shop_plan_id"], expected_updated_at, expected_updated_at),
                    )
                else:
                    cursor.execute(
                        """INSERT INTO config.finance_shop_plan_monthly(
                            budget_month,shop_code,promotion_budget_amount,gsv_target_amount,remark,created_by,updated_by
                        ) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (month, shop_code, promotion, gsv_target, plan_remark, operator, operator),
                    )
                row = cursor.fetchone()
                if not row:
                    raise ConflictError("记录不存在、已被删除或已被他人修改，请刷新页面")
                result = dict(row)
                target_key = str(result["shop_plan_id"])
                resource = "shop-plans"

            elif resource == "recharges":
                if permission_action != "promotion_recharge":
                    raise ValueError("充值流水操作无效")
                business_date = self._finance_date(payload.get("recharge_date"), "充值日期")
                shop_code = normalize_name(payload.get("shop_code", ""))
                self._validate_finance_shop(
                    cursor, shop_code, business_date,
                    normalize_name(payload.get("platform_code", "")) or None,
                    normalize_name(payload.get("company_code", "")) or None,
                )
                values = (
                    business_date, shop_code,
                    self._finance_amount(payload.get("recharge_amount"), "充值金额", positive=True),
                    normalize_name(payload.get("document_no", ""))[:100] or None,
                    note,
                )
                if record_id:
                    cursor.execute(
                        """UPDATE config.finance_promotion_recharge_detail
                            SET recharge_date=%s,shop_code=%s,recharge_amount=%s,document_no=%s,remark=%s,updated_by=%s
                          WHERE recharge_id=%s AND deleted_at IS NULL
                            AND (%s::timestamptz IS NULL OR updated_at=%s::timestamptz)
                        RETURNING *""",
                        (*values, operator, int(record_id), expected_updated_at, expected_updated_at),
                    )
                else:
                    cursor.execute(
                        """INSERT INTO config.finance_promotion_recharge_detail(
                            recharge_date,shop_code,recharge_amount,document_no,remark,created_by,updated_by
                        ) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (*values, operator, operator),
                    )
                row = cursor.fetchone()
                if not row:
                    raise ConflictError("记录不存在、已被删除或已被他人修改，请刷新页面")
                result = dict(row)
                target_key = str(result["recharge_id"])

            else:
                if permission_action != "marketing_expense":
                    raise ValueError("营销费用操作无效")
                expense_date = self._finance_date(payload.get("expense_date"), "费用日期")
                expense_amount = self._finance_amount(payload.get("expense_amount"), "营销费用", positive=True)
                expense_type_input = normalize_name(payload.get("expense_type", ""))[:100]
                if not expense_type_input:
                    raise ValueError("营销费用类型不能为空")
                existing_expense = None
                if record_id:
                    cursor.execute(
                        """SELECT * FROM config.finance_marketing_expense_detail
                           WHERE marketing_expense_id=%s AND deleted_at IS NULL FOR UPDATE""",
                        (int(record_id),),
                    )
                    existing_expense = cursor.fetchone()
                cursor.execute(
                    """SELECT expense_type_code,expense_type_name,is_active
                         FROM config.finance_marketing_expense_type
                        WHERE expense_type_code=%s OR expense_type_name=%s
                        LIMIT 1""",
                    (expense_type_input, expense_type_input),
                )
                expense_type = cursor.fetchone()
                if not expense_type:
                    raise ConflictError("费用类型不存在或已停用，请先在营销费用类型管理中维护")
                if not expense_type["is_active"]:
                    raise ConflictError("费用类型不存在或已停用，请选择启用中的费用类型")
                canonical_type = expense_type["expense_type_name"]
                values = (
                    expense_date, expense_amount, canonical_type,
                    normalize_name(payload.get("counterparty", ""))[:255] or None,
                    normalize_name(payload.get("document_no", ""))[:100] or None,
                    note,
                )
                if existing_expense:
                    cursor.execute(
                        """UPDATE config.finance_marketing_expense_detail
                            SET expense_date=%s,expense_amount=%s,expense_type=%s,counterparty=%s,document_no=%s,remark=%s,updated_by=%s
                          WHERE marketing_expense_id=%s AND deleted_at IS NULL
                            AND (%s::timestamptz IS NULL OR updated_at=%s::timestamptz)
                        RETURNING *""",
                        (*values, operator, int(record_id), expected_updated_at, expected_updated_at),
                    )
                else:
                    cursor.execute(
                        """INSERT INTO config.finance_marketing_expense_detail(
                            expense_date,expense_amount,expense_type,counterparty,document_no,remark,created_by,updated_by
                        ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (*values, operator, operator),
                    )
                row = cursor.fetchone()
                if not row:
                    raise ConflictError("记录不存在、已被删除或已被他人修改，请刷新页面")
                result = dict(row)
                target_key = str(result["marketing_expense_id"])
                resource = "marketing-expenses"

            if resource != "expense-types":
                self._refresh_finance_configuration(cursor)
            self._write_log(
                cursor, "finance_config_save", resource, target_key, operator, ip_address,
                "保存经营配置", {"resource": resource, "record_id": target_key},
            )
        return result

    def save_finance_expense_type(
        self, payload: dict, operator: str, ip_address: str | None, record_id: str | None = None,
    ) -> dict:
        name = normalize_name(payload.get("expense_type_name", payload.get("name", "")))[:100]
        if not name:
            raise ValueError("费用类型名称不能为空")
        remark = normalize_name(payload.get("remark", ""))[:500] or None
        raw_active = payload.get("is_active", True)
        is_active = raw_active if isinstance(raw_active, bool) else str(raw_active).lower() == "true"
        expected_updated_at = payload.get("updated_at") or None
        with self.transaction() as cursor:
            current = None
            if record_id:
                if str(record_id).isdigit():
                    cursor.execute("SELECT * FROM config.finance_marketing_expense_type WHERE expense_type_id=%s FOR UPDATE", (int(record_id),))
                else:
                    cursor.execute("SELECT * FROM config.finance_marketing_expense_type WHERE expense_type_code=%s FOR UPDATE", (str(record_id),))
                current = cursor.fetchone()
                if not current:
                    raise NotFoundError("营销费用类型不存在")
            cursor.execute(
                """SELECT expense_type_id FROM config.finance_marketing_expense_type
                   WHERE expense_type_name=%s AND (%s::bigint IS NULL OR expense_type_id<>%s)""",
                (name, current["expense_type_id"] if current else None, current["expense_type_id"] if current else None),
            )
            if cursor.fetchone():
                raise ConflictError("营销费用类型名称已存在")
            code = current["expense_type_code"] if current else normalize_name(payload.get("expense_type_code", ""))[:64]
            if not code:
                code = f"marketing_{uuid.uuid4().hex[:20]}"
            if current:
                cursor.execute(
                    """UPDATE config.finance_marketing_expense_type
                        SET expense_type_name=%s,remark=%s,is_active=%s,updated_by=%s
                      WHERE expense_type_id=%s
                        AND (%s::timestamptz IS NULL OR updated_at=%s::timestamptz)
                    RETURNING *""",
                    (name, remark, is_active, operator, current["expense_type_id"], expected_updated_at, expected_updated_at),
                )
            else:
                cursor.execute(
                    """INSERT INTO config.finance_marketing_expense_type(
                        expense_type_code,expense_type_name,remark,is_active,created_by,updated_by
                    ) VALUES(%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (code, name, remark, is_active, operator, operator),
                )
            row = cursor.fetchone()
            if not row:
                raise ConflictError("记录不存在、已被删除或已被他人修改，请刷新页面")
            result = dict(row)
            self._write_log(
                cursor, "finance_expense_type_save", "finance_expense_type", str(result["expense_type_id"]),
                operator, ip_address, "维护营销费用类型", {"expense_type_code": result["expense_type_code"]},
            )
        return result

    def _legacy_save_finance_configuration(self, resource: str, payload: dict, operator: str, ip_address: str | None, record_id: str | None = None) -> dict:
        meta = self._finance_resource(resource)
        expected_updated_at = payload.get("updated_at")
        note = normalize_name(payload.get("remark", ""))[:500] or None
        permission_action = normalize_name(payload.get("permission_action", "")) or None
        with self.transaction() as cursor:
            if resource == "budgets":
                month = self._finance_date(payload.get("budget_month"), "预算月份", month_start=True)
                gsv_target = self._finance_amount(payload.get("gsv_target_amount"), "GSV总目标", nonnegative=True)
                promotion = self._finance_amount(payload.get("promotion_budget_amount"), "推广预算", nonnegative=True)
                marketing = self._finance_amount(payload.get("marketing_budget_amount"), "营销预算", nonnegative=True)
                if permission_action:
                    cursor.execute(
                        """SELECT gsv_target_amount,promotion_budget_amount,marketing_budget_amount
                           FROM config.finance_budget_monthly
                          WHERE budget_month=%s
                          FOR UPDATE""",
                        (month,),
                    )
                    current = cursor.fetchone()
                    if current:
                        if permission_action != "gsv_total":
                            gsv_target = current["gsv_target_amount"]
                        if permission_action != "promotion_total":
                            promotion = current["promotion_budget_amount"]
                        if permission_action != "marketing_budget":
                            marketing = current["marketing_budget_amount"]
                    else:
                        if permission_action != "gsv_total":
                            gsv_target = 0
                        if permission_action != "promotion_total":
                            promotion = 0
                        if permission_action != "marketing_budget":
                            marketing = 0
                cursor.execute(
                    """INSERT INTO config.finance_budget_monthly(budget_month,gsv_target_amount,promotion_budget_amount,marketing_budget_amount,remark,created_by,updated_by)
                       VALUES(%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(budget_month) DO UPDATE SET gsv_target_amount=EXCLUDED.gsv_target_amount,promotion_budget_amount=EXCLUDED.promotion_budget_amount,
                         marketing_budget_amount=EXCLUDED.marketing_budget_amount,remark=EXCLUDED.remark,updated_by=EXCLUDED.updated_by
                       WHERE %s::timestamptz IS NULL OR finance_budget_monthly.updated_at=%s::timestamptz RETURNING *""",
                    (month, gsv_target, promotion, marketing, note, operator, operator, expected_updated_at, expected_updated_at),
                )
            elif resource == "shop-plans":
                month = self._finance_date(payload.get("budget_month"), "预算月份", month_start=True)
                shop_code = normalize_name(payload.get("shop_code", ""))
                self._validate_finance_shop(cursor, shop_code, month)
                promotion = self._finance_amount(payload.get("promotion_budget_amount"), "店铺推广预算", nonnegative=True)
                gsv_target = self._finance_amount(payload.get("gsv_target_amount"), "GSV目标", nonnegative=True)
                if permission_action:
                    if record_id:
                        cursor.execute(
                            """SELECT promotion_budget_amount,gsv_target_amount
                               FROM config.finance_shop_plan_monthly
                              WHERE shop_plan_id=%s AND deleted_at IS NULL
                              FOR UPDATE""",
                            (int(record_id),),
                        )
                    else:
                        cursor.execute(
                            """SELECT promotion_budget_amount,gsv_target_amount
                               FROM config.finance_shop_plan_monthly
                              WHERE budget_month=%s AND shop_code=%s AND deleted_at IS NULL
                              FOR UPDATE""",
                            (month, shop_code),
                        )
                    current = cursor.fetchone()
                    if permission_action == "gsv_detail":
                        promotion = current["promotion_budget_amount"] if current else 0
                    elif permission_action == "promotion_detail":
                        gsv_target = current["gsv_target_amount"] if current else 0
                values = (month, shop_code, promotion, gsv_target, note, operator, operator)
                if record_id:
                    cursor.execute("""UPDATE config.finance_shop_plan_monthly SET budget_month=%s,shop_code=%s,promotion_budget_amount=%s,gsv_target_amount=%s,remark=%s,updated_by=%s WHERE shop_plan_id=%s AND deleted_at IS NULL AND (%s::timestamptz IS NULL OR updated_at=%s::timestamptz) RETURNING *""", (*values[:5], operator, int(record_id), expected_updated_at, expected_updated_at))
                else:
                    cursor.execute("""INSERT INTO config.finance_shop_plan_monthly(budget_month,shop_code,promotion_budget_amount,gsv_target_amount,remark,created_by,updated_by) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""", values)
            elif resource == "recharges":
                business_date = self._finance_date(payload.get("recharge_date"), "充值日期")
                shop_code = normalize_name(payload.get("shop_code", ""))
                self._validate_finance_shop(cursor, shop_code, business_date)
                values = (business_date, shop_code, self._finance_amount(payload.get("recharge_amount"), "充值金额", positive=True), normalize_name(payload.get("document_no", ""))[:100] or None, note)
                if record_id:
                    cursor.execute("""UPDATE config.finance_promotion_recharge_detail SET recharge_date=%s,shop_code=%s,recharge_amount=%s,document_no=%s,remark=%s,updated_by=%s WHERE recharge_id=%s AND deleted_at IS NULL AND (%s::timestamptz IS NULL OR updated_at=%s::timestamptz) RETURNING *""", (*values, operator, int(record_id), expected_updated_at, expected_updated_at))
                else:
                    cursor.execute("""INSERT INTO config.finance_promotion_recharge_detail(recharge_date,shop_code,recharge_amount,document_no,remark,created_by,updated_by) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""", (*values, operator, operator))
            elif resource == "adjustments":
                month = self._finance_date(payload.get("budget_month"), "预算月份", month_start=True)
                adjustment_date = self._finance_date(payload.get("adjustment_date"), "调整日期")
                amount = self._finance_amount(payload.get("adjustment_amount"), "调整金额")
                if amount == 0: raise ValueError("调整金额不能为0")
                status = normalize_name(payload.get("approval_status", "approved"))
                if status not in {"pending", "approved", "rejected"}: raise ValueError("审批状态无效")
                values = (month, adjustment_date, amount, normalize_name(payload.get("approval_no", ""))[:100] or None, normalize_name(payload.get("reason", ""))[:500], status)
                if not values[4]: raise ValueError("调整原因不能为空")
                if record_id:
                    cursor.execute("""UPDATE config.finance_promotion_budget_adjustment SET budget_month=%s,adjustment_date=%s,adjustment_amount=%s,approval_no=%s,reason=%s,approval_status=%s,updated_by=%s WHERE adjustment_id=%s AND deleted_at IS NULL AND (%s::timestamptz IS NULL OR updated_at=%s::timestamptz) RETURNING *""", (*values, operator, int(record_id), expected_updated_at, expected_updated_at))
                else:
                    cursor.execute("""INSERT INTO config.finance_promotion_budget_adjustment(budget_month,adjustment_date,adjustment_amount,approval_no,reason,approval_status,created_by,updated_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""", (*values, operator, operator))
            else:
                expense_date = self._finance_date(payload.get("expense_date"), "费用日期")
                values = (expense_date, self._finance_amount(payload.get("expense_amount"), "营销费用", positive=True), normalize_name(payload.get("expense_type", ""))[:100], normalize_name(payload.get("counterparty", ""))[:255] or None, normalize_name(payload.get("document_no", ""))[:100] or None, note)
                if not values[2]: raise ValueError("营销费用类型不能为空")
                if record_id:
                    cursor.execute("""UPDATE config.finance_marketing_expense_detail SET expense_date=%s,expense_amount=%s,expense_type=%s,counterparty=%s,document_no=%s,remark=%s,updated_by=%s WHERE marketing_expense_id=%s AND deleted_at IS NULL AND (%s::timestamptz IS NULL OR updated_at=%s::timestamptz) RETURNING *""", (*values, operator, int(record_id), expected_updated_at, expected_updated_at))
                else:
                    cursor.execute("""INSERT INTO config.finance_marketing_expense_detail(expense_date,expense_amount,expense_type,counterparty,document_no,remark,created_by,updated_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""", (*values, operator, operator))
            row = cursor.fetchone()
            if not row: raise ConflictError("记录不存在、已被删除或已被他人修改，请刷新页面")
            result = dict(row)
            self._refresh_finance_configuration(cursor)
            self._write_log(cursor, "finance_config_save", resource, str(result[meta["pk"]]), operator, ip_address, "保存经营预算配置", {"resource": resource, "record_id": str(result[meta["pk"]])})
        return result

    def delete_finance_configuration(self, resource: str, record_id: str, operator: str, ip_address: str | None) -> dict:
        meta = self._finance_resource(resource)
        if resource == "expense-types":
            with self.transaction() as cursor:
                cursor.execute(
                    f"DELETE FROM {meta['table']} WHERE {meta['pk']}=%s RETURNING {meta['pk']},expense_type_code,expense_type_name",
                    (int(record_id),),
                )
                row = cursor.fetchone()
                if not row:
                    raise NotFoundError("营销费用类型不存在")
                self._write_log(
                    cursor, "finance_expense_type_delete", "finance_expense_type", record_id,
                    operator, ip_address, "删除营销费用类型",
                    {"expense_type_code": row["expense_type_code"], "expense_type_name": row["expense_type_name"]},
                )
            return {"deleted": True, "id": record_id}
        if not meta["soft"]:
            raise ValueError("月度总控不能删除，可将金额调整为0")
        with self.transaction() as cursor:
            cursor.execute(f"UPDATE {meta['table']} SET deleted_at=NOW(),deleted_by=%s,updated_by=%s WHERE {meta['pk']}=%s AND deleted_at IS NULL RETURNING {meta['pk']}", (operator, operator, int(record_id)))
            row = cursor.fetchone()
            if not row: raise NotFoundError("经营配置记录不存在")
            self._refresh_finance_configuration(cursor)
            self._write_log(cursor, "finance_config_delete", resource, record_id, operator, ip_address, "删除经营预算配置", None)
        return {"deleted": True, "id": record_id}

    def list_fee_categories(self, query: dict | None = None) -> dict:
        query = query or {}
        with self.transaction() as cursor:
            cursor.execute(
                """
                SELECT c.platform_code,c.primary_category_code,c.primary_category_name,c.display_order,
                       c.classification_note,c.is_active,c.created_by,c.updated_by,
                       c.created_at,c.updated_at,
                       COUNT(m.mapping_id) AS mapping_count,
                       COUNT(m.mapping_id) FILTER (WHERE m.is_active) AS active_mapping_count,
                       COUNT(m.mapping_id) FILTER (WHERE m.operating_treatment='expense') AS included_mapping_count,
                       COALESCE(ARRAY_AGG(DISTINCT m.platform_name ORDER BY m.platform_name)
                           FILTER (WHERE m.platform_name IS NOT NULL), ARRAY[]::text[]) AS platforms,
                       COALESCE(ARRAY_AGG(DISTINCT m.platform_code ORDER BY m.platform_code)
                           FILTER (WHERE m.platform_code IS NOT NULL), ARRAY[]::text[]) AS platform_codes,
                       COUNT(*) OVER (PARTITION BY c.primary_category_name) AS same_name_code_count
                 FROM dim.dim_platform_fee_primary_category c
                 LEFT JOIN dim.dim_platform_fee_mapping m
                   ON m.primary_category_code=c.primary_category_code
                  AND m.primary_category_name=c.primary_category_name
                  AND m.alias_of_mapping_id IS NULL
                 GROUP BY c.primary_category_code,c.platform_code
                ORDER BY c.display_order,c.primary_category_name,c.primary_category_code
                """
            )
            items = [dict(row) for row in cursor.fetchall()]
        platform_names = {item.platform_code: item.platform_name for item in ACTIVE_REPORTS}
        for item in items:
            owner_code = normalize_name(item.get("platform_code", "")).lower()
            platform_codes = [
                normalize_name(code).lower()
                for code in (item.get("platform_codes") or [])
                if normalize_name(code)
            ]
            # 有实际映射时，以映射记录的平台为准。分类创建时尚未有映射，
            # 才使用分类创建时选择的平台，避免同一编码被跨平台复用时误显示平台。
            if not platform_codes and owner_code:
                platform_codes = [owner_code]
            item["platform_codes"] = platform_codes
            platform_labels = list(item.get("platforms") or [])
            owner_name = platform_names.get(owner_code)
            if not platform_labels and owner_name:
                platform_labels = [owner_name]
            item["platforms"] = platform_labels
        status = query.get("status")
        platform = normalize_name(query.get("platform_code", "")).lower()
        keyword = normalize_name(query.get("keyword", "")).casefold()
        if status in {"active", "inactive"}:
            expected = status == "active"
            items = [item for item in items if bool(item["is_active"]) is expected]
        if platform:
            items = [item for item in items if platform in item.get("platform_codes", [])]
        if keyword:
            items = [
                item for item in items
                if keyword in " ".join(
                    str(item.get(key) or "")
                    for key in ("platform_code", "primary_category_code", "primary_category_name", "classification_note", "platforms")
                ).casefold()
            ]
        return {"items": items, "total": len(items)}

    def create_fee_category(self, payload: dict, operator: str, ip_address: str | None) -> dict:
        platform_code = normalize_name(payload.get("platform_code", "")).lower()
        name = normalize_name(payload.get("primary_category_name", ""))
        note = normalize_name(payload.get("classification_note", ""))[:500]
        if platform_code not in FEE_PLATFORM_ETLS:
            raise ValueError("请选择有效的平台")
        if not name:
            raise ValueError("一级分类名称不能为空")
        display_order = max(0, int(payload.get("display_order") or 0))
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ("dim_platform_fee_primary_category:serial",),
            )
            cursor.execute(
                """
                SELECT primary_category_code,primary_category_name
                FROM dim.dim_platform_fee_primary_category
                WHERE dim.platform_category_name_key(primary_category_name)=dim.platform_category_name_key(%s)
                """,
                (name,),
            )
            if cursor.fetchone():
                raise ConflictError("一级分类名称已存在")
            cursor.execute(
                """
                SELECT COALESCE(MAX(SUBSTRING(primary_category_code FROM '[0-9]+$')::INTEGER), 0) + 1 AS next_serial
                FROM dim.dim_platform_fee_primary_category
                WHERE UPPER(primary_category_code) ~ '^[A-Z][A-Z0-9_]*_[0-9]+$'
                """,
            )
            serial = int(cursor.fetchone()["next_serial"])
            code = f"{platform_code.upper()}_{serial:02d}"
            cursor.execute(
                """
                INSERT INTO dim.dim_platform_fee_primary_category(
                    platform_code,primary_category_code,primary_category_name,display_order,
                    classification_note,is_active,created_by,updated_by
                ) VALUES(%s,%s,%s,%s,%s,TRUE,%s,%s)
                RETURNING *
                """,
                (platform_code, code, name, display_order, note, operator, operator),
            )
            row = dict(cursor.fetchone())
            self._write_log(
                cursor, "fee_category_create", "fee_category", code, operator, ip_address,
                "新增平台费用一级分类",
                {"platform_code": platform_code, "name": name, "display_order": display_order},
            )
        return row

    def update_fee_category(self, code: str, payload: dict, operator: str, ip_address: str | None) -> dict:
        code = normalize_name(code)
        name = normalize_name(payload.get("primary_category_name", ""))
        note = normalize_name(payload.get("classification_note", ""))[:500]
        if not name:
            raise ValueError("一级分类名称不能为空")
        display_order = max(0, int(payload.get("display_order") or 0))
        is_active = bool(payload.get("is_active", True))
        expected_updated_at = payload.get("updated_at")
        with self.transaction() as cursor:
            cursor.execute(
                """
                SELECT primary_category_code FROM dim.dim_platform_fee_primary_category
                WHERE dim.platform_category_name_key(primary_category_name)=dim.platform_category_name_key(%s) AND primary_category_code<>%s
                """,
                (name, code),
            )
            if cursor.fetchone():
                raise ConflictError("一级分类名称已被其他编码使用")
            cursor.execute(
                """
                UPDATE dim.dim_platform_fee_primary_category
                SET primary_category_name=%s,display_order=%s,classification_note=%s,
                    is_active=%s,updated_by=%s
                WHERE primary_category_code=%s
                  AND (%s::timestamptz IS NULL OR updated_at=%s::timestamptz)
                RETURNING *
                """,
                (name, display_order, note, is_active, operator, code, expected_updated_at, expected_updated_at),
            )
            record = cursor.fetchone()
            if not record:
                raise ConflictError("一级分类不存在或已被他人修改，请刷新页面")
            cursor.execute("SELECT DISTINCT platform_code FROM dim.dim_platform_fee_mapping WHERE primary_category_code=%s", (code,))
            affected_platforms = {item["platform_code"] for item in cursor.fetchall()}
            cursor.execute(
                """
                UPDATE dim.dim_platform_fee_mapping
                SET primary_category_name=%s,updated_by=%s
                WHERE primary_category_code=%s AND primary_category_name<>%s
                RETURNING platform_code
                """,
                (name, operator, code, name),
            )
            changed_platforms = affected_platforms | {row["platform_code"] for row in cursor.fetchall()}
            row = dict(record)
            self._write_log(cursor, "fee_category_update", "fee_category", code, operator, ip_address, "修改平台费用一级分类", {"name": name, "display_order": display_order, "is_active": is_active})
            etl_keys: set[str] = set()
            for platform in changed_platforms:
                etl_keys.update(FEE_PLATFORM_ETLS.get(platform, set()))
            etl_run = self.create_etl_run(etl_keys, trigger_type="fee_mapping", scope="affected", operator=operator, cursor=cursor) if etl_keys else None
            if etl_run:
                cursor.execute('UPDATE dim.dim_platform_fee_mapping SET last_etl_run_id=%s::uuid WHERE primary_category_code=%s',(str(etl_run['etl_run_id']),code))
        return {"category": row, "etl_run": etl_run}

    def _fee_candidates(self, cursor, platform_code: str | None = None) -> list[dict]:
        items: dict[tuple, dict] = {}
        configured_business_types: set[tuple[str, str, str]] = set()
        mapping_query = "SELECT * FROM dim.dim_platform_fee_mapping"
        if platform_code:
            cursor.execute(mapping_query + " WHERE platform_code=%s ORDER BY platform_code,source_document_type,display_order,mapping_id", (platform_code,))
        else:
            cursor.execute(mapping_query + " ORDER BY platform_code,source_document_type,display_order,mapping_id")
        for row in cursor.fetchall():
            item = dict(row)
            key = (item["platform_code"], item["source_document_type"], item["secondary_category_name"])
            item["mapping_status"] = "mapped" if item["is_active"] and item.get("primary_category_code") not in {None, "unmapped"} else "unmapped"
            items[key] = item
            if item.get("source_business_type"):
                configured_business_types.add((
                    item["platform_code"], item["source_document_type"], normalize_name(item["source_business_type"]),
                ))
        from etl.platform_finance.scene_normalization import normalize_items
        normalized=normalize_items(cursor,list(items.values()))
        items={(i['platform_code'],i['source_document_type'],i['secondary_category_name'],i.get('mapping_id')):i for i in normalized}
        for candidate_platform, query in FEE_ODS_CANDIDATE_QUERIES.items():
            if platform_code and candidate_platform != platform_code:
                continue
            # Materialize distinct inputs before cleaning. This also keeps
            # scene CASE/regex expressions out of a pushed-down blank filter.
            cursor.execute(
                f"""
                WITH raw_candidates AS MATERIALIZED (
                    SELECT DISTINCT source_document_type,source_business_type,source_description,secondary_category_name
                    FROM ({query.replace('%','%%')}) AS ods_candidate(
                        source_document_type,source_business_type,source_description,secondary_category_name
                    )
                )
                SELECT DISTINCT source_document_type,source_business_type,source_description,
                    dim.normalize_platform_scene(%s,source_document_type,secondary_category_name,source_business_type) secondary_category_name
                FROM raw_candidates
                WHERE NULLIF(BTRIM(secondary_category_name),'') IS NOT NULL
                """,(candidate_platform,)
            )
            for row in cursor.fetchall():
                candidate = dict(row)
                key = (candidate_platform, candidate["source_document_type"], candidate["secondary_category_name"])
                business_key = (
                    candidate_platform, candidate["source_document_type"],
                    normalize_name(candidate.get("source_business_type") or ""),
                )
                # 天猫、拼多多候选使用DWD同口径的二级场景；即使业务类型已有
                # 映射，只要描述产生了新场景，也必须展示为未映射原始费用。
                if any(self._fee_rule_matches(existing, candidate_platform, candidate) for existing in items.values()):
                    continue
                if key not in items:
                    items[key] = self._unmapped_fee_candidate(candidate_platform, candidate)
        from etl.platform_finance.operating_policy import present_policy
        aliases={}
        for item in items.values():
            if item.get('alias_of_mapping_id'):
                aliases.setdefault(item['alias_of_mapping_id'],[]).append(item['secondary_category_name'])
        runs={}
        run_ids=[str(i['last_etl_run_id']) for i in items.values() if i.get('last_etl_run_id')]
        if run_ids:
            cursor.execute('SELECT etl_run_id,status FROM ops.etl_run WHERE etl_run_id=ANY(%s::uuid[])',(run_ids,))
            runs={str(r['etl_run_id']):r['status'] for r in cursor.fetchall()}
        visible=[]
        grouped={}
        for item in items.values():
            if item.get('alias_of_mapping_id'):continue
            item['aliases']=aliases.get(item.get('mapping_id'),[])
            item['configuration_etl_status']=runs.get(str(item.get('last_etl_run_id')))
            item=present_policy(item)
            group=(item['platform_code'],item['source_document_type'],item['secondary_category_name'])
            signature=tuple(item.get(k) for k in ('operating_treatment','canonical_operating_treatment','primary_category_code','is_active','include_in_platform_expense','source_role','source_usage'))
            if group in grouped and grouped[group][0]==signature and item.get('mapping_id'):
                grouped[group][1]['group_mapping_ids'].append(item['mapping_id'])
                continue
            item['group_mapping_ids']=[item['mapping_id']] if item.get('mapping_id') else []
            grouped[group]=(signature,item)
            visible.append(item)
        return visible

    @staticmethod
    def _unmapped_fee_candidate(platform_code: str, candidate: dict) -> dict:
        return {
            "mapping_id": None,
            "platform_code": platform_code,
            "platform_name": next((r.platform_name for r in ACTIVE_REPORTS if r.platform_code == platform_code), platform_code),
            "source_document_type": candidate["source_document_type"],
            "secondary_category_code": None,
            "secondary_category_name": candidate["secondary_category_name"],
            "source_business_type": candidate.get("source_business_type"),
            "source_description_match_type": "none",
            "source_description_match_value": candidate.get("source_description"),
            "mapping_priority": 0,
            "primary_category_code": None,
            "primary_category_name": None,
            "include_in_platform_expense": False,
            "operating_treatment": None,
            "classification_note": "经营归属待确认",
            "display_order": 0,
            "is_active": True,
            "mapping_status": "unmapped",
            "updated_at": None,
            "updated_by": None,
            "treatment_origin": "pending",
            "source_usage": "independent",
        }

    def list_fee_mappings(self, query: dict) -> dict:
        with self.transaction() as cursor:
            items = self._fee_candidates(cursor, platform_code=query.get("platform_code"))
        platform = query.get("platform_code")
        document = query.get("source_document_type")
        status = query.get("mapping_status")
        treatment = query.get("operating_treatment")
        keyword = normalize_name(query.get("keyword", "")).casefold()
        if platform:
            items = [item for item in items if item["platform_code"] == platform]
        if document:
            items = [item for item in items if item["source_document_type"] == document]
        if status:
            items = [item for item in items if item["mapping_status"] == status]
        if treatment:
            items = [item for item in items if item.get("operating_treatment") == (None if treatment=='pending' else treatment)]
        if keyword:
            items = [
                item for item in items
                if keyword in " ".join(str(item.get(key) or "") for key in (
                    "source_business_type", "source_description_match_value", "secondary_category_name",
                    "primary_category_code", "primary_category_name", "platform_name",
                )).casefold()
            ]
        total = len(items)
        unmapped_total = sum(1 for item in items if item["mapping_status"] == "unmapped")
        page = max(1, int(query.get("page", 1)))
        page_size_limit = 5000 if query.get("export") == "true" else 200
        page_size = max(1, min(int(query.get("page_size", 20)), page_size_limit))
        start = (page - 1) * page_size
        return {"items": items[start:start + page_size], "pagination": {"total": total, "unmapped_total": unmapped_total, "page": page, "page_size": page_size}}

    def list_operating_details(self, query: dict) -> dict:
        filters, params = ["TRUE"], []
        for column in ("platform_code", "shop_code", "company_code", "source_document_type", "operating_treatment", "mapping_status"):
            if query.get(column):
                if column=='operating_treatment' and query[column]=='pending':
                    filters.append('operating_treatment IS NULL')
                else:
                    filters.append(f"{column}=%s")
                    params.append(query[column])
        for key, comparison in (("date_from", ">="), ("date_to", "<=")):
            if query.get(key):
                filters.append(f"stat_date {comparison} %s")
                params.append(date.fromisoformat(query[key]))
        if query.get("keyword"):
            filters.append("CONCAT_WS(' ',secondary_category_name,primary_category_name,exclusion_reason,shop_name,company_name) ILIKE %s")
            params.append("%" + query["keyword"] + "%")
        where = " AND ".join(filters)
        page = max(1, int(query.get("page", 1)))
        size = max(1, min(int(query.get("page_size", 20)), 5000 if query.get("export") == "true" else 200))
        relation = "ads.ads_platform_operating_flow_company_shop_daily_scene"
        # Formula components keep their identities in ADS. The UI presents
        # one daily scene, so internal component codes must not split its rows.
        dimensions='stat_date,platform_code,platform_name,shop_code,shop_name,company_code,company_name,source_document_type,secondary_category_name,primary_category_code,primary_category_name,operating_treatment,mapping_status,exclusion_reason'
        display=f'''WITH source AS (SELECT * FROM {relation} WHERE {where}), displayed AS (
            SELECT {dimensions},MIN(secondary_category_code) secondary_category_code,
                MIN(source_origin) source_origin,ARRAY_AGG(DISTINCT source_origin) source_origins,
                SUM(source_signed_amount) source_signed_amount,SUM(income_amount) income_amount,
                SUM(expense_amount) expense_amount,SUM(excluded_amount) excluded_amount,
                SUM(included_detail_count) included_detail_count,SUM(source_detail_count) source_detail_count,
                MAX(source_updated_at) source_updated_at,MAX(mapping_updated_at) mapping_updated_at,
                MAX(updated_at) updated_at,COUNT(*) published_scene_rows
            FROM source GROUP BY {dimensions})'''
        with self.transaction() as cursor:
            cursor.execute(display+" SELECT COUNT(*) total,COUNT(DISTINCT (platform_code,source_document_type,secondary_category_name)) scene_total,COALESCE(SUM(published_scene_rows),0) published_scene_rows,COUNT(*) FILTER(WHERE mapping_status='unmapped') unmapped_total,COUNT(*) FILTER(WHERE operating_treatment IS NULL) pending_total,COALESCE(SUM(source_signed_amount) FILTER(WHERE operating_treatment IS NULL),0) pending_amount,COALESCE(SUM(income_amount),0) income_amount,COALESCE(SUM(expense_amount),0) expense_amount FROM displayed", params)
            summary = dict(cursor.fetchone())
            cursor.execute(display+" SELECT * FROM displayed ORDER BY stat_date DESC,platform_code,shop_code,source_document_type,secondary_category_name,primary_category_code,operating_treatment,mapping_status,exclusion_reason LIMIT %s OFFSET %s", [*params, size, (page-1)*size])
            rows = [dict(row) for row in cursor.fetchall()]
        return {"items": rows, "summary": summary, "pagination": {"total": summary["total"], "unmapped_total": summary["unmapped_total"], "page": page, "page_size": size}}

    @staticmethod
    def _fee_rule_matches(rule: dict, platform: str, candidate: dict) -> bool:
        if rule.get("platform_code") != platform or rule.get("source_document_type") != candidate["source_document_type"] or rule.get("source_component_code"):
            return False
        match_type = rule.get("source_description_match_type") or "none"
        if match_type == "none":
            return rule.get("secondary_category_name") == candidate["secondary_category_name"]
        if rule.get("source_business_type") and rule["source_business_type"] != candidate.get("source_business_type"):
            return False
        value = rule.get("source_description_match_value") or ""
        description = candidate.get("source_description") or ""
        return match_type == "any" or (match_type == "exact" and value == description) or (match_type == "prefix" and description.startswith(value)) or (match_type == "contains" and value in description)

    def assign_fee_mappings(self, payload: dict, operator: str, ip_address: str | None) -> dict:
        try:
            return self._assign_fee_mappings(payload,operator,ip_address)
        except ValueError as exc:
            with self.transaction() as cursor:
                self._write_log(cursor,'fee_mapping_rejected','fee_mapping',None,operator,ip_address,
                    '经营收支配置被拒绝：'+str(exc)[:400],{'mapping_ids':[i.get('mapping_id') for i in payload.get('items',[])],
                    'operating_treatment':payload.get('operating_treatment'),'reason':str(exc)[:500]})
            raise

    def _assign_fee_mappings(self, payload: dict, operator: str, ip_address: str | None) -> dict:
        selections = payload.get("items") or []
        if not selections:
            raise ValueError("请至少选择一条收支场景")
        code = normalize_name(payload.get("primary_category_code", "")) or "unmapped"
        name = normalize_name(payload.get("primary_category_name", "")) or "未映射"
        if code == "unmapped":
            name = "未映射"
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,63}", code):
            raise ValueError("一级分类编码格式无效")
        has_category = "primary_category_code" in payload or "primary_category_name" in payload
        requested_treatment = payload.get("operating_treatment")
        if requested_treatment is not None and requested_treatment not in {"income", "expense", "excluded", "pending"}:
            raise ValueError("经营收支归属只能为收入、支出或不计入")
        changed, before, platforms = [], [], set()
        with self.transaction() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(hashtext('mock_coffice_global_etl')) acquired")
            lock=cursor.fetchone()
            if not (lock.get('acquired') if isinstance(lock,dict) else lock[0]):
                raise ValueError('当前正在重算数据，请在任务完成后重新预览并保存')
            if payload.get('preview_token'):
                from .operating_config import preview
                if preview(cursor,payload)['preview_token']!=payload['preview_token']:
                    raise ValueError('预览后金额或影响范围已变化，请重新预览再保存')
            selections=self._expand_scene_selections(cursor,selections)
            if code != "unmapped":
                cursor.execute("SELECT primary_category_code,primary_category_name,is_active FROM dim.dim_platform_fee_primary_category WHERE primary_category_code=%s", (code,))
                category = cursor.fetchone()
                if not category or not category["is_active"] or category["primary_category_name"] != name:
                    raise ConflictError("请选择已启用且名称一致的一级分类")
            for item in selections:
                platform = normalize_name(item.get("platform_code", ""))
                document = normalize_name(item.get("source_document_type", ""))
                scene = normalize_name(item.get("secondary_category_name", ""))
                if platform not in FEE_PLATFORM_ETLS or document not in {"settlement", "fund"} or not scene:
                    raise ValueError("收支场景平台、来源单据或业务名称无效")
                platforms.add(platform)
                mapping_id = item.get("mapping_id")
                old = None
                if mapping_id:
                    cursor.execute("SELECT * FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s FOR UPDATE", (mapping_id,))
                    old = cursor.fetchone()
                    if not old or old["platform_code"] != platform or old["source_document_type"] != document:
                        raise ConflictError("收支规则不存在或平台不一致，请刷新页面")
                    if old.get('alias_of_mapping_id'):
                        raise ConflictError('该业务已有统一配置入口，请刷新后编辑有效规则')
                    expected = item.get("updated_at")
                    if expected and datetime.fromisoformat(str(expected).replace("Z", "+00:00")) != old["updated_at"]:
                        raise ConflictError(f"映射{mapping_id}已被修改，请刷新页面")
                    before.append(dict(old))
                item_code = code if has_category else (old or item).get("primary_category_code") or "unmapped"
                item_name = name if has_category else (old or item).get("primary_category_name") or "未映射"
                treatment = requested_treatment if 'operating_treatment' in payload else (old or item).get("operating_treatment")
                if treatment=='pending': treatment=None
                from .operating_config import validate_change
                validate_change(cursor,old,treatment,payload)
                match_type = payload.get("source_description_match_type", (old or item).get("source_description_match_type") or "none")
                match_value = payload.get("source_description_match_value", (old or item).get("source_description_match_value"))
                priority = int(payload.get("mapping_priority", (old or item).get("mapping_priority") or 0))
                if match_type not in {"none", "exact", "prefix", "contains", "any"}:
                    raise ValueError("描述匹配方式无效")
                if match_type in {"exact", "prefix", "contains"} and not normalize_name(match_value or ""):
                    raise ValueError("描述匹配值不能为空")
                note = normalize_name(payload.get("classification_note", (old or item).get("classification_note") or ""))[:500]
                from etl.platform_finance.operating_policy import maintain_automatic_note
                note=maintain_automatic_note(old or item,treatment,item_name,note)
                if old:
                    cursor.execute("""UPDATE dim.dim_platform_fee_mapping
                        SET primary_category_code=%s,primary_category_name=%s,operating_treatment=%s,
                            source_description_match_type=%s,source_description_match_value=%s,mapping_priority=%s,
                            classification_note=%s,updated_by=%s,is_active=%s
                        WHERE mapping_id=%s RETURNING *""",
                        (item_code,item_name,treatment,match_type,match_value,priority,note,operator,old["is_active"],mapping_id))
                else:
                    secondary = f"{platform}_{document}_{hashlib.sha1(scene.encode('utf-8')).hexdigest()[:16]}"
                    role = "RECONCILIATION"
                    cursor.execute("""INSERT INTO dim.dim_platform_fee_mapping(
                        platform_code,platform_name,source_document_type,secondary_category_code,secondary_category_name,
                        source_business_type,source_description_match_type,source_description_match_value,mapping_priority,
                        primary_category_code,primary_category_name,operating_treatment,canonical_operating_treatment,
                        include_in_platform_expense,source_role,metric_role,classification_note,created_by,updated_by,source_treatment_initialized)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE) RETURNING *""",
                        (platform,item.get("platform_name") or platform,document,secondary,scene,item.get("source_business_type"),
                         match_type,match_value,priority,item_code,item_name,treatment,None,False,role,
                         "PLATFORM_EXPENSE" if treatment=="expense" else "MAIN_REVENUE" if treatment=="income" else "RECONCILIATION",note,operator,operator))
                changed.append(dict(cursor.fetchone()))
                origin=('pending' if treatment is None else 'manual') if 'operating_treatment' in payload else (old or {}).get('treatment_origin','pending')
                cursor.execute('UPDATE dim.dim_platform_fee_mapping SET treatment_origin=%s,policy_initialized=TRUE WHERE mapping_id=%s',(origin,changed[-1]['mapping_id']))
                if payload.get('source_usage')=='independent' and old and old.get('source_usage')!='independent':
                    cursor.execute("UPDATE dim.dim_platform_fee_mapping SET source_usage='independent',source_usage_note=%s WHERE mapping_id=%s",
                        ('人工更正独立业务依据：'+str(payload['source_correction_reason']).strip(),changed[-1]['mapping_id']))
                cursor.execute('SELECT * FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s',(changed[-1]['mapping_id'],))
                changed[-1]=dict(cursor.fetchone())
            detail = {"platforms": sorted(platforms), "before": before, "after": changed}
            self._write_log(cursor, "fee_mapping_assign", "fee_mapping", None, operator, ip_address,
                f"更新{len(changed)}条经营收支归属或分类", json.loads(json.dumps(detail, default=str)))
            keys = set().union(*(FEE_PLATFORM_ETLS[p] for p in platforms))
            # Both derived totals must be refreshed even when an income/expense is rerouted.
            keys.add("platform_main_business_income_shared_ads")
            etl_run = self.create_etl_run(keys, trigger_type="fee_mapping", scope="affected", operator=operator, cursor=cursor)
            cursor.execute('UPDATE dim.dim_platform_fee_mapping SET last_etl_run_id=%s::uuid WHERE mapping_id=ANY(%s)',
                (str(etl_run['etl_run_id']),[r['mapping_id'] for r in changed]))
        return {"items": changed, "etl_run": etl_run}

    @staticmethod
    def _expand_scene_selections(cursor,selections):
        from etl.platform_finance.scene_normalization import mapping_group
        expanded={}
        for item in selections:
            if not item.get('mapping_id'):
                expanded[(item['platform_code'],item['secondary_category_name'])]=item
                continue
            group=mapping_group(cursor,item['mapping_id'])
            for member in group or [item]:
                selected={**member}
                if member.get('mapping_id')==item['mapping_id']:
                    selected['updated_at']=item.get('updated_at')
                else:selected['updated_at']=None
                expanded[member['mapping_id']]=selected
        return list(expanded.values())

    def preview_fee_mappings(self, payload: dict) -> dict:
        from .operating_config import preview
        with self.transaction() as cursor:
            return preview(cursor,payload)

    def list_scene_rules(self):
        from .scene_rules import list_rules
        with self.transaction() as cursor:return {'items':list_rules(cursor)}

    def preview_scene_rule(self,payload):
        from .scene_rules import preview
        with self.transaction() as cursor:return preview(cursor,payload)

    def save_scene_rule(self,payload,operator,ip_address):
        from .scene_rules import save
        return save(self,payload,operator,ip_address)

    def fee_mapping_source(self, mapping_id: int) -> dict:
        from .operating_config import source_evidence
        from etl.platform_finance.operating_policy import present_policy
        with self.transaction() as cursor:
            cursor.execute('SELECT * FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s',(mapping_id,))
            row=cursor.fetchone()
            if not row:raise NotFoundError('收支规则不存在')
            return {'rule':present_policy(dict(row)),'evidence':source_evidence(cursor,dict(row))}

    def set_fee_mapping_status(self, mapping_id: int, is_active: bool, expected_updated_at: str | None, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            from etl.platform_finance.scene_normalization import mapping_group
            group=mapping_group(cursor,mapping_id)
            cursor.execute(
                """
                UPDATE dim.dim_platform_fee_mapping SET is_active=%s,updated_by=%s
                WHERE mapping_id=%s AND (%s::timestamptz IS NULL OR updated_at=%s::timestamptz)
                RETURNING *
                """,
                (bool(is_active), operator, mapping_id, expected_updated_at, expected_updated_at),
            )
            row = cursor.fetchone()
            if not row:
                raise ConflictError("映射不存在或已被他人修改")
            cursor.execute('UPDATE dim.dim_platform_fee_mapping SET is_active=%s,updated_by=%s WHERE mapping_id=ANY(%s)',
                (bool(is_active),operator,[r['mapping_id'] for r in group]))
            self._write_log(cursor, "fee_mapping_status", "fee_mapping", str(mapping_id), operator, ip_address, "启停费用映射", {"is_active": bool(is_active)})
            etl_run = self.create_etl_run(FEE_PLATFORM_ETLS[row["platform_code"]], trigger_type="fee_mapping", scope="affected", operator=operator, cursor=cursor)
            cursor.execute('UPDATE dim.dim_platform_fee_mapping SET last_etl_run_id=%s::uuid WHERE mapping_id=ANY(%s)',
                (str(etl_run['etl_run_id']),[r['mapping_id'] for r in group]))
        return {"mapping": dict(row), "etl_run": etl_run}

    def delete_fee_category(self, code: str, operator: str, ip_address: str | None) -> dict:
        code = normalize_name(code)
        with self.transaction() as cursor:
            cursor.execute(
                """
                SELECT primary_category_code,primary_category_name
                FROM dim.dim_platform_fee_primary_category
                WHERE primary_category_code=%s
                """,
                (code,),
            )
            record = cursor.fetchone()
            if not record:
                raise ConflictError("一级分类不存在或已被删除")
            cursor.execute(
                """
                UPDATE dim.dim_platform_fee_mapping
                SET primary_category_code='unmapped',primary_category_name='未映射',
                    updated_by=%s
                WHERE primary_category_code=%s
                RETURNING platform_code
                """,
                (operator, code),
            )
            affected_platforms = {row["platform_code"] for row in cursor.fetchall()}
            cursor.execute(
                "DELETE FROM dim.dim_platform_fee_primary_category WHERE primary_category_code=%s",
                (code,),
            )
            self._write_log(cursor, "fee_category_delete", "fee_category", code, operator, ip_address, "删除平台费用一级分类", {"name": record["primary_category_name"], "affected_mappings": len(affected_platforms)})
            etl_keys: set[str] = set()
            for platform in affected_platforms:
                etl_keys.update(FEE_PLATFORM_ETLS.get(platform, set()))
            etl_run = self.create_etl_run(etl_keys, trigger_type="fee_mapping", scope="affected", operator=operator, cursor=cursor) if etl_keys else None
        return {"category": dict(record), "etl_run": etl_run}

    def delete_fee_mapping(self, mapping_id: int, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            from etl.platform_finance.scene_normalization import mapping_group
            group=mapping_group(cursor,mapping_id)
            cursor.execute(
                """
                SELECT mapping_id,platform_code,secondary_category_name,primary_category_code,updated_at
                FROM dim.dim_platform_fee_mapping
                WHERE mapping_id=%s
                """,
                (mapping_id,),
            )
            record = cursor.fetchone()
            if not record:
                raise ConflictError("映射不存在或已被删除")
            cursor.execute(
                "UPDATE dim.dim_platform_fee_mapping SET primary_category_code='unmapped',primary_category_name='未映射' WHERE mapping_id=ANY(%s)",
                ([r['mapping_id'] for r in group],),
            )
            from etl.platform_finance.operating_policy import maintain_automatic_note
            for member in group:
                note=maintain_automatic_note(member,member.get('operating_treatment'),'未映射',member.get('classification_note'))
                if note!=member.get('classification_note'):
                    cursor.execute('UPDATE dim.dim_platform_fee_mapping SET classification_note=%s WHERE mapping_id=%s',(note,member['mapping_id']))
            self._write_log(cursor, "fee_mapping_delete", "fee_mapping", str(mapping_id), operator, ip_address, "清除收支分类，保留经营归属", {"platform_code": record["platform_code"], "secondary_category_name": record["secondary_category_name"], "primary_category_code": record["primary_category_code"]})
            etl_run = self.create_etl_run(FEE_PLATFORM_ETLS.get(record["platform_code"], set()), trigger_type="fee_mapping", scope="affected", operator=operator, cursor=cursor)
            cursor.execute('UPDATE dim.dim_platform_fee_mapping SET last_etl_run_id=%s::uuid WHERE mapping_id=ANY(%s)',
                (str(etl_run['etl_run_id']),[r['mapping_id'] for r in group]))
        return {"mapping": dict(record), "etl_run": etl_run}


class FileIngestWorker:
    def __init__(self, service: FileIngestService, worker_name: str = "standalone", *, worker_id=None):
        self.service = service
        self.worker_id = worker_id or uuid.uuid4()
        self.worker_name = worker_name[:100]
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._last_recovery_scan = float('-inf')
        self._heartbeat("starting")

    def run_once(self) -> bool:
        if self._stop.is_set():
            return False
        self._idle.clear()
        try:
            self._heartbeat("busy")
            if time.monotonic() - self._last_recovery_scan >= 30:
                with self.service.transaction() as cursor:
                    self.service._mark_stale_drafts(cursor)
                self.recover_interrupted_etl()
                self._last_recovery_scan = time.monotonic()
            if self._process_ingest_run():
                return True
            return self._process_etl_run()
        finally:
            self._idle.set()
            self._heartbeat("stopped" if self._stop.is_set() else "idle")

    def stop(self) -> None:
        self._stop.set()
        if self._idle.wait(timeout=8):
            self._heartbeat("stopped")

    def _heartbeat(self, status: str, current_task: str | None = None) -> None:
        with self.service.transaction() as cursor:
            cursor.execute("SELECT to_regclass('ops.worker_heartbeat') AS relation")
            if not cursor.fetchone()["relation"]:
                return
            cursor.execute(
                """
                INSERT INTO ops.worker_heartbeat(
                    worker_id,worker_name,process_id,status,current_task,stopped_at
                ) VALUES(%s,%s,%s,%s,%s,CASE WHEN %s IN ('stopped','failed') THEN NOW() END)
                ON CONFLICT(worker_id) DO UPDATE SET status=EXCLUDED.status,
                    current_task=EXCLUDED.current_task,last_seen_at=NOW(),
                    stopped_at=EXCLUDED.stopped_at
                """,
                (str(self.worker_id), self.worker_name, os.getpid(), status, current_task, status),
            )

    @staticmethod
    def _has_file_loader_diagnostics(cursor) -> bool:
        """Keep workers compatible with a pre-391 test schema.

        The production migration adds two nullable audit columns.  The
        development database is intentionally immutable, so an older test
        schema must still be able to process files; failures fall back to the
        existing error_message column until that migration is applied there.
        """
        cursor.execute(
            """
            SELECT COUNT(*) AS diagnostic_column_count
            FROM information_schema.columns
            WHERE table_schema='ops' AND table_name='ingest_file_task'
              AND column_name IN ('loader_exit_code','output_summary')
            """
        )
        row = cursor.fetchone()
        return bool(row and int(row["diagnostic_column_count"] or 0) == 2)

    def recover_stale(self, minimum_age_minutes: int = 15) -> dict[str, int]:
        age = max(1, int(minimum_age_minutes))
        with self.service.transaction() as cursor:
            cursor.execute(
                """
                UPDATE ops.ingest_file_task SET status='uploaded',error_message='Worker中断后自动恢复',updated_at=NOW()
                WHERE status='processing' AND updated_at < NOW()-(%s * INTERVAL '1 minute')
                """,
                (age,),
            )
            files = cursor.rowcount
            cursor.execute(
                """
                UPDATE ops.ingest_run SET status='ready',error_message='Worker中断后自动恢复',updated_at=NOW()
                WHERE status='processing' AND updated_at < NOW()-(%s * INTERVAL '1 minute')
                """,
                (age,),
            )
            ingest_runs = cursor.rowcount
        recovered = self.recover_interrupted_etl(minimum_age_minutes=age)
        self._last_recovery_scan = time.monotonic()
        return {"files": files, "ingest_runs": ingest_runs, **recovered}

    @staticmethod
    def _close_interrupted_etl(cursor, run_id, reason: str) -> int:
        cursor.execute("SELECT etl_run_id FROM ops.etl_run WHERE etl_run_id=%s AND status='running' FOR UPDATE",
                       (str(run_id),))
        if cursor.fetchone() is None:
            return 0
        cursor.execute(
            """UPDATE ops.etl_task
               SET status=CASE WHEN status='running' THEN 'failed' ELSE 'skipped' END,
                   error_message=CASE WHEN status='running' THEN %s ELSE '本次ETL运行中断，未执行；可重试' END,
                   finished_at=NOW(),updated_at=NOW()
               WHERE etl_run_id=%s AND status IN ('running','queued')""",
            (reason, str(run_id)),
        )
        tasks = cursor.rowcount
        cursor.execute(
            """UPDATE ops.etl_run r
               SET status=CASE WHEN EXISTS(SELECT 1 FROM ops.etl_task t
                       WHERE t.etl_run_id=r.etl_run_id AND t.status='success')
                   THEN 'partial_failed' ELSE 'failed' END,
                   error_message=%s,completed_at=NOW(),updated_at=NOW()
               WHERE etl_run_id=%s AND status='running'""",
            (reason, str(run_id)),
        )
        FileIngestService._write_log(cursor, 'etl_interrupted', 'etl_run', str(run_id),
                                    '系统', None, 'ETL执行中断，结束本次运行', {'reason': reason})
        return tasks

    def recover_interrupted_etl(self, minimum_age_minutes: int = 15) -> dict[str, int]:
        """Close abandoned attempts; never infer death from task duration alone."""
        recovered = {"etl_tasks": 0, "etl_runs": 0}
        connection = self.service.connect()
        connection.autocommit = True
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as guard:
                guard.execute("SELECT pg_try_advisory_lock(hashtext('mock_coffice_file_ingest_dispatch')) AS locked")
                if not guard.fetchone()['locked']:
                    return recovered
                guard.execute("SELECT pg_try_advisory_lock(hashtext('mock_coffice_global_etl')) AS locked")
                if not guard.fetchone()['locked']:
                    return recovered
                with self.service.transaction() as cursor:
                    cursor.execute(
                        """SELECT r.etl_run_id FROM ops.etl_run r
                           LEFT JOIN ops.worker_heartbeat w ON w.worker_id=r.worker_id
                           WHERE r.status='running' AND (
                               (r.worker_id IS NULL AND r.updated_at<NOW()-(%s*INTERVAL '1 minute'))
                               OR (r.worker_id IS NOT NULL AND (
                                   w.status IN ('stopped','failed')
                                   OR (COALESCE(r.heartbeat_at,r.updated_at)<NOW()-INTERVAL '90 seconds'
                                       AND (w.worker_id IS NULL OR w.last_seen_at<NOW()-INTERVAL '90 seconds'
                                           OR w.current_task IS DISTINCT FROM 'etl:' || r.etl_run_id::text)))))
                           ORDER BY r.created_at LIMIT 20 FOR UPDATE OF r SKIP LOCKED""",
                        (max(1, int(minimum_age_minutes)),),
                    )
                    for row in cursor.fetchall():
                        reason = '后端重启或Worker中断，执行者已退出；本次执行未正常完成，可重试'
                        recovered['etl_tasks'] += self._close_interrupted_etl(cursor, row['etl_run_id'], reason)
                        recovered['etl_runs'] += 1
        finally:
            # Session locks are released even when recovery or its transaction fails.
            connection.close()
        return recovered

    def _pulse_etl(self, run_id) -> None:
        with self.service.transaction() as cursor:
            cursor.execute(
                """UPDATE ops.etl_run SET heartbeat_at=NOW()
                   WHERE etl_run_id=%s AND worker_id=%s AND status='running'""",
                (str(run_id), str(self.worker_id)),
            )
            if cursor.rowcount != 1:
                raise RuntimeError('ETL执行归属已失效')
        self._heartbeat('busy', f'etl:{run_id}')

    @staticmethod
    def _terminate_etl_process(process, *, owns_group: bool = True) -> None:
        if process.poll() is not None:
            return
        if os.name == 'nt':
            # The venv launcher has a child python.exe on Windows. Stop the
            # entire owned tree, not just the launcher, before closing the run.
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=5, check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            import signal
            try:
                if owns_group:
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            except ProcessLookupError:
                return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                process.kill()
            elif owns_group:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=3)

    def _execute_etl_process(self, command, environment, run_id, *, pulse=True, timeout_seconds=7200):
        owns_group = not getattr(self, '_supervised', False)
        options = {} if os.name == 'nt' else {'start_new_session': owns_group}
        process = subprocess.Popen(command, cwd=PROJECT_ROOT, env=environment, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   encoding='utf-8', errors='replace', **options)
        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else float('inf')
        next_pulse = 0.0
        try:
            while True:
                if self._stop.is_set():
                    raise RuntimeError('后端停止，ETL执行中断；可重试')
                now = time.monotonic()
                if now >= deadline:
                    raise TimeoutError('ETL执行超过7200秒，已终止；可重试')
                if pulse and now >= next_pulse:
                    self._pulse_etl(run_id)
                    next_pulse = now + 10
                try:
                    output, error = process.communicate(timeout=1)
                    return subprocess.CompletedProcess(command, process.returncode, output, error)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            self._terminate_etl_process(process, owns_group=owns_group)
            # communicate closes the pipe handles after cancellation as well.
            process.communicate(timeout=3)

    def _process_ingest_run(self) -> bool:
        with self.service.transaction() as cursor:
            cursor.execute(
                """
                SELECT run_id FROM ops.ingest_run WHERE status='ready'
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
                """
            )
            row = cursor.fetchone()
            if not row:
                return False
            run_id = row["run_id"]
            cursor.execute("UPDATE ops.ingest_run SET status='processing',updated_at=NOW() WHERE run_id=%s", (run_id,))

        try:
            return self._process_claimed_ingest_run(run_id)
        except Exception as exc:
            # 领取会话后任何未预期异常都必须收口。此前异常只被外层线程打印，
            # 会话已经是processing却没有completed_at，页面因而永久显示处理中，
            # 后续会话也无法得到明确的失败原因。
            self._fail_claimed_ingest_run(run_id, exc)
            return True

    def _process_claimed_ingest_run(self, run_id) -> bool:
        with self.service.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.ingest_run WHERE run_id=%s", (run_id,))
            run = cursor.fetchone()
            cursor.execute("SELECT * FROM ops.ingest_file_task WHERE run_id=%s ORDER BY created_at", (run_id,))
            tasks = [dict(item) for item in cursor.fetchall()]
        for task in tasks:
            if task["status"] != "uploaded":
                continue
            self._run_loader(task, run["source"])
        with self.service.transaction() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) FILTER(WHERE status='success') AS success_count,
                       COUNT(*) FILTER(WHERE status='duplicate') AS duplicate_count,
                       COUNT(*) FILTER(WHERE status='failed') AS failed_count
                FROM ops.ingest_file_task WHERE run_id=%s
                """,
                (run_id,),
            )
            counts = cursor.fetchone()
            if counts["failed_count"]:
                final_status = "failed"
                etl_run = None
                cursor.execute(
                    """
                    SELECT source_file_name, error_message
                    FROM ops.ingest_file_task
                    WHERE run_id=%s AND status='failed'
                    ORDER BY created_at
                    LIMIT 20
                    """,
                    (run_id,),
                )
                failed_details = [
                    f"{row['source_file_name']}：{row['error_message'] or '无错误摘要'}"
                    for row in cursor.fetchall()
                ]
                run_error = ("文件导入失败：" + "；".join(failed_details))[-OUTPUT_LIMIT:]
            else:
                from .coverage import activate
                cursor.execute('SELECT * FROM ops.ingest_file_task WHERE run_id=%s ORDER BY created_at', (run_id,))
                processed = [dict(r) for r in cursor.fetchall()]
                coverage_result = activate(cursor, run, processed, self.service.storage_root)
                cursor.execute('UPDATE ops.ingest_run SET coverage_result=%s WHERE run_id=%s', (Json(coverage_result),run_id))
                final_status = "success" if counts["success_count"] or coverage_result else "no_change"
                cursor.execute("SELECT DISTINCT report_type FROM ops.ingest_file_task WHERE run_id=%s AND (status='success' OR (%s AND status='duplicate'))", (run_id,bool(coverage_result) or run.get('import_mode')=='refresh_only'))
                keys: set[str] = set()
                for item in cursor.fetchall():
                    keys.update(REPORT_BY_TYPE[item["report_type"]].etl_keys)
                etl_run = self.service.create_etl_run(keys, trigger_type="ingest_complete", scope="affected", operator=run["operator"], ingest_run_id=str(run_id), cursor=cursor) if run["auto_refresh"] else None
                if etl_run and coverage_result and not etl_run.get('reused'):
                    from .refresh_scope import build_refresh_context
                    frozen = build_refresh_context(cursor, {'trigger_type':'ingest_complete','scope':'affected',
                                                           'ingest_run_id':str(run_id)})
                    cursor.execute('UPDATE ops.etl_run SET refresh_context=%s WHERE etl_run_id=%s',
                                   (Json(frozen),str(etl_run['etl_run_id'])))
                run_error = None
            cursor.execute(
                """
                UPDATE ops.ingest_run SET status=%s,success_file_count=%s,duplicate_file_count=%s,
                    failed_file_count=%s,error_message=%s,completed_at=NOW(),updated_at=NOW()
                WHERE run_id=%s
                """,
                (final_status, counts["success_count"], counts["duplicate_count"], counts["failed_count"], run_error, run_id),
            )
        return True

    def _fail_claimed_ingest_run(self, run_id, exc: Exception) -> None:
        failure_message = f"Worker处理导入会话异常：{exc}"[-OUTPUT_LIMIT:]
        try:
            with self.service.transaction() as cursor:
                cursor.execute(
                    """
                    UPDATE ops.ingest_file_task
                    SET status='failed',
                        error_message=COALESCE(NULLIF(error_message,''),%s),
                        finished_at=NOW(),updated_at=NOW()
                    WHERE run_id=%s AND status IN ('uploaded','processing')
                    """,
                    (failure_message, run_id),
                )
                cursor.execute(
                    """
                    SELECT COUNT(*) FILTER(WHERE status='success') AS success_count,
                           COUNT(*) FILTER(WHERE status='duplicate') AS duplicate_count,
                           COUNT(*) FILTER(WHERE status='failed') AS failed_count
                    FROM ops.ingest_file_task WHERE run_id=%s
                    """,
                    (run_id,),
                )
                counts = cursor.fetchone()
                cursor.execute(
                    """
                    UPDATE ops.ingest_run
                    SET status='failed',success_file_count=%s,duplicate_file_count=%s,
                        failed_file_count=%s,error_message=%s,completed_at=NOW(),updated_at=NOW()
                    WHERE run_id=%s
                    """,
                    (
                        counts["success_count"],
                        counts["duplicate_count"],
                        counts["failed_count"],
                        failure_message,
                        run_id,
                    ),
                )
        except Exception as finalize_error:
            # 数据库本身不可用时无法写回失败状态，保留进程日志供运维排查。
            print(
                f"数据导入Worker无法收口会话 {run_id}：{finalize_error!r}; 原因：{failure_message}",
                file=sys.stderr,
            )

    def _run_loader(self, task: dict, source: str) -> None:
        spec = REPORT_BY_TYPE[task["report_type"]]
        absolute = self.service.storage_root / task["storage_path"]
        python_executable = next((p for p in ETL_PYTHON_CANDIDATES if p.is_file()), Path(sys.executable))
        command = [
            str(python_executable), '-m', '.'.join(Path(spec.loader).with_suffix('').parts), "--file", str(absolute),
            "--shop-code", task["resolved_shop_code"], "--shop-mapping-source",
            "robot_selected" if source in {"api", "robot"} else "manual_selected",
        ]
        environment = self._subprocess_environment()
        if task['report_type'] == 'jd_settlement':
            claim = task.get('coverage') or {}
            bill_date = claim.get('bill_date') or (claim.get('start') if claim.get('start') == claim.get('end') else None)
            if bill_date:
                command += ['--bill-date',bill_date]
        diagnostics_enabled = False
        with self.service.transaction() as cursor:
            diagnostics_enabled = self._has_file_loader_diagnostics(cursor)
            if diagnostics_enabled:
                cursor.execute(
                    """
                    UPDATE ops.ingest_file_task
                    SET status='processing', attempt_count=attempt_count+1,
                        started_at=NOW(), finished_at=NULL,
                        loader_exit_code=NULL, output_summary=NULL,
                        error_message=NULL, updated_at=NOW()
                    WHERE file_task_id=%s
                    """,
                    (task["file_task_id"],),
                )
            else:
                cursor.execute(
                    """
                    UPDATE ops.ingest_file_task
                    SET status='processing', attempt_count=attempt_count+1,
                        started_at=NOW(), finished_at=NULL,
                        error_message=NULL, updated_at=NOW()
                    WHERE file_task_id=%s
                    """,
                    (task["file_task_id"],),
                )
        try:
            result = subprocess.run(command, cwd=PROJECT_ROOT, env=environment, text=True, capture_output=True, encoding="utf-8", errors="replace", timeout=3600)
            output = (result.stdout or "")[-OUTPUT_LIMIT:]
            error = (result.stderr or "")[-OUTPUT_LIMIT:]
            batch_ids = self._parse_loader_batch_ids(output)
            if result.returncode != 0 or not batch_ids:
                raise RuntimeError(error or output or f"Loader退出码{result.returncode}")
            target_tables = tuple(
                target.split(".", 1)[-1]
                for target in (spec.target_tables or (spec.target_table,))
            )
            with self.service.transaction() as cursor:
                cursor.execute(
                    "SELECT batch_id,target_table FROM ods.ods_file_ingest_log WHERE batch_id = ANY(%s)",
                    (batch_ids,),
                )
                batch_rows = [dict(row) for row in cursor.fetchall()]
                actual_target_tables = {row["target_table"] for row in batch_rows}
                if len(batch_rows) != len(batch_ids) or actual_target_tables != set(target_tables):
                    raise RuntimeError(
                        f"Loader批次目标表不匹配：期望={sorted(target_tables)}，实际={sorted(actual_target_tables)}"
                    )
                primary_batch_id = next(
                    row["batch_id"] for row in batch_rows if row["target_table"] == target_tables[0]
                )
                if diagnostics_enabled:
                    cursor.execute(
                        """
                        UPDATE ops.ingest_file_task
                        SET status='success', batch_id=%s, loader_exit_code=%s,
                            output_summary=%s, error_message=NULL,
                            finished_at=NOW(), updated_at=NOW()
                        WHERE file_task_id=%s
                        """,
                        (primary_batch_id, result.returncode, output or None, task["file_task_id"]),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE ops.ingest_file_task
                        SET status='success', batch_id=%s, error_message=NULL,
                            finished_at=NOW(), updated_at=NOW()
                        WHERE file_task_id=%s
                        """,
                        (primary_batch_id, task["file_task_id"]),
                    )
                cursor.execute(
                    """
                    UPDATE ods.ods_file_ingest_log SET ingest_run_id=%s,ingest_file_task_id=%s,
                        report_type=%s,automation_source=%s,updated_at=NOW()
                    WHERE batch_id = ANY(%s)
                    """,
                    (task["run_id"], task["file_task_id"], task["report_type"], source, batch_ids),
                )
                for row in batch_rows:
                    cursor.execute(
                        """
                        INSERT INTO ops.ingest_file_task_batch(file_task_id,batch_id,target_table)
                        VALUES(%s,%s,%s)
                        ON CONFLICT (file_task_id,batch_id) DO NOTHING
                        """,
                        (task["file_task_id"], row["batch_id"], row["target_table"]),
                    )
        except Exception as exc:
            with self.service.transaction() as cursor:
                failure_message = str(exc)[-OUTPUT_LIMIT:]
                loader_output = output if "output" in locals() else ""
                if not diagnostics_enabled and loader_output:
                    failure_message = (failure_message + "\nLoader标准输出摘要：" + loader_output)[-OUTPUT_LIMIT:]
                if diagnostics_enabled:
                    cursor.execute(
                        """
                        UPDATE ops.ingest_file_task
                        SET status='failed', loader_exit_code=%s,
                            output_summary=%s, error_message=%s,
                            finished_at=NOW(), updated_at=NOW()
                        WHERE file_task_id=%s
                        """,
                        (
                            result.returncode if 'result' in locals() else None,
                            output if 'output' in locals() else None,
                            str(exc)[-OUTPUT_LIMIT:],
                            task["file_task_id"],
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE ops.ingest_file_task
                        SET status='failed', error_message=%s,
                            finished_at=NOW(), updated_at=NOW()
                        WHERE file_task_id=%s
                        """,
                        (failure_message, task["file_task_id"]),
                    )

    @staticmethod
    def _parse_loader_batch_ids(output: str) -> list[int]:
        batch_ids: list[int] = []
        for payload in re.findall(r"导入批次ID：([\d,\s]+)", output):
            for value in payload.split(","):
                text = value.strip()
                if text and text.isdigit():
                    batch_id = int(text)
                    if batch_id not in batch_ids:
                        batch_ids.append(batch_id)
        return batch_ids

    def _process_etl_run(self) -> bool:
        connection = self.service.connect()
        connection.autocommit = True
        run_id = None
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as guard:
                guard.execute("SELECT pg_try_advisory_lock(hashtext('mock_coffice_file_ingest_dispatch')) AS locked")
                if not guard.fetchone()['locked']:
                    return False
                guard.execute("SELECT pg_try_advisory_lock(hashtext('mock_coffice_global_etl')) AS locked")
                if not guard.fetchone()['locked']:
                    return False
                guard.execute("SELECT pg_advisory_unlock(hashtext('mock_coffice_global_etl'))")
            with self.service.transaction() as cursor:
                cursor.execute("SELECT etl_run_id FROM ops.etl_run WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1")
                row = cursor.fetchone()
                if not row:
                    return False
                run_id = row['etl_run_id']
                cursor.execute("""UPDATE ops.etl_run SET status='running',
                    started_at=COALESCE(started_at,NOW()),worker_id=%s,heartbeat_at=NOW(),updated_at=NOW()
                    WHERE etl_run_id=%s""", (str(self.worker_id), run_id))
            python_executable = next((p for p in ETL_PYTHON_CANDIDATES if p.is_file()), Path(sys.executable))
            command = [str(python_executable), '-m', 'apps.file_ingest.etl_executor',
                       '--run-id', str(run_id), '--worker-id', str(self.worker_id)]
            # The executor owns the lock for the whole pipeline and publishes task
            # results itself, even if this web/dispatcher process exits abruptly.
            result = self._execute_etl_process(command, self._subprocess_environment(), run_id,
                                               pulse=False, timeout_seconds=None)
            if result.returncode:
                raise RuntimeError((result.stderr or 'ETL执行进程异常退出')[-OUTPUT_LIMIT:])
            return True
        except Exception as exc:
            if run_id is None:
                raise
            with self.service.transaction() as cursor:
                self._close_interrupted_etl(cursor, run_id, f'ETL运行中断：{exc}'[-OUTPUT_LIMIT:])
            return True
        finally:
            connection.close()

    def _process_claimed_etl_run(self, etl_run_id) -> bool:
        try:
            self._pulse_etl(etl_run_id)
            with self.service.transaction() as cursor:
                cursor.execute(
                    """
                    SELECT t.*, r.ingest_run_id, r.scope, r.trigger_type
                    FROM ops.etl_task t
                    JOIN ops.etl_run r ON r.etl_run_id=t.etl_run_id
                    WHERE t.etl_run_id=%s
                    ORDER BY t.sequence_no
                    """,
                    (etl_run_id,),
                )
                tasks = [dict(row) for row in cursor.fetchall()]
            if tasks:
                with self.service.transaction() as readiness_cursor:
                    deferred_reasons = self.service._deferred_etl_reasons(
                        (ETL_SPECS[task["etl_key"]] for task in tasks if task["etl_key"] in ETL_SPECS),
                        trigger_type=tasks[0].get("trigger_type"),
                        scope=tasks[0].get("scope"),
                        cursor=readiness_cursor,
                    )
                # Persist the same decision before executing any task so an old failed
                # affected run can recover after the user retries one node.
                if deferred_reasons:
                    with self.service.transaction() as cursor:
                        for task in tasks:
                            reason = deferred_reasons.get(task["etl_key"])
                            if reason and task["status"] != "success":
                                cursor.execute(
                                    "UPDATE ops.etl_task SET status='deferred',started_at=NULL,exit_code=NULL,error_message=%s,finished_at=NOW(),updated_at=NOW() WHERE etl_task_id=%s",
                                    (reason, task["etl_task_id"]),
                                )
                                task["status"] = "deferred"
                else:
                    # 兼容修复前已经落库的 deferred 节点：当前调度策略不再
                    # 把空平台视为未就绪，重试该运行时将历史延后节点一并
                    # 重新排队，避免用户必须逐个点击“重试”。
                    stale_deferred = [
                        task for task in tasks
                        if task["status"] == "deferred"
                    ]
                    if stale_deferred:
                        with self.service.transaction() as cursor:
                            cursor.execute(
                                """
                                UPDATE ops.etl_task
                                   SET status='queued',started_at=NULL,finished_at=NULL,
                                       exit_code=NULL,error_message=NULL,output_summary=NULL,
                                       updated_at=NOW()
                                 WHERE etl_task_id = ANY(%s::uuid[])
                                """,
                                ([task["etl_task_id"] for task in stale_deferred],),
                            )
                        for task in stale_deferred:
                            task["status"] = "queued"
            statuses: dict[str, str] = {}
            for task in tasks:
                if self._stop.is_set():
                    raise RuntimeError('后端停止，ETL运行中断；可重试')
                if task["status"] == "success":
                    statuses[task["etl_key"]] = "success"
                    continue
                if task["status"] == "deferred":
                    statuses[task["etl_key"]] = "deferred"
                    continue
                dependencies = task["dependencies"] or []
                dependency_statuses = [statuses.get(key) for key in dependencies]
                if any(status == "deferred" for status in dependency_statuses):
                    reason = "依赖任务来源未就绪，已延后；请补齐来源后重试"
                    with self.service.transaction() as cursor:
                        cursor.execute(
                            "UPDATE ops.etl_task SET status='deferred',started_at=NULL,exit_code=NULL,error_message=%s,finished_at=NOW(),updated_at=NOW() WHERE etl_task_id=%s",
                            (reason, task["etl_task_id"]),
                        )
                    statuses[task["etl_key"]] = "deferred"
                    continue
                if any(status != "success" for status in dependency_statuses):
                    with self.service.transaction() as cursor:
                        cursor.execute("UPDATE ops.etl_task SET status='skipped',started_at=NULL,exit_code=NULL,error_message='依赖任务未成功',finished_at=NOW(),updated_at=NOW() WHERE etl_task_id=%s", (task["etl_task_id"],))
                    statuses[task["etl_key"]] = "skipped"
                    continue
                try:
                    statuses[task["etl_key"]] = self._run_etl_task(task)
                except Exception as exc:
                    # 单个任务的未预期异常不得击穿整个运行：否则运行会永久
                    # 停留在 running，恢复机制反复重排又反复在同一任务崩溃。
                    with self.service.transaction() as cursor:
                        cursor.execute(
                            "UPDATE ops.etl_task SET status='failed',error_message=%s,finished_at=NOW(),updated_at=NOW() WHERE etl_task_id=%s",
                            (f"任务执行出现未预期异常：{exc}"[-OUTPUT_LIMIT:], task["etl_task_id"]),
                        )
                    statuses[task["etl_key"]] = "failed"
            failed = sum(1 for status in statuses.values() if status == "failed")
            skipped = sum(1 for status in statuses.values() if status == "skipped")
            deferred = sum(1 for status in statuses.values() if status == "deferred")
            success = sum(1 for status in statuses.values() if status == "success")
            if failed or skipped:
                final = "failed" if not success else "partial_failed"
            elif deferred:
                final = "success_with_warnings"
            else:
                final = "success" if success else "no_change"
            with self.service.transaction() as cursor:
                error_message = {
                    "success_with_warnings": "存在来源未就绪而延后的任务，请补齐来源后重试",
                    "partial_failed": "存在失败或跳过任务",
                    "failed": "存在失败或跳过任务",
                }.get(final)
                cursor.execute("UPDATE ops.etl_run SET status=%s,error_message=%s,completed_at=NOW(),updated_at=NOW() WHERE etl_run_id=%s", (final, error_message, etl_run_id))
                if final in {"success", "success_with_warnings"}:
                    cursor.execute(
                        """
                        INSERT INTO ops.refresh_watermark(watermark_key,etl_run_id,last_success_at,summary)
                        VALUES('affected',%s,NOW(),%s)
                        ON CONFLICT(watermark_key) DO UPDATE SET etl_run_id=EXCLUDED.etl_run_id,
                            last_success_at=EXCLUDED.last_success_at,summary=EXCLUDED.summary,updated_at=NOW()
                        """,
                        (etl_run_id, Json({"success_tasks": success, "deferred_tasks": deferred})),
                    )
            return True
        except Exception as exc:
            with self.service.transaction() as cursor:
                self._close_interrupted_etl(cursor, etl_run_id, f'ETL运行中断：{exc}'[-OUTPUT_LIMIT:])
            return True

    def _run_etl_task(self, task: dict) -> str:
        spec = ETL_SPECS.get(task["etl_key"])
        if spec is None:
            # 历史运行可能仍排着已下线 ETL 的任务（例如旧天猫结算链路）。
            # 登记入口 plan_etls 会拒绝未知 key，运行期出现未登记 key 只能说明
            # 该 ETL 已退役；按无操作成功收口，避免整个运行永久卡在 running，
            # 并让依赖它的下游共享任务继续执行。
            with self.service.transaction() as cursor:
                cursor.execute(
                    """
                    UPDATE ops.etl_task
                    SET status='success',started_at=COALESCE(started_at,NOW()),exit_code=0,
                        error_message=NULL,output_summary=%s,finished_at=NOW(),updated_at=NOW()
                    WHERE etl_task_id=%s
                    """,
                    (f"ETL未登记或已下线：{task['etl_key']}，无需执行，自动标记完成", task["etl_task_id"]),
                )
            return "success"
        if not spec.enabled:
            with self.service.transaction() as cursor:
                cursor.execute(
                    """
                    UPDATE ops.etl_task
                    SET status='skipped',started_at=NULL,exit_code=NULL,error_message=%s,finished_at=NOW(),updated_at=NOW()
                    WHERE etl_task_id=%s
                    """,
                    (f"ETL已停用：{spec.note or spec.label}", task["etl_task_id"]),
                )
            return "skipped"
        python_executable = next(
            (path for path in ETL_PYTHON_CANDIDATES if path.is_file()),
            Path(sys.executable),
        )
        context = None
        if task['etl_key'] != 'bank_management' and task.get('trigger_type') != 'bank_submit':
            from .refresh_scope import ensure_refresh_context
            context = ensure_refresh_context(self.service, task['etl_run_id'])
            command = [str(python_executable), '-m', 'etl.common.refresh_entrypoint',
                       '--etl-key', task['etl_key']]
        else:
            # A bank submission is an explicit finance operation over locked
            # bank batches, independent of merchant file-import refreshes.
            command = [str(python_executable), '-m',
                       '.'.join(spec.command_path.relative_to(PROJECT_ROOT).with_suffix('').parts), *spec.args]
        if task['etl_key'] == 'platform_main_business_income_shared_ads' and task.get('scope') == 'affected':
            command.append('--allow-partial')
        environment = self._subprocess_environment()
        environment['MOCK_COFFICE_ETL_LOCK_HELD'] = '1'
        if context is not None:
            environment['MOCK_COFFICE_REFRESH_CONTEXT'] = json.dumps(context, ensure_ascii=False)
        observation = self.service.snapshot_diagnostics(context,[task['etl_key']])
        with self.service.transaction() as cursor:
            cursor.execute("UPDATE ops.etl_task SET status='running',attempt_count=attempt_count+1,started_at=NOW(),finished_at=NULL,exit_code=NULL,error_message=NULL,updated_at=NOW() WHERE etl_task_id=%s", (task["etl_task_id"],))
        try:
            result = self._execute_etl_process(command, environment, task['etl_run_id'])
            metrics = self._extract_metrics(result.stdout or '')
            output = (result.stdout or "")[-OUTPUT_LIMIT:]
            error = (result.stderr or "")[-OUTPUT_LIMIT:]
            status = "success" if result.returncode == 0 else "deferred" if result.returncode == 3 else "failed"
            if status == 'failed':
                observation = self.service.snapshot_diagnostics(context,[task['etl_key']])
                if observation.get('snapshot_stale'):
                    error = (error + '\n' + observation['message'])[-OUTPUT_LIMIT:]
            metrics['source_snapshot'] = observation
            if status == "failed" and task.get("ingest_run_id"):
                with self.service.transaction() as context_cursor:
                    context_cursor.execute(
                        """
                        SELECT source_file_name, report_type, status, batch_id
                        FROM ops.ingest_file_task
                        WHERE run_id=%s
                        ORDER BY created_at
                        LIMIT 50
                        """,
                        (task["ingest_run_id"],),
                    )
                    source_files = [
                        f"{row['source_file_name']} [{row['report_type']}, {row['status']}, batch={row['batch_id'] or '—'}]"
                        for row in context_cursor.fetchall()
                    ]
                if source_files:
                    error = (error or "ETL进程返回失败") + "\n本次导入会话ODS文件：" + "；".join(source_files)
                    error = error[:OUTPUT_LIMIT]
            with self.service.transaction() as cursor:
                cursor.execute(
                    """
                    UPDATE ops.etl_task SET status=%s,exit_code=%s,output_summary=%s,error_message=%s,result_metrics=%s,
                        finished_at=NOW(),updated_at=NOW() WHERE etl_task_id=%s
                    """,
                    (status, result.returncode, output, error or None, Json(metrics), task["etl_task_id"]),
                )
            return status
        except Exception as exc:
            with self.service.transaction() as cursor:
                cursor.execute("UPDATE ops.etl_task SET status='failed',error_message=%s,finished_at=NOW(),updated_at=NOW() WHERE etl_task_id=%s", (str(exc)[-OUTPUT_LIMIT:], task["etl_task_id"]))
            return "failed"

    def _subprocess_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update({
            "PGHOST": str(self.service.connect_kwargs["host"]),
            "PGPORT": str(self.service.connect_kwargs["port"]),
            "PGDATABASE": str(self.service.connect_kwargs["dbname"]),
            "PGUSER": str(self.service.connect_kwargs["user"]),
        })
        password = self.service.connect_kwargs.get("password")
        if password:
            environment["PGPASSWORD"] = str(password)
        return environment

    @staticmethod
    def _extract_metrics(output: str) -> dict:
        validation_lines = [
            line.strip() for line in output.splitlines()
            if any(marker in line for marker in ("行数", "日期范围", "合计", "汇总", "未匹配", "唯一", "警告", "延后", "未映射"))
        ]
        refresh = []
        for line in output.splitlines():
            if line.startswith('[REFRESH_METRICS] '):
                try:
                    refresh.append(json.loads(line.removeprefix('[REFRESH_METRICS] ')))
                except (ValueError, TypeError):
                    continue
        result = {"validation_lines": validation_lines[-100:], "refresh": refresh}
        for line in output.splitlines():
            if line.startswith('[WALLET_RECONCILIATION] '):
                try:
                    result['wallet_reconciliation']=json.loads(line.removeprefix('[WALLET_RECONCILIATION] '))
                except (ValueError,TypeError):
                    pass
        return result
