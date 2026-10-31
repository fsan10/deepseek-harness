from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp, parse, parse_one
from sqlglot.errors import ParseError


class SqlRejected(ValueError):
    http_status = 403


DANGEROUS_FUNCTIONS = {
    "pg_sleep", "dblink", "dblink_exec", "lo_export", "lo_import", "lo_unlink",
    "pg_read_file", "pg_read_binary_file", "pg_write_file", "setval", "nextval",
    "currval", "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf",
}
SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Alter, exp.Drop,
    exp.Command, exp.Copy, exp.Grant, exp.Revoke, exp.Into,
)


@dataclass(frozen=True, slots=True)
class ValidatedQuery:
    sql: str
    tables: tuple[str, ...]
    columns: tuple[str, ...]
    limit: int | None


class ReadonlySqlValidator:
    def validate(self, sql: str, *, allowed_tables: set[str], allowed_columns: set[str]) -> ValidatedQuery:
        if not isinstance(sql, str) or not sql.strip():
            raise SqlRejected("SQL不能为空")
        normalized = sql.strip()
        explain = normalized.upper().startswith("EXPLAIN ")
        if explain:
            if normalized.upper().startswith("EXPLAIN ANALYZE") or "ANALYZE TRUE" in normalized.upper():
                raise SqlRejected("禁止EXPLAIN ANALYZE")
            normalized = normalized[7:].strip()
        try:
            statements = parse(normalized, read="postgres")
        except ParseError as exc:
            raise SqlRejected("SQL语法无法安全解析") from exc
        if len(statements) != 1 or statements[0] is None:
            raise SqlRejected("只允许一条SQL语句")
        tree = statements[0]
        if any(tree.find(node_type) is not None for node_type in FORBIDDEN_NODES):
            raise SqlRejected("只允许只读SELECT查询")
        root_query = tree
        if not isinstance(root_query, (exp.Select, exp.Union, exp.Intersect, exp.Except)) and root_query.find(exp.Select) is None:
            raise SqlRejected("仅支持SELECT或WITH ... SELECT")

        tables: set[str] = set()
        alias_to_table: dict[str, str] = {}
        aliases = {alias.alias_or_name for alias in tree.find_all(exp.CTE)}
        for table in tree.find_all(exp.Table):
            if table.name in aliases and not table.db:
                continue
            schema = (table.db or "").lower()
            if not schema:
                raise SqlRejected("业务表必须显式指定schema")
            if schema in SYSTEM_SCHEMAS or schema.startswith("pg_"):
                raise SqlRejected("系统目录只能通过受控元数据工具访问")
            key = f"{schema}.{table.name.lower()}"
            if key not in {item.lower() for item in allowed_tables}:
                raise SqlRejected("查询包含未授权表或视图")
            tables.add(key)
            alias_to_table[(table.alias_or_name or table.name).lower()] = key
            alias_to_table[table.name.lower()] = key

        if not tables:
            raise SqlRejected("查询必须访问已授权业务表")
        for star in tree.find_all(exp.Star):
            if isinstance(star.parent, exp.Count):
                continue
            raise SqlRejected("禁止SELECT *，必须显式选择已授权字段")
        for function in tree.find_all(exp.Func):
            name = str(getattr(function, "name", "") or function.sql_name()).lower()
            if name in DANGEROUS_FUNCTIONS or name.startswith(("dblink", "lo_", "pg_read_", "pg_write_")):
                raise SqlRejected("查询包含危险数据库函数")

        columns: set[str] = set()
        allowed_lower = {item.lower() for item in allowed_columns}
        projection_aliases = {
            str(alias.alias).lower() for alias in tree.find_all(exp.Alias) if alias.alias
        }
        for column in tree.find_all(exp.Column):
            if column.is_star:
                raise SqlRejected("禁止SELECT *，必须显式选择已授权字段")
            name = column.name.lower()
            qualifier = (column.table or "").lower()
            if not qualifier and name in projection_aliases and self._is_order_or_group_reference(column):
                continue
            if qualifier and qualifier in alias_to_table:
                matches = {f"{alias_to_table[qualifier]}.{name}"} & allowed_lower
            else:
                matches = {item for item in allowed_lower if item.rsplit(".", 1)[0] in tables and item.endswith(f".{name}")}
            if not matches or (not qualifier and len(matches) > 1):
                raise SqlRejected("查询包含未授权字段")
            columns.update(matches)

        select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
        current_limit = select.args.get("limit") if select else None
        safe_sql = tree.sql(dialect="postgres")
        if explain:
            safe_sql = "EXPLAIN " + safe_sql
        explicit_limit = self._limit_value(current_limit) if current_limit is not None else None
        return ValidatedQuery(safe_sql, tuple(sorted(tables)), tuple(sorted(columns)), explicit_limit)

    @staticmethod
    def _is_order_or_group_reference(column: exp.Column) -> bool:
        parent = column.parent
        while parent is not None and not isinstance(parent, exp.Select):
            if isinstance(parent, (exp.Order, exp.Group)):
                return True
            parent = parent.parent
        return False

    @staticmethod
    def _limit_value(limit: exp.Limit) -> int:
        expression = limit.expression
        try:
            return int(expression.this) if isinstance(expression, exp.Literal) else 10**12
        except (TypeError, ValueError):
            return 10**12

    def validate_row_filter(self, expression_sql: str, *, allowed_columns: set[str]) -> str:
        try:
            tree = parse(f"SELECT 1 WHERE {expression_sql}", read="postgres")[0]
        except (ParseError, IndexError) as exc:
            raise SqlRejected("行级过滤规则语法无效") from exc
        if tree.find(exp.Subquery) or tree.find(exp.Table) or any(tree.find(t) for t in FORBIDDEN_NODES):
            raise SqlRejected("行级过滤规则只能是字段与常量组成的布尔表达式")
        allowed_names = {key.rsplit(".", 1)[-1].lower() for key in allowed_columns}
        for column in tree.find_all(exp.Column):
            if column.name.lower() not in allowed_names:
                raise SqlRejected("行级过滤包含未授权字段")
        for function in tree.find_all(exp.Func):
            name = str(getattr(function, "name", "") or function.sql_name()).lower()
            if name not in {"lower", "upper", "coalesce", "date_trunc"}:
                raise SqlRejected("行级过滤包含未允许函数")
        return tree.args["where"].this.sql(dialect="postgres")

    def inject_row_filter(self, validated_sql: str, expression_sql: str) -> str:
        """把管理员规则注入单表SELECT的WHERE；复杂查询拒绝而不是降级放行。"""
        explain = validated_sql.upper().startswith("EXPLAIN ")
        sql_body = validated_sql[7:].strip() if explain else validated_sql
        tree = parse_one(sql_body, read="postgres")
        if tree.find(exp.With) is not None or len(list(tree.find_all(exp.Table))) != 1:
            raise SqlRejected("带行级权限的数据仅支持单表查询")
        target = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
        if target is None:
            raise SqlRejected("无法安全注入行级权限")
        condition = parse_one(f"SELECT 1 WHERE {expression_sql}", read="postgres").args["where"].this
        target.where(condition, append=True, copy=False)
        rendered = tree.sql(dialect="postgres")
        return "EXPLAIN " + rendered if explain else rendered
