"""快手 capability declarations. No network or browser work at import time."""
from ...core.contracts import BackendSpec, PlatformSpec, ReportSpec

PLATFORM = PlatformSpec(
    id="kuaishou", name="快手", aliases=("ks",),
    backends=(
        BackendSpec("kuaishou", "merchant", "快手小店", ("s.kwaixiaodian.com", "syt.kwaixiaodian.com", "www.kwaixiaodian.com",), "https://s.kwaixiaodian.com/zone/home", "commerce_api.platforms.kuaishou.backends.merchant.client:Client", "kuaishou.merchant", None),
        BackendSpec("kuaishou", "finance", "快手财务", ("s.kwaixiaodian.com", "syt.kwaixiaodian.com", "pay.kuaishou.com",), "https://s.kwaixiaodian.com/zone/home", "commerce_api.platforms.kuaishou.backends.finance.client:Client", "kuaishou.finance", None),
    ),
    reports=(
        ReportSpec("kuaishou", "order", "merchant", "订单", "commerce_api.platforms.kuaishou.services.reports.orders:download", default_period="last30", sources=("ReverseAPI/Formal_Script/kuaishou_webapi_download.py",)),
        ReportSpec("kuaishou", "fund", "finance", "资金", "commerce_api.platforms.kuaishou.services.reports.funds:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/kuaishou_webapi_download.py",)),
        ReportSpec("kuaishou", "settlement", "finance", "结算", "commerce_api.platforms.kuaishou.services.reports.settlements:download", default_period="yesterday", sources=("ReverseAPI/Formal_Script/kuaishou_webapi_download.py",)),
    ),
)

