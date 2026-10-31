CALL dws.refresh_operating_sales_product_allocation(
    'dwd.dwd_tmall_operating_sales_order_item_detail'::REGCLASS,
    'dws.dws_tmall_operating_sales_product_allocation'::REGCLASS,
    FALSE,
    'main_order_sum_gt',
    TRUE
);
