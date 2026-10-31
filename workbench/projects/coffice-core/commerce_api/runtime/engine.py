"""One business execution core for CLI and future workbench integration."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from pathlib import Path
from urllib.parse import urlsplit

from ..core.contracts import ReportRequest, ReportResult, now_iso
from ..core.errors import AuthRequired, ChallengeExpired, CommerceError, ContextRequired, ContractError, IdentityMismatch, NeedsHuman, NotReady, OutcomeUnknown
from ..core.registry import Registry, load_symbol
from .auth import AuthManager, profile_binding
from .files import download, valid_receipt
from .runs import Run, business_key
from .sessions import session_key
from .storage import Paths, atomic_json, file_lock, read_json


class Context:
    def __init__(self, paths, run, profile, backend, client, *, human_timeout=300):
        self.paths, self.run, self.profile, self.backend, self.client = paths, run, profile, backend, client
        self.request = ReportRequest.restore(run.state["request"])
        self.human_timeout = human_timeout

    def private(self, name, value=None):
        from .private import load, save
        values = load(self.paths, self.run.id)
        if value is not None:
            values[name] = value
            save(self.paths, self.run.id, values)
        return values.get(name)

    def bind_account(self, name, identifier):
        if identifier in (None, ""):
            raise ContractError("业务账户缺少稳定标识", stage="identity")
        fingerprint = hashlib.sha256(str(identifier).encode()).hexdigest()
        accounts = self.run.state.setdefault("account_scopes", {})
        if name in accounts and accounts[name] != fingerprint:
            raise IdentityMismatch("续跑的业务账户与原任务不一致", stage="identity")
        accounts[name] = fingerprint
        self.run.save()

    async def submit(self, name, operation, *, reference=None, reconcile=False):
        """Persist intent before sending; never automatically replay unknown effects."""
        self.run.begin(name, reconcile=reconcile)
        try:
            result = await operation()
            references = reference(result) if reference else {}
        except AuthRequired:
            self.run.state["operations"][name]["status"] = "rejected_auth"
            self.run.save()
            raise
        except ContractError as exc:
            self.run.state["operations"][name]["status"] = "rejected_business" if exc.details.get("business_code") else "unknown"
            self.run.save()
            raise
        except BaseException:
            self.run.state["operations"][name]["status"] = "unknown"
            self.run.save()
            raise
        self.run.confirmed(name, **references)
        return result

    async def poll(self, operation, ready, *, stage="poll"):
        deadline = time.monotonic() + self.request.timeout
        self.run.update(stage=stage)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NotReady("平台任务尚未就绪，已保留原任务供续跑", stage=stage)
            try:
                result = await asyncio.wait_for(operation(), timeout=remaining)
            except TimeoutError:
                raise NotReady("平台任务轮询超时，已保留原任务供续跑", stage=stage) from None
            selected = ready(result)
            if selected is not None:
                return selected
            if time.monotonic() >= deadline:
                raise NotReady("平台任务尚未就绪，已保留原任务供续跑", stage=stage)
            await asyncio.sleep(min(self.request.poll_interval, max(.01, deadline - time.monotonic())))

    async def download(self, url, extension, *, label=None, headers=None, actual_period=None):
        self.run.update(stage="download")
        period = self.request.period
        name = f"{self.request.platform}_{label or self.request.kind}_{self.backend.id}_{period.start}_to_{period.end}{extension}"
        artifact_key = f"{label or self.request.kind}:{actual_period or period.public()}"
        previous = next((f for f in self.run.state["files"] if
            (f.get("artifact_key") == artifact_key or Path(f.get("path", "")).stem == Path(name).stem)
            and valid_receipt(f)), None)
        if previous:
            return previous
        # The URL is obtained by a fixed registered API workflow, never a CLI URL
        # argument. Restrict redirects to the same returned file host and platform.
        cdn = {"jd": ("jd.com", "jdcloud.com", "jcloudcs.com", "360buyimg.com"),
               "tmall": ("alipay.com", "alipayobjects.com", "taobao.com", "alicdn.com"),
               "douyin": ("bytecdn.cn", "ibytedtos.com", "bytedance.com", "jinritemai.com"),
               "pinduoduo": ("pinduoduo.com", "pddpic.com"),
               "kuaishou": ("kwaixiaodian.com", "kuaishou.com", "ksapisrv.com", "kuaishoupay.com"),
               "xiaohongshu": ("xiaohongshu.com", "xhscdn.com")}
        hosts = tuple(set(self.backend.domains) | set(cdn.get(self.request.platform, ())) | {urlsplit(url).hostname or ""})
        file = await download(url, self.paths.root / "downloads" / self.run.id, name,
            client=self.client.http.client, headers=self.client.http.headers(url, headers),
            allowed_hosts=hosts, period=actual_period or period.public())
        file.update(artifact_key=artifact_key, role="report")
        self.run.state["files"].append(file)
        self.run.save()
        return file

    def result(self, status="downloaded", *, row_count=None, actual_period=None):
        return ReportResult(status=status, run_id=self.run.id, platform=self.request.platform,
            backend=self.request.backend, kind=self.request.kind, profile=self.profile.name,
            requested_period=self.request.period.public(), actual_period=actual_period or (self.request.period.public() if status != "no_data" else None),
            files=self.run.state["files"], row_count=row_count, identity=self.client.identity_data)

    async def register_verification(self, *, purpose, kind="verification_code", name="verification", defer_human_notice=False, reference=None):
        from ..integrations.legacy.verification import create
        operation = self.run.state["operations"].get(name, {})
        identifier = operation.get("challenge_id")
        if not identifier:
            if reference is None and self.profile.platform == "jd" and kind == "archive_password":
                task = str(self.run.reference("create_export") or "")
                if not task.isdigit():
                    raise ContractError("京东文件密码接收必须绑定原导出任务的真实 taskId", stage=name)
                reference = "taskid-" + task
            challenge = await create(self.profile, purpose=purpose, kind=kind, reference=reference or "",
                defer_human_notice=defer_human_notice, force_human=bool(operation.get("human_required")))
            identifier = challenge.get("challenge_id")
            if not identifier:
                raise ContractError("原验证码服务没有返回 Challenge 标识", stage=name)
            operation.update(status="sent" if operation.get("skip_resend") else "registered", challenge_id=identifier)
            self.run.state["operations"][name] = operation
            self.run.save()
        return identifier

    async def cancel_verification(self, name):
        from ..integrations.legacy.verification import cancel
        operation = self.run.state["operations"].get(name, {})
        identifier = operation.get("challenge_id")
        if identifier:
            await cancel(identifier)
            operation.update(status="cancelled", previous_challenge_id=identifier)
            operation.pop("challenge_id", None)
            self.run.save()

    async def verification(self, *, purpose, send, verify=None, kind="verification_code", name="verification", _replaced=False):
        from ..integrations.legacy.verification import answer
        identifier = await self.register_verification(purpose=purpose, kind=kind, name=name)
        status = self.run.state["operations"][name].get("status")
        if status not in {"sent", "answered", "sending", "unknown"}:
            self.run.state["operations"][name]["status"] = "sending"
            self.run.save()
            try:
                await send()
            except AuthRequired:
                self.run.state["operations"][name]["status"] = "registered"
                self.run.save()
                raise
            except BaseException:
                self.run.state["operations"][name]["status"] = "unknown"
                self.run.save()
                raise
            self.run.state["operations"][name]["status"] = "sent"
            self.run.save()
        try:
            value = await answer(identifier, timeout_seconds=self.human_timeout)
        except ChallengeExpired:
            if _replaced:
                raise
            operation = self.run.state["operations"][name]
            # Follow the existing expiry rule: an expired listener is replaced
            # and the new challenge's callback runs once. While a challenge is
            # valid, uncertain sends never run again. Archive renewal requests
            # manual confirmation as in the legacy flow.
            operation.update(status="registered", previous_challenge_id=identifier,
                human_required=kind == "archive_password", skip_resend=False)
            operation.pop("challenge_id", None)
            self.run.save()
            return await self.verification(purpose=purpose, send=send, verify=verify, kind=kind, name=name, _replaced=True)
        self.run.state["operations"][name]["status"] = "answered"
        self.run.save()
        return await verify(value) if verify else value


class Engine:
    def __init__(self, paths=None, registry=None, *, auth=None, use_legacy_lock=True):
        self.paths = paths or Paths()
        self.registry = registry or Registry()
        self.auth = auth or AuthManager(self.paths, self.registry)
        self.use_legacy_lock = use_legacy_lock

    async def execute(self, request: ReportRequest, *, resume=None, recover=True, human_timeout=300):
        spec = self.registry.report(request.platform, request.kind, request.backend)
        if request.period.mode not in spec.modes:
            raise ContractError("该报表尚不支持请求日期模式", stage="plan")
        if request.timeout <= 0 or request.poll_interval <= 0:
            raise ContractError("超时与轮询间隔必须为正数", stage="plan")
        if not 1 <= human_timeout <= 300:
            raise ContractError("人工回复等待时间必须在 1 到 300 秒之间", stage="plan")
        profile = profile_binding(self.paths, request.profile, request.platform)
        backend = self.registry.backend(request.platform, request.backend)
        run = Run.load(self.paths, resume) if resume else None
        if run and (run.state["profile_id"] != profile.id or run.state["request"] != request.public()):
            raise ContractError("续跑请求必须与冻结的原计划及 Profile 完全一致", stage="resume")
        local_lock = self.paths.file("locks", session_key(profile.id, profile.platform, backend.id), ".lock")
        if self.use_legacy_lock:
            from ..integrations.legacy.locking import legacy_browser_lock
            shared = legacy_browser_lock()
        else:
            shared = contextlib.nullcontext()
        with file_lock(local_lock), shared:
            index = self.paths.file("requests", business_key(request, profile.id))
            if run is None:
                previous = read_json(index, {}).get("run_id")
                if previous:
                    run = Run.load(self.paths, previous)
                    # Recovery retains the exact original execution plan, including
                    # its timing options. A fresh invocation cannot reset intent.
                    request = ReportRequest.restore(run.state["request"])
                else:
                    run = Run.create(self.paths, request, profile.id)
            atomic_json(index, {"run_id": run.id})
            if run.state.get("status") in {"downloaded", "reused", "no_data"}:
                if run.state["status"] == "no_data" and resume or all(valid_receipt(f) for f in run.state["files"]) and run.state["files"]:
                    if not resume and hasattr(self.auth, "store"):
                        try:
                            current = self.auth.store.load(session_key(profile.id, profile.platform, backend.id)).get("identity", {})
                        except AuthRequired:
                            current = {}
                        pinned = run.state.get("identity_scope") or {k: run.state.get("result", {}).get("identity", {}).get(k)
                            for k in ("shop_id", "advertiser_id", "fund_account_fingerprint")
                            if run.state.get("result", {}).get("identity", {}).get(k)}
                        current = {k: current[k] for k in ("shop_id", "advertiser_id", "fund_account_fingerprint") if k in current}
                        if current and pinned and current != pinned:
                            raise IdentityMismatch("当前后台账户与已有文件归属不同，请明确业务账户后执行新请求", stage="identity")
                    result = run.state["result"]
                    if run.state.get("error"):
                        run.update(error=None)
                    return {**result, "status": "reused" if run.state["files"] else "no_data"}
            client = None
            try:
                recovered = False
                try:
                    await self.auth.check(profile, backend, recover=False, account_id=request.account_id, already_locked=True)
                except AuthRequired:
                    if not recover:
                        raise
                    await self.auth.login(profile, backend, account_id=request.account_id, already_locked=True)
                    recovered = True
                handler = load_symbol(spec.handler)
                for attempt in range(2):
                    client = self.auth.client(profile, backend)
                    try:
                        client.identity_data = client.credential.get("identity", {})
                        identity_scope = {k: client.identity_data[k] for k in
                            ("shop_id", "advertiser_id", "fund_account_fingerprint") if k in client.identity_data}
                        if run.state.get("identity_scope") and run.state["identity_scope"] != identity_scope:
                            raise IdentityMismatch("HTTP 店铺或子后台账户与原任务不一致，拒绝续跑", stage="identity")
                        run.update(identity_scope=identity_scope)
                        ctx = Context(self.paths, run, profile, backend, client, human_timeout=human_timeout)
                        run.update(status="running")
                        result = await handler(ctx, request)
                        public = result.public() if isinstance(result, ReportResult) else result
                        if not isinstance(public, dict) or public.get("status") not in {"downloaded", "reused", "no_data"}:
                            raise ContractError("报表服务没有返回有效成果状态", stage="complete")
                        run.update(status=public["status"], stage="complete", result=public, error=None, finished_at=now_iso())
                        return public
                    except AuthRequired:
                        if not recover or recovered or attempt:
                            raise
                        await client.close()
                        client = None
                        await self.auth.login(profile, backend, account_id=request.account_id, already_locked=True)
                        recovered = True
                    finally:
                        if client:
                            await client.close()
                            client = None
            except BaseException as exc:
                state = "cancelled" if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)) else getattr(exc, "code", "FAILED").lower()
                error = exc.public() if isinstance(exc, CommerceError) else {"code": "FAILED", "message": type(exc).__name__}
                run.update(status=state, error=error)
                if isinstance(exc, (NeedsHuman, ContextRequired, IdentityMismatch)) and exc.stage in {
                        "request", "response", "identity", "context", "auth"} and hasattr(self.auth, "_status"):
                    self.auth._status(profile, backend, exc.code.lower(), error=exc.public())
                if isinstance(exc, CommerceError):
                    exc.details = {**exc.details, "run_id": run.id}
                if isinstance(exc, Exception) and not run.state.get("failure_notified"):
                    from ..integrations.legacy.notifications import notify
                    sent = await notify(profile, f"报表 API：{spec.name}，阶段 {run.state['stage']}，状态 {state}，任务 {run.id}")
                    run.update(failure_notified=sent)
                raise
