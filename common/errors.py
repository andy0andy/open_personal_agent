"""与业务无关的通用错误类型；backend 统一把它们映射为 HTTP 状态码。"""


class AppError(Exception):
    """可预期错误的基类。"""


class NotFoundError(AppError):
    """目标资源不存在。"""


class ConflictError(AppError):
    """与当前状态冲突，例如同一会话已有进行中的运行。"""


class UpstreamError(AppError):
    """依赖的外部服务（如模型网关）不可用。"""


class TooLargeError(AppError):
    """内容超过允许的大小，例如上传的文件超过上限。"""


class UnsupportedError(AppError):
    """格式不支持（如上传了不能处理的文件类型）。"""


class InvalidConfigError(AppError):
    """配置文件写错了（YAML 语法、未知字段、缺少必填项等）。"""


class InvalidRequestError(AppError):
    """请求的内容与当前状态对不上，例如审批的决定数量不对。"""
