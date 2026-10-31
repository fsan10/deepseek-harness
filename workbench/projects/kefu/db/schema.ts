import { sql } from "drizzle-orm";
import { integer, real, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const shops = sqliteTable(
  "shops",
  {
    id: integer("id").primaryKey(),
    name: text("name").notNull(),
    platform: text("platform").notNull(),
    kind: text("kind", { enum: ["own", "competitor"] }).notNull(),
    scoreEnabled: integer("score_enabled", { mode: "boolean" }).notNull().default(false),
    receptionEnabled: integer("reception_enabled", { mode: "boolean" }).notNull().default(false),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [uniqueIndex("shops_name_platform_kind_idx").on(table.name, table.platform, table.kind)],
);

export const metrics = sqliteTable(
  "metrics",
  {
    id: integer("id").primaryKey(),
    code: text("code").notNull().unique(),
    name: text("name").notNull(),
    category: text("category").notNull(),
    unit: text("unit").notNull().default(""),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [uniqueIndex("metrics_name_category_unit_idx").on(table.name, table.category, table.unit)],
);

export const dailyRecords = sqliteTable(
  "daily_records",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    reportDate: text("report_date").notNull(),
    shopId: integer("shop_id").notNull().references(() => shops.id, { onDelete: "cascade" }),
    metricId: integer("metric_id").notNull().references(() => metrics.id, { onDelete: "cascade" }),
    numericValue: real("numeric_value"),
    textValue: text("text_value"),
    targetOperator: text("target_operator"),
    targetValue: real("target_value"),
    sourceSheet: text("source_sheet").notNull().default("网页录入"),
    note: text("note").notNull().default(""),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [uniqueIndex("daily_records_date_shop_metric_idx").on(table.reportDate, table.shopId, table.metricId)],
);
