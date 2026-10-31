INSERT INTO dim.dim_expense_type (code, name, sort_order, description)
VALUES
    ('EXP001', '管理费用', 1, '办公、行政及公司管理相关支出'),
    ('EXP002', '人员成本', 2, '工资、社保、公积金及员工福利'),
    ('EXP003', '税金及附加', 3, '增值税附加、印花税、企业所得税等税费'),
    ('EXP004', '主营业务收入', 4, '平台提现等主营业务资金流入'),
    ('EXP005', '主营业务成本', 5, '主营业务直接采购成本'),
    ('EXP006', '销售费用', 6, '推广、达人佣金、客服及履约相关费用'),
    ('EXP007', '财务费用', 7, '银行手续费等财务费用'),
    ('EXP008', '营业外收入', 8, '账户验证等非主营业务收入')
ON CONFLICT DO NOTHING;

INSERT INTO dim.dim_account_entry (code, name, sort_order)
VALUES
    ('ACC001', '入账-银行手续费', 1),
    ('ACC002', '入账-提现', 2),
    ('ACC003', '入账-采购周边', 3),
    ('ACC004', '入账-快递服务费', 4),
    ('ACC005', '入账-天猫推广费', 5),
    ('ACC006', '入账-达人佣金费用', 6),
    ('ACC007', '入账-办公费用', 7),
    ('ACC008', '入账-人员工资', 8),
    ('ACC009', '入账-个人所得税', 9),
    ('ACC010', '入账-社会保险费', 10),
    ('ACC011', '入账-公积金', 11),
    ('ACC012', '入账-增值税', 12),
    ('ACC013', '入账-企业所得税', 13),
    ('ACC014', '入账-水电费', 14),
    ('ACC015', '入账-交通费', 15)
ON CONFLICT DO NOTHING;

WITH pairs(account_name, expense_name, is_default) AS (
    VALUES
      ('入账-银行手续费','财务费用',TRUE),
      ('入账-提现','主营业务收入',TRUE),
      ('入账-采购周边','主营业务成本',TRUE),
      ('入账-快递服务费','销售费用',TRUE),
      ('入账-快递服务费','管理费用',FALSE),
      ('入账-天猫推广费','销售费用',TRUE),
      ('入账-达人佣金费用','销售费用',TRUE),
      ('入账-办公费用','管理费用',TRUE),
      ('入账-办公费用','销售费用',FALSE),
      ('入账-人员工资','人员成本',TRUE),
      ('入账-个人所得税','人员成本',TRUE),
      ('入账-社会保险费','人员成本',TRUE),
      ('入账-社会保险费','管理费用',FALSE),
      ('入账-公积金','人员成本',TRUE),
      ('入账-公积金','管理费用',FALSE),
      ('入账-增值税','税金及附加',TRUE),
      ('入账-企业所得税','税金及附加',TRUE),
      ('入账-水电费','管理费用',TRUE),
      ('入账-交通费','管理费用',TRUE)
)
INSERT INTO dim.dim_account_entry_expense_type (account_entry_id, expense_type_id, is_default)
SELECT account.id, expense.id, pairs.is_default
FROM pairs
JOIN dim.dim_account_entry account ON account.name = pairs.account_name
JOIN dim.dim_expense_type expense ON expense.name = pairs.expense_name
ON CONFLICT (account_entry_id, expense_type_id) DO UPDATE
SET is_default = EXCLUDED.is_default;
