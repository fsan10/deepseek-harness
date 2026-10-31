"""Submit archived report receipts to the existing authenticated ingest API."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class IngestAPIError(RuntimeError):
    pass


def validate_ingest_credentials(source: str) -> None:
    """Fail before opening a merchant browser when upload identity is missing."""
    if source == 'manual':
        if not os.getenv('INGEST_USERNAME') or not os.getenv('INGEST_PASSWORD'):
            raise IngestAPIError('人工终端上传需要用户登录：请使用apps.file_ingest.cli交互登录，或在未提交.env配置INGEST_USERNAME和INGEST_PASSWORD')
    elif source == 'api':
        if not os.getenv('INGEST_ROBOT_TOKEN'):
            raise IngestAPIError('API上传需要项目.env中的INGEST_ROBOT_TOKEN')
    else:
        raise IngestAPIError('上传来源必须为manual或api')


def _safe_http_failure(exc: HTTPError, path: str) -> str:
    stage = ('覆盖预检' if path.endswith('/coverage-preflight') else
             '提交会话' if path.endswith('/complete') else
             '上传文件' if path.endswith('/files') else '请求导入服务')
    # Response bodies can contain business rows, URLs or credentials. Only
    # recognize known error categories and return our own fixed descriptions.
    reason = ''
    try:
        payload = json.loads(exc.read(8192).decode('utf-8'))
        message = str(payload.get('message') or '') if isinstance(payload, dict) else ''
        for fragment, safe in (
            ('查询范围之外', '文件业务日期与声明覆盖范围不一致'),
            ('超出', '文件业务日期或覆盖范围校验未通过'),
            ('账单日期', '京东账单缺少已核验的业务日期'),
            ('同店铺同报表日期重复', '同一会话存在重复报表日期'),
            ('覆盖回执未验证', '覆盖回执与文件或店铺不一致'),
            ('SHA256改变', '原始上传文件校验失败'),
            ('查询范围', '完整查询范围校验未通过'),
        ):
            if fragment in message:
                reason = '；原因=' + safe
                break
    except (ValueError, OSError, UnicodeError, TypeError, AttributeError):
        pass
    return f'API上传失败（HTTP {exc.code}）；阶段={stage}{reason}，归档文件已保留'


_REQUEST_TIMEOUT_SECONDS = 120
_REQUEST_MAX_ATTEMPTS = 2
_REQUEST_RETRY_DELAY_SECONDS = 3


def _request(base: str, token: str, path: str, body: bytes | None, content_type: str, key: str, *, method: str = 'POST') -> dict:
    for attempt in range(_REQUEST_MAX_ATTEMPTS):
        request = Request(base + path, data=body, method=method, headers={
            "Authorization": "Bearer " + token, "Content-Type": content_type,
            "Idempotency-Key": key, "X-Operator": "Codex-Automation",
        })
        try:
            with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                result = json.load(response)
            break
        except HTTPError as exc:
            # Never echo request headers, response bodies or credential-bearing URLs.
            raise IngestAPIError(_safe_http_failure(exc, path)) from None
        except (URLError, OSError, ValueError):
            if attempt + 1 < _REQUEST_MAX_ATTEMPTS:
                # Reuse the same idempotency key and payload after an uncertain response.
                time.sleep(_REQUEST_RETRY_DELAY_SECONDS)
                continue
            raise IngestAPIError("API上传连接或响应异常，归档文件已保留") from None
    if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
        raise IngestAPIError("API上传响应缺少data")
    return result["data"]


def submit_archived_reports(root: Path, artifacts: list[dict], *, metadata: dict | None = None,
                            report_types: list[str] | None = None, source: str = 'api', period: dict | None = None) -> dict:
    if not artifacts:
        return {"submitted": 0}
    root = root.resolve()
    files = []
    for artifact in artifacts:
        path = (root / artifact["relative_path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise IngestAPIError("API上传归档路径无效")
        if path.suffix.lower() not in {".csv", ".xls", ".xlsx", ".xlsm"}:
            raise IngestAPIError("API上传需要完成解压的标准报表")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if artifact.get("file_hash") and artifact["file_hash"] != digest:
            raise IngestAPIError("API上传文件哈希与归档回执不一致")
        files.append((path, content, digest, artifact))
    base = os.getenv("INGEST_API_BASE_URL", "http://127.0.0.1:8770").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise IngestAPIError("INGEST_API_BASE_URL必须为不含凭据的HTTP服务地址")
    if source == 'manual':
        from apps.file_ingest.cli import Client
        username,password=os.getenv('INGEST_USERNAME'),os.getenv('INGEST_PASSWORD')
        if not username or not password:
            raise IngestAPIError('人工终端上传需要用户登录：请使用apps.file_ingest.cli交互登录，或在未提交.env配置INGEST_USERNAME和INGEST_PASSWORD')
        try:
            client=Client(base,username,password)
        except (HTTPError,URLError,OSError,ValueError):
            raise IngestAPIError('人工终端上传登录失败，归档已保留；请检查登录和上传权限') from None
        def request(path,body=None,content_type='application/json',key='',method='POST'):
            try:return client.call(method,path,body=body,content_type=content_type,key=key or None)
            except (HTTPError,URLError,OSError,ValueError):
                raise IngestAPIError('人工终端API上传或预检失败，归档已保留；请在导入记录查看草稿') from None
    elif source == 'api':
        token = os.getenv("INGEST_ROBOT_TOKEN", "")
        if not token:
            raise IngestAPIError("API上传需要项目.env中的INGEST_ROBOT_TOKEN")
        def request(path,body=None,content_type='application/json',key='',method='POST'):
            return _request(base,token,path,body,content_type,key,method=method)
    else:
        raise IngestAPIError('上传来源必须为manual或api')
    from apps.file_ingest.naming import comparison_key
    shops=request('/api/ingest/shops',method='GET')['items']
    prepared=[]
    for path,content,digest,artifact in files:
        identity=metadata or {}
        matches=[shop for shop in shops if (
            artifact.get('shop_code') and shop['shop_code']==artifact['shop_code'] and
            (not artifact.get('platform_code') or shop['platform_code']==artifact['platform_code'])
        ) or (all(identity.get(k) for k in ('platform','company','shop')) and all(
            comparison_key(shop[field])==comparison_key(identity[key]) for key,field in (
                ('platform','platform_name'),('company','company_name'),('shop','shop_name'))))]
        if len(matches)!=1:
            raise IngestAPIError('Profile/回执必须唯一匹配DIM标准店铺，不能依据文件名或平台默认店铺上传')
        shop=matches[0]
        report_type=artifact.get('report_type') or (report_types[0] if report_types and len(report_types)==1 else None)
        if not report_type:
            raise IngestAPIError('归档回执缺少明确report_type，停止上传')
        claim={}
        if report_type in {'douyin_fund','douyin_settlement','jd_fund','jd_settlement'}:
            if artifact.get('coverage_verified') and artifact.get('business_date_start') and artifact.get('business_date_end'):
                claim={'start':artifact['business_date_start'],'end':artifact['business_date_end'],
                       'complete_export':True,'reason':'归档回执绑定的完整查询范围'}
            if (report_type=='jd_settlement' and artifact.get('coverage_verified')
                    and artifact.get('business_date_start')
                    and artifact.get('business_date_start')==artifact.get('business_date_end')):
                # The plan period is only the requested day; JD may export the
                # latest available bill date instead. Use the verified artifact
                # date when filling blank CSV date cells so it stays within the
                # declared complete-export range.
                claim['bill_date']=artifact['business_date_start']
        fields={'report_type':report_type,'shop_code':shop['shop_code'],'platform_name':shop['platform_name'],
                'company_name':shop['company_name'],'shop_name':shop['shop_name'],'coverage':json.dumps(claim,ensure_ascii=False)}
        prepared.append((path,content,digest,fields))
    identities=sorted((p.relative_to(root).as_posix(),d,json.dumps(f,sort_keys=True,ensure_ascii=False)) for p,_,d,f in prepared)
    key='archive-'+source+':'+hashlib.sha256(json.dumps(identities,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    run = request('/api/ingest/runs',json.dumps({
        'source':source,'idempotency_key':key,'expected_file_count':len(prepared),'auto_refresh':True,
    }).encode(),key=key)
    run_id = str(run["run_id"])
    if run["status"] != "draft":
        if run["status"] in {"failed", "partial_failed"}:
            raise IngestAPIError("API导入批次存在失败，请在导入记录中处理后重试")
        return {"ingest_run_id": run_id, "submitted": len(files), "reused": True}
    for path, content, digest, fields in prepared:
        file_key = hashlib.sha256((path.relative_to(root).as_posix() + ":" + digest).encode()).hexdigest()
        boundary = "codex-" + uuid.uuid4().hex
        filename = path.name.replace('"', '').replace('\r', '').replace('\n', '')
        fields['client_file_id']=file_key
        metadata_parts=''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n' for field,value in fields.items())
        prefix = (metadata_parts+f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                  'Content-Type: application/octet-stream\r\n\r\n').encode("utf-8")
        body = prefix + content + f"\r\n--{boundary}--\r\n".encode()
        request(f"/api/ingest/runs/{run_id}/files",body,"multipart/form-data; boundary="+boundary,file_key)
    preview=request(f'/api/ingest/runs/{run_id}/coverage-preflight',b'{}',key=key)
    if preview['blocked']:
        raise IngestAPIError('来源预检存在差异，归档和上传草稿已保留，请人工核对；自动化未覆盖旧来源')
    request(f'/api/ingest/runs/{run_id}/complete',json.dumps({'preflight_token':preview['token']}).encode(),key=key)
    return {"ingest_run_id": run_id, "submitted": len(files), "reused": False,'preflight_summary':preview.get('summary',{})}
