"""Local order archive extraction/decryption; never a browser operation."""
import asyncio
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from ..core.errors import CommerceError, ContractError, NeedsHuman
from .files import receipt


def extract(archive, destination, password=""):
    destination.mkdir(parents=True, exist_ok=True)
    result = []
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if member.is_dir():
                continue
            relative = PurePosixPath(member.filename.replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts or ":" in str(relative):
                raise ContractError("报表 ZIP 含非法路径")
            if relative.suffix.lower() not in {".csv", ".xlsx", ".xls"}:
                continue
            target = destination / relative.name
            if target in result:
                raise ContractError("报表 ZIP 包含重名文件")
            temporary = target.with_suffix(target.suffix + ".part")
            try:
                with bundle.open(member, pwd=password.encode() if password else None) as source, temporary.open("wb") as output:
                    shutil.copyfileobj(source, output)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            result.append(target)
    if len(result) != 1:
        raise ContractError("订单 ZIP 未包含唯一报表，拒绝静默选错文件")
    return result[0]


def office_encrypted(path):
    if path.suffix.lower() != ".xlsx":
        return False
    import msoffcrypto
    with path.open("rb") as source:
        return msoffcrypto.OfficeFile(source).is_encrypted()


def decrypt(source, password, target):
    import msoffcrypto
    temporary = target.with_suffix(".xlsx.part")
    try:
        with source.open("rb") as input_file, temporary.open("wb") as output:
            office = msoffcrypto.OfficeFile(input_file)
            office.load_key(password=password)
            office.decrypt(output)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def validate(path):
    if not path.is_file() or path.stat().st_size == 0:
        raise ContractError("提取后的报表为空")
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            if not book.sheetnames:
                raise ContractError("报表没有工作表")
        finally:
            book.close()


async def finish_order(ctx, source, *, send_password=None):
    async def already_sent():
        return None
    send_password = send_password or already_sent
    path = Path(source["path"])
    for attempt in range(3):
        try:
            if path.suffix.lower() == ".zip":
                with zipfile.ZipFile(path) as bundle:
                    encrypted = any(m.flag_bits & 1 for m in bundle.infolist())
                password = await ctx.verification(purpose="订单报表 ZIP 解压密码", kind="archive_password",
                    name="archive_password", send=send_password) if encrypted else ""
                report = await asyncio.to_thread(extract, path, path.parent / "extracted", password)
            else:
                report = path
            if await asyncio.to_thread(office_encrypted, report):
                password = await ctx.verification(purpose="订单报表文件提取码", kind="archive_password",
                    name="archive_password", send=send_password)
                report = await asyncio.to_thread(decrypt, report, password, report.with_name(report.stem + "_decrypted.xlsx"))
            await asyncio.to_thread(validate, report)
            if report != path:
                source["role"] = "source"
                ctx.run.state["files"].append({**receipt(report, period=ctx.request.period.public()), "role": "report"})
            else:
                source["role"] = "report"
            ctx.run.save()
            return report
        except CommerceError:
            raise
        except Exception as exc:
            if not any(marker in (type(exc).__name__ + str(exc)).lower() for marker in ("password", "key", "decrypt")):
                raise ContractError("订单报表解密或结构校验失败") from None
            operation = ctx.run.state["operations"].get("archive_password", {})
            if not operation.get("challenge_id"):
                raise ContractError("密码校验失败且未找到原 Challenge") from None
            from ..integrations.legacy.verification import reject
            await reject(operation["challenge_id"])
            operation["status"] = "sent"
            ctx.run.save()
            if attempt == 2:
                raise NeedsHuman("连续三次文件密码校验失败，请在原群更正后续跑") from None
