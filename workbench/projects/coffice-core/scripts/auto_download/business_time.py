# -*- coding: utf-8 -*-
"""Shanghai business time shared by the download controller and report dates."""

from datetime import datetime
from time import struct_time
from zoneinfo import ZoneInfo


CHINA_TIME_ZONE = "Asia/Shanghai"


def china_now() -> datetime:
    return datetime.now(ZoneInfo(CHINA_TIME_ZONE))


def china_localtime(timestamp: float) -> struct_time:
    return datetime.fromtimestamp(timestamp, ZoneInfo(CHINA_TIME_ZONE)).timetuple()
