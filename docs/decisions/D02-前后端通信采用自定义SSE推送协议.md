# D02：前后端通信用自定义推送协议（SSE），不用 AG-UI

- 状态：已采纳
- 日期：2026-10-12

## 背景

一次运行可能持续很久，过程中要把回答逐字、思考过程、工具调用、子智能体嵌套、待办、审批、产物等实时推给浏览器；关掉浏览器再打开，正在跑的任务和已推送的内容都不能丢。SSE（服务器单向推送）是浏览器自带的一种长连接：服务器持续往下推事件，浏览器用 `EventSource` 接收，断线会自动重连。AG-UI 是一个开源的"智能体与前端界面之间"的事件协议。

## 备选方案

1. 采用 AG-UI 协议。
2. 自己定义事件协议，经 SSE 推送。

## 结论

- 自定义事件协议，所有事件共用一个信封：`seq`（递增序号）、`run_id`、`type`、`agent_path`（事件属于哪个智能体，子智能体据此嵌套显示）、`ts`、`data`。
- 事件类型：`run.started`、`message.delta`、`thinking.delta`、`tool.started` / `tool.finished`、`subagent.started` / `subagent.finished`、`todos.updated`、`usage`、`run.finished`；`file.created`、`memory.saved`、`approval.required` 随 M2～M4 的功能加入。
- 事件定义（pydantic 数据模型）放在 `agents/main_agent/runtime/`，backend 原样转发、只加序号，前端类型由脚本自动生成；只有这个目录知道 deepagents，其他模块只认我们自己的事件。
- 发消息、审批、取消走普通接口；运行过程走 `GET /api/runs/{id}/events` 推送，断线重连带上最后收到的序号（`Last-Event-ID`），backend 先补发再接着推。空闲时每 15 秒发一次心跳，防止连接被中间环节掐断（FastAPI 自带的推送响应会自动发送）。
- 以后需要时再加一层 AG-UI 转换（扩展路线阶段 4）。

落地：M0：`agents/main_agent/runtime/events.py`（事件定义）、`agents/main_agent/runtime/translator.py`（把 deepagents 输出翻译成事件）、`backend/api/router.py`（推送接口）、`frontend/src/api/events.ts`（订阅）、`frontend/src/features/chat/reducer.ts`（事件处理器）；M1b 补齐思考、子智能体、待办、用量事件；M1c：前端类型自动生成（`backend/openapi.py`、`frontend/src/api/generated/`，`make types`）。

## 原因与代价

- 子智能体嵌套、待办、审批、产物都要定制界面，自己定义事件最直接；AG-UI 仍是 0.0.x 早期版本，接口不稳定。
- 推送只需要"服务器 → 浏览器"一个方向，SSE 由浏览器原生支持并自动重连；续传靠序号，不依赖连接粘在某个进程上（也为 D09 的多进程预留了条件）。
- 前端只有一套事件处理逻辑：实时显示是边收边处理，打开历史是把存好的事件重放（配合 D07）。
- 代价：协议、翻译器、前端事件处理器都要自己写、自己维护和测试；不能直接复用支持 AG-UI 的现成界面和工具，以后要接需另写转换层。
- 代价：推送是长连接，服务停止时 uvicorn 默认会一直等浏览器断开，必须配 `--timeout-graceful-shutdown` 才能及时收尾（见 `docs/development/architecture.md` 第 9 节）。
