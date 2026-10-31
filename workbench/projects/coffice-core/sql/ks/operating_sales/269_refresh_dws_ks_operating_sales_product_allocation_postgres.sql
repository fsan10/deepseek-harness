CALL dws.refresh_operating_sales_product_allocation(
    'dwd.dwd_ks_operating_sales_order_item_detail'::REGCLASS,
    'dws.dws_ks_operating_sales_product_allocation'::REGCLASS,
    TRUE
);
