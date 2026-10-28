"""模型页的业务规则（D21）。

- 模型全部存在网关数据库里（网关的模型管理接口，D22），不用重启网关；首次启动时导入 4 个模型
  （config/seed/models.yaml），之后都能改、能删。
- 名字不能与网关里已有的任何模型相同：同名时网关会把两份一起分摊调用，而不是覆盖。
- 默认对话模型不能删，也不能改成向量模型；有运行正在用（运行中、等审批）的模型不能删；
  删掉别的模型后，在用它的会话改用默认对话模型，历史与用量保留。
- 模型名不能叫 default：和"设默认模型"的接口地址（PUT /default）冲突。
- 默认对话模型存进设置表（D22），并且立即生效。向量模型只读（R31）。
"""

from agents.main_agent.models import ModelGateway, ModelInfo, ModelSpec, ModelTestResult
from backend.models.schemas import DeleteResult, ModelInput, ModelsView, ModelView
from backend.runs import RunRepo
from backend.settings.app_settings import AppSettingsService
from backend.threads import ThreadRepo
from common.errors import ConflictError, InvalidRequestError, NotFoundError
from config import Settings
from config.settings import ModelSource

_NOT_IN_DB = "这个模型写在 config/models.yaml 里、不在网关数据库中，页面上不能改"
_PER_MILLION = 1_000_000
# 与默认模型清单 config/seed/models.yaml 里 Claude 的写法一致：
# 深度思考用 adaptive，单次输出上限 64000
_CLAUDE_MAX_TOKENS = 64000


def is_claude(upstream_id: str) -> bool:
    """厂商模型 ID 是 Claude 系列：深度思考用 adaptive 参数，能打提示缓存。"""
    return "claude" in upstream_id.lower()


class ModelAdmin:
    def __init__(
        self,
        settings: Settings,
        gateway: ModelGateway,
        threads: ThreadRepo,
        app_settings: AppSettingsService,
        runs: RunRepo,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._threads = threads
        self._app_settings = app_settings
        self._runs = runs

    async def list(self) -> ModelsView:
        models = await self._gateway.list_models()
        counts = await self._threads.model_counts()
        chat, embedding = self._defaults()
        return ModelsView(
            models=[
                ModelView(
                    **model.model_dump(),
                    source_label=self._source_label(model),
                    sessions=counts.get(model.name, 0),
                    is_default_chat=model.name == chat,
                    is_default_embedding=model.name == embedding,
                )
                for model in models
            ],
            default_chat=chat,
            default_embedding=embedding,
            sources=self._settings.models.sources,
        )

    async def add(self, item: ModelInput) -> ModelView:
        # 放在这里、不放进表单校验：网关里已有的同名模型照样能还原成表单、导入默认模型不受影响
        if item.name == "default":
            raise InvalidRequestError("模型名不能叫 default：和“设默认模型”的接口地址冲突")
        models = await self._gateway.list_models()
        if any(model.name == item.name for model in models):
            raise ConflictError(f"已有同名模型：{item.name}")
        info = await self._gateway.add_model(self._spec(item))
        return await self._view(info)

    async def update(self, name: str, item: ModelInput) -> ModelView:
        if item.name != name:
            raise InvalidRequestError("模型名不能改：在用它的会话按名字对应")
        model = await self._editable(name)
        assert model.id is not None  # 页面加的模型都有部署编号
        if item.mode != "chat" and name == self._defaults()[0]:
            # 改了以后默认值与模型页、设置页的下拉框对不上（积压小问题 F12）
            raise ConflictError("这是默认对话模型，不能改成向量模型：先换一个默认对话模型")
        info = await self._gateway.update_model(model.id, self._spec(item))
        return await self._view(info)

    async def delete(self, name: str) -> DeleteResult:
        model = await self._editable(name)
        chat, embedding = self._defaults()
        if name in (chat, embedding):
            raise ConflictError("先换掉默认再删")
        if await self._runs.count_active(name):
            # 正在跑、等审批的运行按运行上记的模型接着调用，删了就会失败（积压小问题 F9）
            raise ConflictError("有对话正在用这个模型（运行中或等审批），等它结束或停止后再删")
        assert model.id is not None
        await self._gateway.delete_model(model.id)  # 网关出错时抛出，会话不动
        return DeleteResult(reassigned=await self._threads.reassign_model(name, chat))

    async def enable_prompt_caching(self) -> tuple[str, ...] | None:
        """给网关数据库里还没开提示缓存的 Claude 对话模型打开缓存（设计 2026-10-23 4.1），
        其余设置原样保留；返回改过的模型名。

        清单里一个数据库里的模型都没有时返回 None：网关可能刚启动、还没载入，这时什么都不改。
        网关出错时抛 UpstreamError。
        """
        listed = await self._gateway.list_models()
        if not any(model.id is not None for model in listed):
            return None
        changed: tuple[str, ...] = ()
        for model in listed:
            item = self.input_of(model)
            if (
                model.id is None
                or item is None
                or item.mode != "chat"
                or model.supports_prompt_caching
                or not is_claude(item.upstream_id)
            ):
                continue
            await self.update(model.name, item.model_copy(update={"supports_prompt_caching": True}))
            changed += (model.name,)
        return changed

    def input_of(self, model: ModelInfo) -> ModelInput | None:
        """网关里的模型还原成页面的表单（来源按模型名前缀认出）；认不出来源时返回 None。"""
        upstream = model.upstream or ""
        source = next(
            (s for s in self._settings.models.sources if upstream.startswith(s.prefix)), None
        )
        if source is None:
            return None
        return ModelInput(
            name=model.name,
            source=source.id,
            upstream_id=upstream[len(source.prefix) :],
            mode="embedding" if model.mode == "embedding" else "chat",
            max_input_tokens=model.max_input_tokens,
            max_output_tokens=model.max_output_tokens,
            price_input=(model.input_cost_per_token or 0) * _PER_MILLION,
            price_output=(model.output_cost_per_token or 0) * _PER_MILLION,
            supports_reasoning=model.supports_reasoning,
            supports_vision=model.supports_vision,
            supports_function_calling=model.supports_function_calling,
            supports_prompt_caching=model.supports_prompt_caching,
        )

    async def require_chat(self, name: str) -> None:
        """会话要换的模型必须在网关里，并且是对话模型。"""
        model = await self._find(name, missing=InvalidRequestError)
        if model.mode != "chat":
            raise InvalidRequestError("只能选对话模型")

    async def test(self, name: str) -> ModelTestResult:
        await self._find(name)
        return await self._gateway.test_model(name)

    async def set_default_chat(self, name: str) -> ModelsView:
        model = await self._find(name, missing=InvalidRequestError)
        if model.mode != "chat":
            raise InvalidRequestError("默认对话模型只能选对话模型")
        # 存进设置表并立即生效：新建的会话立即用它，不用重启（被环境变量指定时拒绝）
        await self._app_settings.update("agent.default_model", name)
        return await self.list()

    # ---- 内部 ----

    def _defaults(self) -> tuple[str, str]:
        return self._settings.agent.default_model, self._settings.knowledge.embedding_model

    def _source(self, source_id: str) -> ModelSource:
        for source in self._settings.models.sources:
            if source.id == source_id:
                return source
        raise InvalidRequestError(f"没有这个来源：{source_id}")

    def _source_label(self, model: ModelInfo) -> str:
        for source in self._settings.models.sources:
            if model.upstream and model.upstream.startswith(source.prefix):
                return source.label
        return "其他"

    def _spec(self, item: ModelInput) -> ModelSpec:
        source = self._source(item.source)
        if source.mode != item.mode:
            kinds = {"chat": "对话", "embedding": "向量"}
            raise InvalidRequestError(
                f"来源“{source.label}”只能加{kinds[source.mode]}模型，和所选类型对不上"
            )
        extra: dict[str, object] = {}
        claude = is_claude(item.upstream_id)
        if item.supports_reasoning and claude:
            limit = min(_CLAUDE_MAX_TOKENS, item.max_output_tokens or _CLAUDE_MAX_TOKENS)
            extra = {"thinking": {"type": "adaptive"}, "max_tokens": limit}
        return ModelSpec(
            name=item.name,
            upstream=f"{source.prefix}{item.upstream_id}",
            api_base=source.api_base,
            api_key=source.api_key,
            mode=item.mode,
            max_input_tokens=item.max_input_tokens,
            max_output_tokens=item.max_output_tokens,
            input_cost_per_token=item.price_input / _PER_MILLION,
            output_cost_per_token=item.price_output / _PER_MILLION,
            supports_reasoning=item.supports_reasoning,
            supports_vision=item.supports_vision,
            supports_function_calling=item.supports_function_calling,
            supports_prompt_caching=item.supports_prompt_caching and claude,
            extra_params=extra,
        )

    async def _find(self, name: str, *, missing: type[Exception] = NotFoundError) -> ModelInfo:
        for model in await self._gateway.list_models():
            if model.name == name:
                return model
        raise missing(f"没有这个模型：{name}")

    async def _editable(self, name: str) -> ModelInfo:
        model = await self._find(name)
        if model.id is None:
            raise ConflictError(_NOT_IN_DB)
        return model

    async def _view(self, info: ModelInfo) -> ModelView:
        chat, embedding = self._defaults()
        counts = await self._threads.model_counts()
        return ModelView(
            **info.model_dump(),
            source_label=self._source_label(info),
            sessions=counts.get(info.name, 0),
            is_default_chat=info.name == chat,
            is_default_embedding=info.name == embedding,
        )
