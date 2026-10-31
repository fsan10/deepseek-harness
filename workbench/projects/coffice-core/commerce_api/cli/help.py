"""Build command parsers from capability metadata without loading handlers."""
from __future__ import annotations

import argparse

from ..core.errors import UsageError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message, hint=f"{self.prog} --help")


def common_auth(parser, platform):
    parser.add_argument("--profile", required=True, help="完整 Cloak Profile 名称")
    parser.add_argument("--backend", choices=[b.id for b in platform.backends], default=platform.backends[0].id)
    parser.add_argument("--account-id", help="显式广告账户或二级账户标识")


def build_parser(registry):
    root = Parser(prog="commerce", description="统一商家 API CLI；现有 DOM 下载与定时任务保持独立")
    root.add_argument("--runtime-dir", help="新项目运行数据根目录；默认 commerce_api/.runtime")
    root.add_argument("--env-file", help="仅在当前进程加载指定 .env，未指定时复用原项目 .env")
    root.add_argument("--legacy-root", help="现有登录/群回复适配器所在项目目录")
    root.add_argument("--version", action="store_true")
    commands = root.add_subparsers(dest="command")
    listing = commands.add_parser("platforms", help="平台、后台和报表能力")
    listing.add_argument("platform", nargs="?")
    schema = commands.add_parser("schema", help="输出结构化参数与能力声明")
    schema.add_argument("platform")
    schema.add_argument("resource", nargs="?", default="report", choices=["report"])
    schema.add_argument("action", nargs="?", default="download", choices=["download"])
    commands.add_parser("doctor", help="检查本地能力和依赖，不连接浏览器")
    profiles = commands.add_parser("profiles", help="缓存账号；显式刷新只读发现 Profile")
    profiles.add_argument("action", choices=["list", "sync"])
    batch = commands.add_parser("batch", help="独立的多平台串行计划")
    batch.add_argument("action", choices=["run", "resume"])
    batch.add_argument("--plan")
    batch.add_argument("--id")
    batch.add_argument("--no-login-recovery", action="store_true")
    run = commands.add_parser("run", help="查看或恢复冻结的原任务")
    run.add_argument("action", choices=["status", "resume"])
    run.add_argument("--id", required=True)
    run.add_argument("--no-login-recovery", action="store_true")
    run.add_argument("--human-timeout", type=int, default=300, help="本次等待群回复的秒数，1 到 300；不改变 Challenge 有效期")
    health = commands.add_parser("health", help="默认关闭的后台认证检查")
    health.add_argument("action", choices=["policy", "configure", "run", "watch"])
    health.add_argument("--enabled", choices=["true", "false"])
    health.add_argument("--profile")
    health.add_argument("--platform")
    health.add_argument("--backend")
    health.add_argument("--interval-minutes", type=int)
    health.add_argument("--due", action="store_true")
    health.add_argument("--tick-seconds", type=int, default=60)
    for platform in registry.platforms.values():
        parser = commands.add_parser(platform.id, aliases=list(platform.aliases), help=platform.name)
        parser.set_defaults(platform_id=platform.id)
        resources = parser.add_subparsers(dest="resource")
        auth = resources.add_parser("auth", help="现有 DOM 认证与 HTTP 身份检查")
        auth_actions = auth.add_subparsers(dest="action")
        for action in ["login", "status", "logout"]:
            common_auth(auth_actions.add_parser(action), platform)
        reports = resources.add_parser("report", help="订单、结算、资金和推广费")
        actions = reports.add_subparsers(dest="action")
        actions.add_parser("list")
        download = actions.add_parser("download", help="独立 HTTP 报表下载")
        common_auth(download, platform)
        # Backend is resolved from the report kind when it is unambiguous.
        download.set_defaults(backend=None)
        download.add_argument("--kind", required=True, choices=sorted({s.kind for s in platform.reports}))
        date = download.add_mutually_exclusive_group()
        date.add_argument("--date")
        date.add_argument("--month")
        date.add_argument("--from", dest="start")
        download.add_argument("--to", dest="end")
        download.add_argument("--timeout", type=float, default=300)
        download.add_argument("--poll-interval", type=float, default=3)
        download.add_argument("--no-login-recovery", action="store_true", help="验证 HTTP 独立性时禁止浏览器恢复")
        download.add_argument("--human-timeout", type=int, default=300)
    # A convenience entry for the seventh operational scope shares the exact
    # Douyin implementation/registry. It cannot select the merchant backend.
    qc = commands.add_parser("qianchuan", help="巨量千川（抖音的独立后台）")
    qc.set_defaults(platform_id="douyin")
    resources = qc.add_subparsers(dest="resource")
    auth = resources.add_parser("auth")
    actions = auth.add_subparsers(dest="action")
    for action in ("login", "status", "logout"):
        option = actions.add_parser(action)
        option.add_argument("--profile", required=True)
        option.add_argument("--account-id")
        option.set_defaults(backend="qianchuan")
    reports = resources.add_parser("report")
    actions = reports.add_subparsers(dest="action")
    actions.add_parser("list")
    option = actions.add_parser("download")
    option.set_defaults(backend="qianchuan", kind="promotion")
    option.add_argument("--profile", required=True)
    option.add_argument("--account-id")
    dates = option.add_mutually_exclusive_group()
    dates.add_argument("--date")
    dates.add_argument("--month")
    dates.add_argument("--from", dest="start")
    option.add_argument("--to", dest="end")
    option.add_argument("--timeout", type=float, default=300)
    option.add_argument("--poll-interval", type=float, default=3)
    option.add_argument("--no-login-recovery", action="store_true")
    option.add_argument("--human-timeout", type=int, default=300)
    return root
