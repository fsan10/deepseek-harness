from scripts import parse_tmall_experience_score as MODULE


PERFORMANCE_HTML = """
<div class="PerformanceMetrics--container--randomHash">
  <span class="PerformanceMetrics--time--x">更新时间：<span>2026-07-14</span></span>
  <div class="PerformanceMetricsTable--container--x">
    <div class="PerformanceMetricsTable--listName--x" id="voc-shop-performance-newGoods-v2025">
      <span class="PerformanceMetricsTable--name--x">宝贝质量</span>
    </div>
    <div class="PerformanceMetricsTableList--listItem--x">
      <span class="PerformanceMetricsTableList--metricsName--x">商品负反馈率</span>
      <span class="RankContainer--rankValue--x">0.1124%</span>
    </div>
    <div class="PerformanceMetricsTableList--listItem--x">
      <span class="PerformanceMetricsTableList--metricsName--x">商品好评率</span>
      <span class="RankContainer--rankValue--x">97.66%</span>
    </div>
  </div>
  <div class="PerformanceMetricsTable--container--anotherHash">
    <div class="PerformanceMetricsTable--listName--x" id="voc-shop-performance-newLogistics-v2025">
      <span class="PerformanceMetricsTable--name--x">物流速度</span>
    </div>
    <div class="PerformanceMetricsTableList--listItem--x">
      <span class="PerformanceMetricsTableList--metricsName--x">48小时揽收及时率</span>
      <span class="RankContainer--rankValue--x">99.94%</span>
    </div>
    <div class="PerformanceMetricsTableList--listItem--x">
      <span class="PerformanceMetricsTableList--metricsName--x">物流到货时长</span>
      <span class="RankContainer--rankValue--x">47.09<span>小时</span></span>
    </div>
  </div>
  <div class="PerformanceMetricsTable--container--newHash">
    <div class="PerformanceMetricsTable--listName--x" id="voc-shop-performance-newServices-v2025">
      <span class="PerformanceMetricsTable--name--x">服务保障</span>
    </div>
    <div class="PerformanceMetricsTableList--listItem--x">
      <span class="PerformanceMetricsTableList--metricsName--x">3分钟人工响应率</span>
      <span class="RankContainer--rankValue--x">99.78%</span>
    </div>
    <div class="PerformanceMetricsTableList--listItem--x">
      <span class="PerformanceMetricsTableList--metricsName--x">旺旺满意度</span>
      <span class="RankContainer--rankValue--x">95.75%</span>
    </div>
    <div class="PerformanceMetricsTableList--listItem--x">
      <span class="PerformanceMetricsTableList--metricsName--x">退款处理时长</span>
      <span class="RankContainer--rankValue--x">0.32<span>小时</span></span>
    </div>
    <div class="PerformanceMetricsTableList--listItem--x">
      <span class="PerformanceMetricsTableList--metricsName--x">平台求助率</span>
      <span class="RankContainer--rankValue--x">0.0000%</span>
    </div>
  </div>
</div>
"""

SCORE_HTML = """
<div class="ScoreDetails--container--randomHash">
  <div class="ScoreDetails--firstItem--x">
    <span class="ScoreDetails--firstItemName--x">真实体验分</span>
    <span class="ScoreDetails--firstItemScore--x">5.00</span>
  </div>
  <div class="ScoreDetails--item--x">
    <span class="ScoreDetails--itemName--x">宝贝质量</span>
    <span class="ScoreDetails--itemScore--x">4.97</span>
  </div>
  <div class="ScoreDetails--item--y">
    <span class="ScoreDetails--itemName--x">物流速度</span>
    <span class="ScoreDetails--itemScore--x">4.96</span>
  </div>
  <div class="ScoreDetails--item--z">
    <span class="ScoreDetails--itemName--x">服务保障</span>
    <span class="ScoreDetails--itemScore--x">5.00</span>
  </div>
</div>
"""

CONSULTATION_HTML = """
<div class="index-group-level-1 consult-monitor-overview-index">
  <div class="index-line level-1">
    <span class="index-label level-1"><span class="text">咨询人数</span></span>
  </div>
  <div class="index-line level-1">
    <div class="index-value level-1"><span class="numbervalue"><span class="number-prefix"></span>34</span></div>
  </div>
  <div class="index-group-level-2">
    <div class="index-value level-2"><span class="numbervalue up"><span class="number-prefix">+</span>17.24%</span></div>
    <div class="index-value level-2"><span class="numbervalue">34</span></div>
  </div>
</div>
"""


def test_parse_user_samples():
    result = MODULE.parse_tmall_blocks(PERFORMANCE_HTML, SCORE_HTML)

    assert result["数据日期"] == "2026-07-14"
    assert result["一级指标"] == {
        "真实体验分": "5.00",
        "宝贝质量": "4.97",
        "物流速度": "4.96",
        "服务保障": "5.00",
    }
    assert result["指标明细"] == {
        "宝贝质量": [
            {"指标名称": "商品负反馈率", "指标值": "0.1124%"},
            {"指标名称": "商品好评率", "指标值": "97.66%"},
        ],
        "物流速度": [
            {"指标名称": "48小时揽收及时率", "指标值": "99.94%"},
            {"指标名称": "物流到货时长", "指标值": "47.09小时"},
        ],
        "服务保障": [
            {"指标名称": "3分钟人工响应率", "指标值": "99.78%"},
            {"指标名称": "旺旺满意度", "指标值": "95.75%"},
            {"指标名称": "退款处理时长", "指标值": "0.32小时"},
            {"指标名称": "平台求助率", "指标值": "0.0000%"},
        ],
    }


def test_flatten_result_keeps_group_in_column_name():
    flat = MODULE.yingdao_parse(PERFORMANCE_HTML, SCORE_HTML)

    assert flat["真实体验分"] == "5.00"
    assert flat["宝贝质量/商品负反馈率"] == "0.1124%"
    assert flat["物流速度/物流到货时长"] == "47.09小时"
    assert flat["服务保障/平台求助率"] == "0.0000%"


def test_consultation_count_uses_level_one_value():
    result = MODULE.parse_tmall_blocks(
        PERFORMANCE_HTML,
        SCORE_HTML,
        consultation_html=CONSULTATION_HTML,
        valid_order_count="1.23万",
    )
    flat = MODULE.yingdao_parse(
        PERFORMANCE_HTML,
        SCORE_HTML,
        CONSULTATION_HTML,
        "1.23万",
    )

    assert result["咨询人数"] == "34"
    assert result["近30天有效订单"] == "12300"
    assert flat["咨询人数"] == "34"
    assert flat["近30天有效订单"] == "12300"
