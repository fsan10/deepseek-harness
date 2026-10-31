-- 用户已核实：禧饮平台商家ID为5525973946；保留内部标准店铺编码。
UPDATE dim.dim_platform_shop_company
SET account_id='5525973946',updated_at=NOW()
WHERE platform_code='ks' AND shop_code='123456789'
  AND account_id='123456789';
