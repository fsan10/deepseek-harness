"""数据接入与自动化 单元入口。

单元只装配零依赖外壳；业务实现仍在 apps/ 下原样保留，未做任何改写。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
UNIT = os.path.dirname(HERE)
RUNTIME = os.path.abspath(os.path.join(UNIT, "..", "..", "runtime"))
sys.path.insert(0, RUNTIME)
os.environ["WB_UNIT_ROOT"] = UNIT

from unit_app import main  # noqa: E402  (路径先注入，再导入外壳)

if __name__ == "__main__":
    main()
