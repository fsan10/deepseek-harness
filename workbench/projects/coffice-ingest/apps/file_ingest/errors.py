"""Stable business error identifiers without changing the HTTP envelope."""


class ShopCodeRequired(ValueError):
    http_status = 400
    details = {'error_code':'SHOP_CODE_REQUIRED'}

    def __init__(self):
        super().__init__('上传必须显式传入DIM中的标准shop_code，不能通过文件名或平台默认店铺代替')
