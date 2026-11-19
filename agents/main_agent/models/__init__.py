"""模型能力模块：对外公开模型网关与向量化接口、模型信息、卡住时的错误、额度用完与失败类型的识别、
网关实现、换模型清理与 token 估算。"""

from agents.main_agent.models.base import (
    ModelGateway,
    ModelInfo,
    ModelSpec,
    ModelStalledError,
    ModelTestResult,
    version_name,
)
from agents.main_agent.models.calls import (
    CallContext,
    call_context,
    current_call,
    detached_context,
)
from agents.main_agent.models.cleanup import ModelSwitchCleanupMiddleware
from agents.main_agent.models.embedding import (
    EMBEDDING_DIMENSIONS,
    Embedder,
    EmbeddingUsage,
    EmbedKind,
    LiteLLMProxyEmbedder,
)
from agents.main_agent.models.estimate import estimate_input_tokens, estimate_text_tokens
from agents.main_agent.models.failures import ErrorKind, classify_failure
from agents.main_agent.models.litellm_proxy import LiteLLMProxyGateway
from agents.main_agent.models.onnx_download import ensure_model
from agents.main_agent.models.onnx_embedder import (
    ONNX_MODELS,
    OnnxEmbedder,
    OnnxModelFile,
    OnnxModelSpec,
    OnnxRuntime,
    files_ready,
)
from agents.main_agent.models.quota import is_quota_exhausted

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "ONNX_MODELS",
    "CallContext",
    "EmbedKind",
    "Embedder",
    "EmbeddingUsage",
    "ErrorKind",
    "LiteLLMProxyEmbedder",
    "LiteLLMProxyGateway",
    "ModelGateway",
    "ModelInfo",
    "ModelSpec",
    "ModelStalledError",
    "ModelSwitchCleanupMiddleware",
    "ModelTestResult",
    "OnnxEmbedder",
    "OnnxModelFile",
    "OnnxModelSpec",
    "OnnxRuntime",
    "call_context",
    "classify_failure",
    "current_call",
    "detached_context",
    "ensure_model",
    "estimate_input_tokens",
    "estimate_text_tokens",
    "files_ready",
    "is_quota_exhausted",
    "version_name",
]
