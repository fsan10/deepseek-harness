"""抖音 capability declarations. No network or browser work at import time."""
from ...core.contracts import BackendSpec, PlatformSpec, ReportSpec

PLATFORM = PlatformSpec(
    id="douyin", name="抖音", aliases=("dy",),
    backends=(
        BackendSpec("douyin", "merchant", "抖店", ("fxg.jinritemai.com",), "https://fxg.jinritemai.com/ffa/mhome/home", "commerce_api.platforms.douyin.backends.merchant.client:Client", "douyin.merchant", None),
        BackendSpec("douyin", "qianchuan", "巨量千川", ("qianchuan.jinritemai.com", "business.oceanengine.com", "ad.oceanengine.com",), "https://business.oceanengine.com/", "commerce_api.platforms.douyin.backends.qianchuan.client:Client", "douyin.qianchuan", "douyin.merchant"),
    ),
    reports=(
        ReportSpec("douyin", "order", "merchant", "订单", "commerce_api.platforms.douyin.services.reports.orders:download", default_period="last30", sources=("ReverseAPI/Formal_Script/douyin_webapi_download.py",)),
        ReportSpec("douyin", "fund", "merchant", "资金", "commerce_api.platforms.douyin.services.reports.funds:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/douyin_webapi_download.py",)),
        ReportSpec("douyin", "settlement", "merchant", "结算", "commerce_api.platforms.douyin.services.reports.settlements:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/douyin_webapi_download.py",)),
        ReportSpec("douyin", "promotion", "qianchuan", "千川推广费", "commerce_api.platforms.douyin.services.reports.promotion:download", default_period="yesterday", sources=("scripts/auto_download/playwright/qianchuan_promotion_fee_download.py",)),
    ),
)

