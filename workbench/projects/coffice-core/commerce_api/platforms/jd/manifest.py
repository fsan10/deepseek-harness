"""京东 capability declarations. No network or browser work at import time."""
from ...core.contracts import BackendSpec, PlatformSpec, ReportSpec

PLATFORM = PlatformSpec(
    id="jd", name="京东", aliases=(),
    backends=(
        BackendSpec("jd", "merchant", "京麦", ("shop.jd.com", "sff.jd.com", "ddmall.jd.com",), "https://shop.jd.com/jdm/home", "commerce_api.platforms.jd.backends.merchant.client:Client", "jd.merchant", None),
        BackendSpec("jd", "promotion", "京准通", ("jzt.jd.com", "jzt-api.jd.com", "atoms-api.jd.com", "ddmall.jd.com",), "https://jzt.jd.com/", "commerce_api.platforms.jd.backends.promotion.client:Client", "jd.promotion", None),
    ),
    reports=(
        ReportSpec("jd", "order", "merchant", "订单", "commerce_api.platforms.jd.services.reports.orders:download", default_period="last30", sources=("ReverseAPI/Formal_Script/jd_webapi_download.py",)),
        ReportSpec("jd", "fund", "merchant", "资金", "commerce_api.platforms.jd.services.reports.funds:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/jd_webapi_download.py",)),
        ReportSpec("jd", "settlement", "merchant", "结算", "commerce_api.platforms.jd.services.reports.settlements:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/jd_webapi_download.py",)),
        ReportSpec("jd", "promotion", "promotion", "京东联盟和京东通推广费", "commerce_api.platforms.jd.services.reports.promotion:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/jd_webapi_download.py",)),
    ),
)

