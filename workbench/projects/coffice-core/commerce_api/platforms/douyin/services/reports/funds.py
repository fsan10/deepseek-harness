"""抖店资金报表下载。"""
from ...backends.merchant.api.reports import funds
from .bills import execute


async def download(ctx, request):
    return await execute(ctx, request, funds)
