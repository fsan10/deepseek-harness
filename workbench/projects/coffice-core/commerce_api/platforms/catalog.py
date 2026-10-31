"""Only metadata is imported here; handlers and browser adapters load on demand."""
from __future__ import annotations


def platforms():
    from .douyin.manifest import PLATFORM as douyin
    from .jd.manifest import PLATFORM as jd
    from .pinduoduo.manifest import PLATFORM as pinduoduo
    from .kuaishou.manifest import PLATFORM as kuaishou
    from .xiaohongshu.manifest import PLATFORM as xiaohongshu
    from .tmall.manifest import PLATFORM as tmall
    return (douyin, jd, pinduoduo, kuaishou, xiaohongshu, tmall)

