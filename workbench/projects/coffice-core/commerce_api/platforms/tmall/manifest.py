"""天猫 capability declarations. No network or browser work at import time."""
from ...core.contracts import BackendSpec, PlatformSpec, ReportSpec

PLATFORM = PlatformSpec(
    id="tmall", name="天猫", aliases=("taobao",),
    backends=(
        BackendSpec("tmall", "qianniu", "千牛", ("myseller.taobao.com", "trade.taobao.com", "h5api.m.taobao.com",), "https://myseller.taobao.com/home.htm", "commerce_api.platforms.tmall.backends.qianniu.client:Client", "tmall.qianniu", None),
        BackendSpec("tmall", "aggregate", "聚合账户", ("myseller.taobao.com", "trade.taobao.com", "h5api.m.taobao.com",), "https://myseller.taobao.com/home.htm", "commerce_api.platforms.tmall.backends.aggregate.client:Client", "tmall.aggregate", "tmall.qianniu"),
        BackendSpec("tmall", "alipay", "支付宝", ("b.alipay.com", "mbillexprod.alipay.com", "h5api.m.taobao.com",), "https://b.alipay.com/", "commerce_api.platforms.tmall.backends.alipay.client:Client", "tmall.alipay", "tmall.qianniu"),
        BackendSpec("tmall", "alimama", "淘宝联盟", ("ad.alimama.com", "h5api.m.taobao.com",), "https://ad.alimama.com/", "commerce_api.platforms.tmall.backends.alimama.client:Client", "tmall.alimama", "tmall.qianniu"),
        BackendSpec("tmall", "wanxiangtai", "万相台", ("one.alimama.com", "ad.alimama.com", "stlacct.alimama.com", "h5api.m.taobao.com",), "https://one.alimama.com/", "commerce_api.platforms.tmall.backends.wanxiangtai.client:Client", "tmall.wanxiangtai", "tmall.qianniu"),
    ),
    reports=(
        ReportSpec("tmall", "order", "qianniu", "订单", "commerce_api.platforms.tmall.services.reports.orders:download", default_period="last30", sources=("ReverseAPI/Formal_Script/tmall_webapi_download.py",)),
        ReportSpec("tmall", "fund", "aggregate", "聚合账户资金", "commerce_api.platforms.tmall.services.reports.funds:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/tmall_webapi_download.py",)),
        ReportSpec("tmall", "fund", "alipay", "支付宝账户资金", "commerce_api.platforms.tmall.services.reports.funds:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/tmall_webapi_download.py",)),
        ReportSpec("tmall", "promotion", "alimama", "淘宝联盟推广费", "commerce_api.platforms.tmall.services.reports.promotion:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/tmall_webapi_download.py",)),
        ReportSpec("tmall", "promotion", "wanxiangtai", "万相台推广费", "commerce_api.platforms.tmall.services.reports.promotion:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/tmall_webapi_download.py",)),
    ),
)

