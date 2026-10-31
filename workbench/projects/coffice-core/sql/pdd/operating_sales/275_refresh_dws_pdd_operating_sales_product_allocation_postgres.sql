CALL dws.refresh_operating_sales_product_allocation(
    'dwd.dwd_pdd_operating_sales_order_item_detail'::REGCLASS,
    'dws.dws_pdd_operating_sales_product_allocation'::REGCLASS,
    FALSE
);
