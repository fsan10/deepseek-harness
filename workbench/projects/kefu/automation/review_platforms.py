"""平台能力注册表；未实现的平台明确返回 NOT_SUPPORTED。"""
from .review_errors import NotSupported

PLATFORMS = {"douyin": {"id": "douyin", "name": "抖音", "transport": "direct_http", "browser": "login_only",
                         "capabilities": ["auth.login", "auth.status", "reviews.fetch", "reviews.collect", "reviews.status", "reviews.retry"]}}

from .metric_profiles import PLATFORMS as METRIC_PLATFORMS
for key, spec in METRIC_PLATFORMS.items():
    info = PLATFORMS.setdefault(key, {"id": key, "name": spec["name"], "transport": "direct_http", "browser": "login_only", "capabilities": []})
    info["capabilities"] += ["metrics.auth.login", "metrics.auth.status", "reception.fetch", "reception.collect", "reception.status", "reception.retry"]
    if spec["score"]: info["capabilities"] += ["score.fetch", "score.collect", "score.status", "score.retry"]


def platform_info(platform: str):
    key = next((key for key, spec in PLATFORMS.items() if platform in (key, spec["name"])), platform)
    if key not in PLATFORMS:
        raise NotSupported("该平台尚未实现，请运行 commerce platforms 查看支持范围")
    return PLATFORMS[key]
