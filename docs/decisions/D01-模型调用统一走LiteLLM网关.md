# D01：模型调用全部走 LiteLLM 网关（独立容器）

- 状态：已采纳
- 日期：2026-10-12

## 背景

要同时支持 Claude、OpenAI / Gemini、国产模型（DeepSeek / Qwen / Kimi / GLM 等），能按会话切换具体版本；知识库的向量化同样要调用模型（D15）。成功标准要求"加模型版本只改配置，业务代码不动"。LiteLLM 是一个用同一种写法调用各家大模型的开源工具，可以作为库嵌进代码，也可以部署成独立的"模型网关"服务。

## 备选方案

1. 在代码里直接调用 LiteLLM 库，不单独部署网关。
2. 直连各厂商的官方接口。
3. 经 OpenRouter 等第三方模型聚合服务调用。
4. 部署 LiteLLM 网关作为独立容器，所有调用都经过它。

设计文档把 1～3 列为"模型网关"接口以后可替换成的实现（4.1 节），没有展开逐项比较。

## 结论

- 所有模型调用（对话与向量化）都经 compose 中的 `litellm` 服务；`config/models.yaml` 直接挂载为网关的模型清单（见 D03）。
- 网关藏在"模型网关"可替换接口后面（`config/app.yaml` 的 `adapters.model_gateway` 选择实现），业务代码不直接引用 litellm。
- 智能体一侧用 langchain-litellm（LangChain 与 LiteLLM 的对接包）的 `ChatLiteLLM` 连接网关，不用通用的 `ChatOpenAI`——后者会丢弃思考内容，Claude 深度思考加工具调用会报错。
- 模型调用失败时由网关先自动重试、切换备用模型，仍失败才结束运行。

落地：M0：`agents/main_agent/models/base.py`（接口）、`agents/main_agent/models/litellm_proxy.py`（实现）、`agents/main_agent/bootstrap.py`（登记）、`config/models.yaml`、`deploy/docker-compose.yml` 的 `litellm` 服务；契约测试 `agents/tests/contracts/test_model_gateway_contract.py`。目前模型来源是公司的 LiteLLM 网关，本地网关以 `litellm_proxy/` 方式转发。

## 原因与代价

- 所有模型调用收拢到一个入口，密钥、重试、备用切换集中管理，本机其他工具也能共用这个网关。
- M0 先行验证 V1、V2 通过：经"本地网关 → 公司网关"两级转发，Claude 深度思考 + 多轮工具调用 + 逐字输出正常，思考块与签名得以保留；流式输出时每次调用都带输入、输出 token 及缓存、思考明细。
- 代价：多一个要运行的服务（网关在 PostgreSQL 里另占一个 `litellm` 库）；deepagents 自带的 Anthropic 提示缓存中间件只对官方 `ChatAnthropic` 生效，走网关用不上，要改在网关配置中为 Claude 开启缓存注入点（M0 时尚未配置）；LiteLLM 模型对象不带上下文长度，需由模型网关接口把读到的长度填进去，deepagents 才知道何时压缩上下文。
- 风险：litellm 曾出现投毒版本（1.82.7 / 1.82.8），靠精确版本、锁文件哈希和固定网关镜像规避（见 D12）；LiteLLM 导入时会联网拉价格表，统一设置 `LITELLM_LOCAL_MODEL_COST_MAP=True` 关闭。
