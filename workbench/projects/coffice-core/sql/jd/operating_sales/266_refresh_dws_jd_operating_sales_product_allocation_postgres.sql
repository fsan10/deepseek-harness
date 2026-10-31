CALL dws.refresh_operating_sales_product_allocation(
    'dwd.dwd_jd_operating_sales_order_item_detail'::REGCLASS,
    'dws.dws_jd_operating_sales_product_allocation'::REGCLASS,
    FALSE
);
