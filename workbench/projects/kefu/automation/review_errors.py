"""供 HTTP、后台和 CLI 共用的业务错误；不携带平台原始响应或凭据。"""

class ReviewError(RuntimeError):
    code = "API_ERROR"
    recoverable = False
    recovery_action = "检查平台状态后重试"


class ContractError(ReviewError):
    code = "CONTRACT_ERROR"
    recovery_action = "核对接口契约后重试"


class AccountUnavailable(ContractError):
    code = "ACCOUNT_UNAVAILABLE"
    recovery_action = "核对店铺的停用、关店状态和同步配置"


class HumanRequired(ReviewError):
    code = "NEEDS_HUMAN"
    recoverable = True
    recovery_action = "在对应 profile 完成验证或确认权限后重新登录"


class AuthRequired(HumanRequired):
    code = "AUTH_REQUIRED"
    recovery_action = "commerce auth login --profile <店铺profile>"


class LoginFailed(ReviewError):
    code = "LOGIN_FAILED"
    recovery_action = "检查登录失败原因后重试未完成任务"


class AuthStoreError(ReviewError):
    code = "AUTH_STORE_ERROR"
    recoverable = True
    recovery_action = "使用同一 Windows 用户重新执行 auth login"


class NetworkError(ReviewError):
    code = "NETWORK_ERROR"
    recoverable = True
    recovery_action = "检查网络后重试；无需重新登录"


class NotSupported(ReviewError):
    code = "NOT_SUPPORTED"
    recovery_action = "运行 commerce platforms 查看已实现的平台"
