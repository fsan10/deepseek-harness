export type ReportingScope = "score" | "reception";
export type ImportScope = ReportingScope | "refund";

export type ScoreCardDefinition = {
  label: string;
  aliases: readonly string[];
  unit: "分" | "单" | "区间";
  trend: boolean;
};

type ShopDefinition = {
  platform: string;
  name: string;
  score: boolean;
  reception: boolean;
};

const SCORE_SHOPS: Record<string, readonly string[]> = {
  抖音: [
    "MOCK咖啡旗舰店",
    "MOCK食品旗舰店",
    "MOCK冲饮旗舰店",
    "MOCK官方旗舰店",
    "MOCK宁盏冲饮专卖店",
    "MOCK墨客咖时咖啡专卖店",
    "MOCK吉饮咖啡专卖店",
    "MOCK豆格咖啡专卖店",
    "MOCK舟益饮品专卖店",
    "MOCK笪圭专卖店",
    "MOCK禧饮咖啡专卖店",
    "MOCK音咖专卖店",
    "MOCK致纯咖啡专卖店",
    "MOCK谨咖专卖店",
  ],
  拼多多: ["MOCK饮品旗舰店", "悦咖甄选", "养颜轻食"],
  天猫: ["MOCK旗舰店"],
};

const RECEPTION_SHOPS: Record<string, readonly string[]> = {
  抖音: SCORE_SHOPS.抖音,
  拼多多: SCORE_SHOPS.拼多多,
  快手: ["MOCK舟益专卖店", "MOCK陌时专卖店", "MOCK禧饮专卖店", "MOCK禧饮咖啡专卖店", "MOCK音咖专卖店"],
  天猫: SCORE_SHOPS.天猫,
  小红书: ["MOCK旗舰店"],
  微信小店: ["mock咖啡店"],
  京东: ["mock饮品旗舰店", "MOCK饮品旗舰店"],
};

const REFUND_SHOPS: Record<string, readonly string[]> = {
  抖音: SCORE_SHOPS.抖音,
};

export const PLATFORM_IMPORT_CAPABILITIES: Record<string, readonly ImportScope[]> = {
  抖音: ["score", "reception", "refund"],
  天猫: ["score", "reception"],
  拼多多: ["score", "reception"],
  京东: ["reception"],
  微信小店: ["reception"],
  小红书: ["reception"],
  快手: ["reception"],
};

export const PLATFORM_SCORE_CARDS: Record<string, readonly ScoreCardDefinition[]> = {
  抖音: [
    {
      label: "店铺体验分",
      aliases: ["店铺体验分", "店铺分", "我的总分", "我的体验分"],
      unit: "分",
      trend: true,
    },
    { label: "近30天有效订单", aliases: ["近30天有效订单", "近30单有效订单"], unit: "单", trend: false },
    {
      label: "商品体验分",
      aliases: ["商品体验分", "商品体验得分", "商品体验", "商品综合评分"],
      unit: "分",
      trend: true,
    },
    {
      label: "物流体验分",
      aliases: ["物流体验分", "物流体验得分", "物流体验"],
      unit: "分",
      trend: true,
    },
    {
      label: "服务体验分",
      aliases: ["服务体验分", "服务体验得分", "服务体验"],
      unit: "分",
      trend: true,
    },
  ],
  天猫: [
    { label: "店铺体验分", aliases: ["店铺体验分", "真实体验分", "店铺分"], unit: "分", trend: true },
    { label: "近30天有效订单", aliases: ["近30天有效订单"], unit: "单", trend: false },
    { label: "宝贝质量分", aliases: ["宝贝质量分", "宝贝质量"], unit: "分", trend: true },
    { label: "物流速度分", aliases: ["物流速度分", "物流速度"], unit: "分", trend: true },
    { label: "服务体验分", aliases: ["服务体验分", "服务保障"], unit: "分", trend: true },
  ],
  拼多多: [
    { label: "消费者服务体验分", aliases: ["消费者服务体验分", "店铺体验分", "店铺分"], unit: "分", trend: true },
    { label: "本店铺体验分在同行排名", aliases: ["本店铺体验分在同行排名"], unit: "区间", trend: false },
    { label: "服务态度体验分", aliases: ["服务态度体验分"], unit: "分", trend: true },
    { label: "基础服务体验分", aliases: ["基础服务体验分"], unit: "分", trend: true },
    { label: "商品服务体验分", aliases: ["商品服务体验分"], unit: "分", trend: true },
    { label: "发货服务体验分", aliases: ["发货服务体验分"], unit: "分", trend: true },
    { label: "物流服务体验分", aliases: ["物流服务体验分"], unit: "分", trend: true },
  ],
};

function namesFor(scope: ReportingScope) {
  return scope === "score" ? SCORE_SHOPS : RECEPTION_SHOPS;
}

export function hasReportingScope(platform: string, name: string, scope: ReportingScope) {
  return namesFor(scope)[platform]?.includes(name) ?? false;
}

export function hasImportScope(platform: string, name: string, scope: ImportScope) {
  if (scope === "refund") return REFUND_SHOPS[platform]?.includes(name) ?? false;
  return hasReportingScope(platform, name, scope);
}

export const REPORTING_SHOPS: readonly ShopDefinition[] = (() => {
  const shops = new Map<string, ShopDefinition>();
  for (const [scope, platforms] of [["score", SCORE_SHOPS], ["reception", RECEPTION_SHOPS]] as const) {
    for (const [platform, names] of Object.entries(platforms)) {
      for (const name of names) {
        const key = `${platform}\u0000${name}`;
        const current = shops.get(key) ?? { platform, name, score: false, reception: false };
        current[scope] = true;
        shops.set(key, current);
      }
    }
  }
  return [...shops.values()];
})();

export function scoreCardsForPlatform(platform: string) {
  return PLATFORM_SCORE_CARDS[platform] ?? [];
}

export function storeScoreAliases() {
  return [...new Set(Object.values(PLATFORM_SCORE_CARDS).flatMap((cards) => cards[0]?.aliases ?? []))];
}

export function normalizeImportedMetric(
  platform: string,
  metricName: string,
  metricCategory: string,
) {
  const receptionNames = new Set(["接待量", "咨询人数", "咨询量", "接待人数"]);
  if (receptionNames.has(metricName)) {
    return { metricName: "接待量", metricCategory: "运营" };
  }
  const refundNames = new Set(["退款率", "订单退款率", "店铺退款率"]);
  if (refundNames.has(metricName)) {
    return { metricName: "退款率", metricCategory: "退款统计" };
  }
  if (metricCategory === "退款统计") {
    return { metricName, metricCategory };
  }
  if (platform === "抖音" && metricCategory === "体验分") {
    const scoreNames: Record<string, string> = {
      店铺体验分: "店铺体验分",
      我的总分: "店铺体验分",
      我的体验分: "店铺体验分",
      商品体验分: "商品体验分",
      商品体验: "商品体验分",
      商品体验得分: "商品体验分",
      物流体验分: "物流体验分",
      物流体验: "物流体验分",
      物流体验得分: "物流体验分",
      服务体验分: "服务体验分",
      服务体验: "服务体验分",
      服务体验得分: "服务体验分",
    };
    if (scoreNames[metricName]) {
      return { metricName: scoreNames[metricName], metricCategory: "总览" };
    }
  }
  if (platform !== "天猫") return { metricName, metricCategory };

  const scoreNames: Record<string, string> = {
    真实体验分: "店铺体验分",
    宝贝质量: "宝贝质量分",
    物流速度: "物流速度分",
    服务保障: "服务体验分",
  };
  if (metricCategory === "体验分" && scoreNames[metricName]) {
    return { metricName: scoreNames[metricName], metricCategory: "总览" };
  }
  if (metricCategory === "服务保障") {
    return { metricName, metricCategory: "服务体验" };
  }
  return { metricName, metricCategory };
}
