CALL dws.refresh_operating_sales_product_allocation(
    'dwd.dwd_xhs_operating_sales_order_item_detail'::REGCLASS,
    'dws.dws_xhs_operating_sales_product_allocation'::REGCLASS,
    TRUE
);
