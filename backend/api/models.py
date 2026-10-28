"""模型页接口（设计文档 5、D21）：都在 /api/settings/models 下。

对话页的模型下拉框仍用 GET /api/models。
"""

from fastapi import APIRouter, status

from agents.main_agent.models import ModelTestResult
from backend.api.deps import ServicesDep
from backend.models import DefaultInput, ModelInput, ModelsView, ModelView
from backend.models.schemas import DeleteResult

models_router = APIRouter(prefix="/settings/models")


@models_router.get("")
async def list_models(services: ServicesDep) -> ModelsView:
    return await services.models.list()


@models_router.post("", status_code=status.HTTP_201_CREATED)
async def add_model(body: ModelInput, services: ServicesDep) -> ModelView:
    """新增模型：存进网关数据库，立即生效（不用重启网关）。"""
    return await services.models.add(body)


@models_router.put("/default")
async def set_default_chat(body: DefaultInput, services: ServicesDep) -> ModelsView:
    """改默认对话模型（只影响新会话的起点）；向量模型只读。"""
    return await services.models.set_default_chat(body.name)


@models_router.put("/{name}")
async def update_model(name: str, body: ModelInput, services: ServicesDep) -> ModelView:
    return await services.models.update(name, body)


@models_router.delete("/{name}")
async def delete_model(name: str, services: ServicesDep) -> DeleteResult:
    """删除页面加的模型；在用它的会话改用默认对话模型。"""
    return await services.models.delete(name)


@models_router.post("/{name}/test")
async def test_model(name: str, services: ServicesDep) -> ModelTestResult:
    """真的调用一次（花几个 token）。"""
    return await services.models.test(name)
