"""小红书结算账单。"""
from ...backends.merchant.api.reports import settlements
from .bills import execute


async def download(ctx, request):
    return await execute(ctx, request, settlements, settlement=True)
