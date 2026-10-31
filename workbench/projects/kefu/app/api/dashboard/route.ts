import { all, first } from "@/db/local";
import { scoreCardsForPlatform, storeScoreAliases } from "@/db/reporting-config";
import type { SQLInputValue } from "node:sqlite";

export const runtime = "nodejs";

type Row = Record<string, string | number | null>;

function dbError(error: unknown) {
  const message = error instanceof Error ? error.message : "数据库暂时不可用";
  return Response.json({ error: message }, { status: 500 });
}

function safeDate(value: string | null, fallback: string) {
  return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : fallback;
}

type FilterScope = "all" | "score" | "reception";

function scopeCondition(scope: FilterScope) {
  if (scope === "score") return "s.score_enabled = 1";
  if (scope === "reception") return "s.reception_enabled = 1";
  return "(s.score_enabled = 1 OR s.reception_enabled = 1)";
}

function filters(kind: "own" | "competitor" = "own", scope: FilterScope = "all") {
  const scoped = scopeCondition(scope);
  const shops = all<Row>(
    `SELECT DISTINCT s.id, s.name, s.platform, s.kind
     FROM shops s
     WHERE s.kind = ? AND ${scoped}
     ORDER BY s.platform, s.name`,
    [kind],
  );
  const metrics = all<Row>(
    `SELECT DISTINCT m.id, m.code, m.name, m.category, m.unit
     FROM metrics m
     JOIN daily_records r ON r.metric_id = m.id
     JOIN shops s ON s.id = r.shop_id
     WHERE s.kind = ? AND ${scoped}
     ORDER BY CASE WHEN m.code = 'reception_count' THEN 0 ELSE 1 END, m.category, m.name`,
    [kind],
  );
  return { shops, metrics };
}

function scoreComparison(from: string, to: string, limit: number) {
  const aliases = storeScoreAliases();
  if (!aliases.length) return [];
  const placeholders = aliases.map(() => "?").join(", ");
  const rows = all<Row>(
    `SELECT s.id AS shopId, s.name AS shop, s.platform, r.report_date AS date,
       m.name AS metric, r.numeric_value AS value
     FROM daily_records r
     JOIN shops s ON s.id = r.shop_id
     JOIN metrics m ON m.id = r.metric_id
     WHERE s.kind = 'own' AND s.score_enabled = 1
       AND r.report_date BETWEEN ? AND ? AND m.name IN (${placeholders})`,
    [from, to, ...aliases],
  );
  const latest = new Map<number, Row>();
  for (const row of rows) {
    const shopId = Number(row.shopId);
    const card = scoreCardsForPlatform(String(row.platform))[0];
    const priority = card?.aliases.indexOf(String(row.metric)) ?? -1;
    if (!card || priority < 0) continue;
    const current = latest.get(shopId);
    const currentPriority = current ? card.aliases.indexOf(String(current.metric)) : Number.MAX_SAFE_INTEGER;
    if (!current || String(row.date) > String(current.date) || (
      String(row.date) === String(current.date) && priority < currentPriority
    )) latest.set(shopId, row);
  }
  return [...latest.values()]
    .sort((left, right) => Number(right.value) - Number(left.value))
    .slice(0, limit);
}

function buildScoreCards(platform: string, values: Row[]) {
  return scoreCardsForPlatform(platform).map((definition) => {
    const candidates = values
      .filter((row) => definition.aliases.includes(String(row.metric)))
      .sort((left, right) => {
        const dateOrder = String(right.date).localeCompare(String(left.date));
        return dateOrder || definition.aliases.indexOf(String(left.metric)) - definition.aliases.indexOf(String(right.metric));
      });
    const current = candidates[0];
    return {
      label: definition.label,
      metric: current?.metric ?? definition.label,
      metricId: current?.metricId ?? null,
      value: current?.value ?? null,
      textValue: current?.textValue ?? null,
      date: current?.date ?? null,
      unit: current?.unit ?? definition.unit,
    };
  });
}

function buildScoreTrend(selectedShop: number, platform: string, from: string, to: string) {
  const definitions = scoreCardsForPlatform(platform).filter((definition) => definition.trend);
  const aliases = [...new Set(definitions.flatMap((definition) => definition.aliases))];
  if (!selectedShop || !aliases.length) return [];
  const placeholders = aliases.map(() => "?").join(", ");
  const raw = all<Row>(
    `SELECT r.report_date AS date, m.name AS metric, r.numeric_value AS value
     FROM daily_records r JOIN metrics m ON m.id = r.metric_id
     WHERE r.shop_id = ? AND r.report_date BETWEEN ? AND ?
       AND m.name IN (${placeholders})`,
    [selectedShop, from, to, ...aliases],
  );
  const dates = [...new Set(raw.map((row) => String(row.date)))].sort().slice(-30);
  const result: Row[] = [];
  for (const date of dates) {
    for (const definition of definitions) {
      const candidates = raw
        .filter((row) => String(row.date) === date && definition.aliases.includes(String(row.metric)))
        .sort((left, right) => definition.aliases.indexOf(String(left.metric)) - definition.aliases.indexOf(String(right.metric)));
      if (candidates[0]) result.push({ date, series: definition.label, value: candidates[0].value });
    }
  }
  return result;
}

function overview(url: URL) {
  const to = safeDate(url.searchParams.get("to"), "9999-12-31");
  const reception = first<{ latestDate: string | null }>(
    `SELECT MAX(r.report_date) AS latestDate
     FROM daily_records r JOIN metrics m ON m.id = r.metric_id JOIN shops s ON s.id = r.shop_id
     WHERE m.code = 'reception_count' AND s.kind = 'own' AND s.reception_enabled = 1 AND r.report_date <= ?`,
    [to],
  );
  const latestDate = reception?.latestDate ?? null;
  if (!latestDate) {
    return { latestDate: null, stats: {}, trend: [], platforms: [], ranking: scoreComparison("0001-01-01", to, 8), risks: [], filters: filters() };
  }

  const previous = first<{ previousDate: string | null }>(
    `SELECT MAX(r.report_date) AS previousDate
     FROM daily_records r JOIN metrics m ON m.id = r.metric_id JOIN shops s ON s.id = r.shop_id
     WHERE m.code = 'reception_count' AND s.kind = 'own' AND s.reception_enabled = 1 AND r.report_date < ?`,
    [latestDate],
  );
  const previousDate = previous?.previousDate ?? latestDate;
  const metricDate = first<{ latestDate: string | null }>(
    `SELECT MAX(r.report_date) AS latestDate FROM daily_records r
     JOIN shops s ON s.id = r.shop_id
     WHERE s.kind = 'own' AND s.score_enabled = 1 AND r.report_date <= ?`,
    [to],
  )?.latestDate ?? latestDate;

  const stats = first<Row>(
    `SELECT
       COALESCE(SUM(CASE WHEN r.report_date = ? THEN r.numeric_value ELSE 0 END), 0) AS receptionTotal,
       COALESCE(SUM(CASE WHEN r.report_date = ? THEN r.numeric_value ELSE 0 END), 0) AS previousTotal,
       COUNT(DISTINCT CASE WHEN r.report_date = ? AND r.numeric_value > 0 THEN s.id END) AS activeShopCount
     FROM daily_records r
     JOIN shops s ON s.id = r.shop_id
     JOIN metrics m ON m.id = r.metric_id
     WHERE m.code = 'reception_count' AND s.kind = 'own' AND s.reception_enabled = 1`,
    [latestDate, previousDate, latestDate],
  ) ?? {};
  const risk = first<Row>(
    `SELECT COUNT(DISTINCT s.id) AS abnormalShopCount,
       COUNT(DISTINCT m.id) AS metricCount
     FROM daily_records r
     JOIN shops s ON s.id = r.shop_id
     JOIN metrics m ON m.id = r.metric_id
     WHERE r.report_date = ? AND s.kind = 'own' AND s.score_enabled = 1 AND r.target_value IS NOT NULL AND (
       (r.target_operator IN ('≥', '>') AND r.numeric_value < r.target_value) OR
       (r.target_operator IN ('≤', '<') AND r.numeric_value > r.target_value)
     )`,
    [metricDate],
  ) ?? {};

  const trend = all<Row>(
    `WITH recent_dates AS (
       SELECT DISTINCT r.report_date
       FROM daily_records r JOIN metrics m ON m.id = r.metric_id JOIN shops s ON s.id = r.shop_id
       WHERE m.code = 'reception_count' AND s.reception_enabled = 1 AND r.report_date <= ?
       ORDER BY r.report_date DESC LIMIT 7
     )
     SELECT r.report_date AS date, s.platform,
       ROUND(SUM(r.numeric_value), 2) AS value
     FROM daily_records r
     JOIN shops s ON s.id = r.shop_id
     JOIN metrics m ON m.id = r.metric_id
     WHERE m.code = 'reception_count' AND s.reception_enabled = 1 AND r.report_date IN (SELECT report_date FROM recent_dates)
     GROUP BY r.report_date, s.platform
     ORDER BY r.report_date, value DESC`,
    [latestDate],
  );
  const platforms = all<Row>(
    `SELECT s.platform, ROUND(SUM(r.numeric_value), 2) AS value
     FROM daily_records r
     JOIN shops s ON s.id = r.shop_id
     JOIN metrics m ON m.id = r.metric_id
     WHERE r.report_date = ? AND m.code = 'reception_count' AND s.reception_enabled = 1
     GROUP BY s.platform ORDER BY value DESC`,
    [latestDate],
  );
  const ranking = scoreComparison("0001-01-01", to, 8);
  const risks = all<Row>(
    `SELECT s.name AS shop, s.platform, m.name AS metric, m.unit,
       r.numeric_value AS value, r.target_value AS target, r.target_operator AS operator
     FROM daily_records r
     JOIN shops s ON s.id = r.shop_id
     JOIN metrics m ON m.id = r.metric_id
     WHERE r.report_date = ? AND s.kind = 'own' AND s.score_enabled = 1 AND r.target_value IS NOT NULL AND (
       (r.target_operator IN ('≥', '>') AND r.numeric_value < r.target_value) OR
       (r.target_operator IN ('≤', '<') AND r.numeric_value > r.target_value)
     )
     ORDER BY ABS(r.numeric_value - r.target_value) DESC LIMIT 8`,
    [metricDate],
  );

  return {
    latestDate,
    metricDate,
    previousDate,
    stats: { ...stats, ...risk },
    trend,
    platforms,
    ranking,
    risks,
    filters: filters(),
  };
}

function reception(url: URL) {
  const from = safeDate(url.searchParams.get("from"), "2025-01-01");
  const to = safeDate(url.searchParams.get("to"), "9999-12-31");
  const platform = (url.searchParams.get("platform") ?? "").slice(0, 40);
  const platformSql = platform ? "AND s.platform = ?" : "";
  const platformBindings: SQLInputValue[] = platform ? [platform] : [];
  const latestDate = first<{ latestDate: string | null }>(
    `SELECT MAX(r.report_date) AS latestDate
     FROM daily_records r JOIN shops s ON s.id = r.shop_id JOIN metrics m ON m.id = r.metric_id
     WHERE m.code = 'reception_count' AND s.kind = 'own' AND s.reception_enabled = 1
       AND r.report_date BETWEEN ? AND ? ${platformSql}`,
    [from, to, ...platformBindings],
  )?.latestDate ?? null;

  if (!latestDate) {
    return { latestDate: null, from, to, platform, summary: {}, trend: [], rows: [], filters: filters("own", "reception") };
  }
  const previousDate = first<{ previousDate: string | null }>(
    `SELECT MAX(r.report_date) AS previousDate
     FROM daily_records r JOIN shops s ON s.id = r.shop_id JOIN metrics m ON m.id = r.metric_id
     WHERE m.code = 'reception_count' AND s.kind = 'own' AND s.reception_enabled = 1
       AND r.report_date < ? ${platformSql}`,
    [latestDate, ...platformBindings],
  )?.previousDate ?? latestDate;

  const summary = first<Row>(
    `SELECT
       COALESCE(SUM(CASE WHEN r.report_date = ? THEN r.numeric_value ELSE 0 END), 0) AS todayTotal,
       COALESCE(SUM(CASE WHEN r.report_date = ? THEN r.numeric_value ELSE 0 END), 0) AS yesterdayTotal,
       COALESCE(SUM(CASE WHEN r.report_date BETWEEN date(?, '-6 day') AND ? THEN r.numeric_value ELSE 0 END), 0) AS weekTotal,
       COALESCE(SUM(CASE WHEN r.report_date BETWEEN date(?, '-13 day') AND date(?, '-7 day') THEN r.numeric_value ELSE 0 END), 0) AS previousWeekTotal,
       COALESCE(SUM(CASE WHEN strftime('%Y-%m', r.report_date) = strftime('%Y-%m', ?) THEN r.numeric_value ELSE 0 END), 0) AS monthTotal,
       COUNT(DISTINCT CASE WHEN r.report_date BETWEEN date(?, '-29 day') AND ? THEN r.report_date END) AS activeDays,
       COALESCE(SUM(CASE WHEN r.report_date BETWEEN date(?, '-29 day') AND ? THEN r.numeric_value ELSE 0 END), 0) AS thirtyDayTotal
     FROM daily_records r
     JOIN shops s ON s.id = r.shop_id
     JOIN metrics m ON m.id = r.metric_id
     WHERE m.code = 'reception_count' AND s.kind = 'own' AND s.reception_enabled = 1 ${platformSql}`,
    [
      latestDate, previousDate, latestDate, latestDate, latestDate, latestDate,
      latestDate, latestDate, latestDate, latestDate, latestDate, ...platformBindings,
    ],
  ) ?? {};
  const trend = all<Row>(
    `WITH recent_dates AS (
       SELECT DISTINCT r.report_date
       FROM daily_records r JOIN shops s ON s.id = r.shop_id JOIN metrics m ON m.id = r.metric_id
       WHERE m.code = 'reception_count' AND s.kind = 'own' AND s.reception_enabled = 1
         AND r.report_date BETWEEN ? AND ? ${platformSql}
       ORDER BY r.report_date DESC LIMIT 30
     )
     SELECT r.report_date AS date, s.platform, ROUND(SUM(r.numeric_value), 2) AS value
     FROM daily_records r
     JOIN shops s ON s.id = r.shop_id
     JOIN metrics m ON m.id = r.metric_id
     WHERE m.code = 'reception_count' AND s.kind = 'own' AND s.reception_enabled = 1
       AND r.report_date IN (SELECT report_date FROM recent_dates) ${platformSql}
     GROUP BY r.report_date, s.platform ORDER BY r.report_date, value DESC`,
    [from, to, ...platformBindings, ...platformBindings],
  );
  const rows = all<Row>(
    `WITH seven_day AS (
       SELECT r.shop_id, AVG(r.numeric_value) AS averageValue, SUM(r.numeric_value) AS weekValue
       FROM daily_records r JOIN metrics m ON m.id = r.metric_id
       WHERE m.code = 'reception_count' AND r.report_date BETWEEN date(?, '-6 day') AND ?
       GROUP BY r.shop_id
     ), previous_week AS (
       SELECT r.shop_id, SUM(r.numeric_value) AS previousWeekValue
       FROM daily_records r JOIN metrics m ON m.id = r.metric_id
       WHERE m.code = 'reception_count' AND r.report_date BETWEEN date(?, '-13 day') AND date(?, '-7 day')
       GROUP BY r.shop_id
     )
     SELECT s.id AS shopId, s.platform, s.name AS shop,
       COALESCE(today.numeric_value, 0) AS todayValue,
       COALESCE(yesterday.numeric_value, 0) AS yesterdayValue,
       ROUND(COALESCE(seven_day.averageValue, 0), 1) AS averageValue,
       COALESCE(seven_day.weekValue, 0) AS weekValue,
       COALESCE(previous_week.previousWeekValue, 0) AS previousWeekValue
     FROM shops s
     JOIN daily_records today ON today.shop_id = s.id AND today.report_date = ?
     JOIN metrics tm ON tm.id = today.metric_id AND tm.code = 'reception_count'
     LEFT JOIN daily_records yesterday ON yesterday.shop_id = s.id AND yesterday.report_date = ? AND yesterday.metric_id = today.metric_id
     LEFT JOIN seven_day ON seven_day.shop_id = s.id
     LEFT JOIN previous_week ON previous_week.shop_id = s.id
     WHERE s.kind = 'own' AND s.reception_enabled = 1 ${platform ? "AND s.platform = ?" : ""}
     ORDER BY today.numeric_value DESC, s.platform, s.name`,
    [latestDate, latestDate, latestDate, latestDate, latestDate, previousDate, ...platformBindings],
  );

  return { latestDate, previousDate, from, to, platform, summary, trend, rows, filters: filters("own", "reception") };
}

function storeScore(url: URL) {
  const from = safeDate(url.searchParams.get("from"), "0001-01-01");
  const to = safeDate(url.searchParams.get("to"), "9999-12-31");
  const filterData = filters("own", "score");
  const requestedShopId = Number(url.searchParams.get("shopId") || 0);
  const defaultShop = first<{ id: number }>(
    `SELECT s.id FROM shops s
     JOIN daily_records r ON r.shop_id = s.id JOIN metrics m ON m.id = r.metric_id
     WHERE s.kind = 'own' AND s.score_enabled = 1 AND m.code != 'reception_count'
       AND r.report_date BETWEEN ? AND ?
     GROUP BY s.id ORDER BY MAX(r.report_date) DESC, s.platform, s.name LIMIT 1`,
    [from, to],
  )?.id ?? Number(filterData.shops[0]?.id ?? 0);
  const requestedShopAllowed = filterData.shops.some((shop) => Number(shop.id) === requestedShopId);
  const selectedShop = requestedShopAllowed ? requestedShopId : defaultShop;
  const selectedShopInfo = filterData.shops.find((shop) => Number(shop.id) === selectedShop) ?? null;
  const selectedPlatform = String(selectedShopInfo?.platform ?? "");
  const latestDate = first<{ latestDate: string | null }>(
    `SELECT MAX(r.report_date) AS latestDate FROM daily_records r
     JOIN metrics m ON m.id = r.metric_id
     WHERE r.shop_id = ? AND m.code != 'reception_count' AND r.report_date BETWEEN ? AND ?`,
    [selectedShop, from, to],
  )?.latestDate ?? null;

  const values = all<Row>(
    `WITH latest AS (
       SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.metric_id ORDER BY r.report_date DESC) AS position
       FROM daily_records r WHERE r.shop_id = ? AND r.report_date BETWEEN ? AND ?
     )
     SELECT m.id AS metricId, m.code, m.name AS metric, m.category, m.unit,
       latest.report_date AS date, latest.numeric_value AS value, latest.text_value AS textValue,
       latest.target_operator AS operator, latest.target_value AS target
     FROM latest JOIN metrics m ON m.id = latest.metric_id
     WHERE latest.position = 1 AND m.code != 'reception_count'
     ORDER BY m.category, m.name`,
    [selectedShop, from, to],
  );
  const scoreCards = buildScoreCards(selectedPlatform, values);
  const scoreMetricIds = new Set(
    scoreCards
      .map((card) => Number(card.metricId))
      .filter((metricId) => Number.isFinite(metricId) && metricId > 0),
  );
  const detailValues = values.filter((row) => !scoreMetricIds.has(Number(row.metricId)));
  const scoreTrend = buildScoreTrend(selectedShop, selectedPlatform, from, to);
  const comparison = scoreComparison(from, to, 12);

  return {
    from,
    to,
    latestDate,
    selectedShop,
    selectedShopInfo,
    scoreCards,
    values,
    detailValues,
    scoreTrend,
    comparison,
    filters: filterData,
  };
}

function dataManagement(url: URL) {
  const dataType = url.searchParams.get("dataType") === "scores" ? "scores" : "reception";
  const query = (url.searchParams.get("query") ?? "").trim().slice(0, 80);
  const platform = (url.searchParams.get("platform") ?? "").trim().slice(0, 40);
  const shopId = Math.max(0, Number(url.searchParams.get("shopId") || 0));
  const from = safeDate(url.searchParams.get("from"), "0001-01-01");
  const to = safeDate(url.searchParams.get("to"), "9999-12-31");
  const requestedPage = Number(url.searchParams.get("page") || 1);
  const requestedPageSize = Math.trunc(Number(url.searchParams.get("pageSize") || 20));
  const pageSize = Number.isFinite(requestedPageSize) ? Math.min(100, Math.max(5, requestedPageSize)) : 20;
  const conditions = ["s.kind = 'own'", "r.report_date BETWEEN ? AND ?"];
  const bindings: SQLInputValue[] = [from, to];
  if (dataType === "reception") conditions.push("s.reception_enabled = 1", "m.code = 'reception_count'");
  else conditions.push("s.score_enabled = 1", "m.code != 'reception_count'");
  if (platform) { conditions.push("s.platform = ?"); bindings.push(platform); }
  if (shopId) { conditions.push("s.id = ?"); bindings.push(shopId); }
  if (query) {
    conditions.push("(s.name LIKE ? OR s.platform LIKE ? OR m.name LIKE ?)");
    const like = `%${query}%`;
    bindings.push(like, like, like);
  }
  const where = conditions.join(" AND ");
  const total = Number(first<{ count: number }>(
    `SELECT COUNT(*) AS count FROM daily_records r
     JOIN shops s ON s.id = r.shop_id JOIN metrics m ON m.id = r.metric_id
     WHERE ${where}`,
    bindings,
  )?.count ?? 0);
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const page = Number.isFinite(requestedPage) ? Math.min(pages, Math.max(1, Math.trunc(requestedPage))) : 1;
  const rows = all<Row>(
    `SELECT r.id, r.report_date AS date, s.id AS shopId, s.platform, s.name AS shop,
       m.id AS metricId, m.name AS metric, m.category, m.unit,
       r.numeric_value AS value, r.text_value AS textValue, r.note
     FROM daily_records r
     JOIN shops s ON s.id = r.shop_id JOIN metrics m ON m.id = r.metric_id
     WHERE ${where}
     ORDER BY r.report_date DESC, s.platform, s.name, m.name
     LIMIT ? OFFSET ?`,
    [...bindings, pageSize, (page - 1) * pageSize],
  );

  return {
    latestDate: rows[0]?.date ?? null,
    dataType,
    query,
    platform,
    shopId,
    rows,
    pagination: { page, pageSize, total, pages },
    filters: filters("own", dataType === "reception" ? "reception" : "score"),
  };
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const view = url.searchParams.get("view") ?? "overview";
    if (view === "reception") return Response.json(reception(url));
    if (view === "store-score") return Response.json(storeScore(url));
    if (view === "data-management") return Response.json(dataManagement(url));
    return Response.json(overview(url));
  } catch (error) {
    return dbError(error);
  }
}
