"""小红书 capability declarations. No network or browser work at import time."""
from ...core.contracts import BackendSpec, PlatformSpec, ReportSpec

PLATFORM = PlatformSpec(
    id="xiaohongshu", name="小红书", aliases=("xhs",),
    backends=(
        BackendSpec("xiaohongshu", "merchant", "千帆商家后台", ("ark.xiaohongshu.com",), "https://ark.xiaohongshu.com/", "commerce_api.platforms.xiaohongshu.backends.merchant.client:Client", "xiaohongshu.merchant", None),
    ),
    reports=(
        ReportSpec("xiaohongshu", "order", "merchant", "订单", "commerce_api.platforms.xiaohongshu.services.reports.orders:download", default_period="last30", sources=("ReverseAPI/Formal_Script/xiaohongshu_webapi_download.py",)),
        ReportSpec("xiaohongshu", "fund", "merchant", "资金", "commerce_api.platforms.xiaohongshu.services.reports.funds:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/xiaohongshu_webapi_download.py",)),
        ReportSpec("xiaohongshu", "settlement", "merchant", "结算", "commerce_api.platforms.xiaohongshu.services.reports.settlements:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/xiaohongshu_webapi_download.py",)),
    ),
)

