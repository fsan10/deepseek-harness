"""拼多多 capability declarations. No network or browser work at import time."""
from ...core.contracts import BackendSpec, PlatformSpec, ReportSpec

PLATFORM = PlatformSpec(
    id="pinduoduo", name="拼多多", aliases=("pdd",),
    backends=(
        BackendSpec("pinduoduo", "merchant", "商家后台", ("mms.pinduoduo.com",), "https://mms.pinduoduo.com/home", "commerce_api.platforms.pinduoduo.backends.merchant.client:Client", "pinduoduo.merchant", None),
        BackendSpec("pinduoduo", "cashier", "对账中心", ("mms.pinduoduo.com", "cashier.pinduoduo.com",), "https://mms.pinduoduo.com/home", "commerce_api.platforms.pinduoduo.backends.cashier.client:Client", "pinduoduo.cashier", None),
        BackendSpec("pinduoduo", "promotion", "推广平台", ("yingxiao.pinduoduo.com", "mms.pinduoduo.com",), "https://yingxiao.pinduoduo.com/", "commerce_api.platforms.pinduoduo.backends.promotion.client:Client", "pinduoduo.promotion", None),
    ),
    reports=(
        ReportSpec("pinduoduo", "order", "merchant", "订单", "commerce_api.platforms.pinduoduo.services.reports.orders:download", default_period="last30", sources=("ReverseAPI/Formal_Script/pinduoduo_webapi_download.py",)),
        ReportSpec("pinduoduo", "settlement", "cashier", "结算", "commerce_api.platforms.pinduoduo.services.reports.settlements:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/pinduoduo_webapi_download.py",)),
        ReportSpec("pinduoduo", "promotion", "promotion", "推广费", "commerce_api.platforms.pinduoduo.services.reports.promotion:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/pinduoduo_webapi_download.py",)),
    ),
)

