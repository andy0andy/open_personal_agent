# M2b 文件上传与预览 实施计划

> **给执行者：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐个任务执行本计划。步骤用复选框（`- [ ]`）跟踪。开始任何任务前先读 `.claude/skills/dev-standards/SKILL.md`。

**目标：** M2 的后一半——用户能把文件交给智能体，并在页面里直接查看会话里的文件。

- 文件上传：点回形针或拖进对话区，选中即上传；文件随下一条消息作为附件交给智能体。
- 能看图的模型直接看到上传的图片；同一会话换到不能看图的模型时，历史里的图片换成一句说明。
- 右侧文件面板：列出本会话上传与生成的文件；预览图片、CSV / Excel 前若干行、PDF、Markdown、网页（不执行脚本）与代码；点产物卡片或附件标签直接打开。
- 收掉 M2a 审查延后、与本期相关的小问题：下载改为边读边传、文件类型不依赖系统、越界时返回 404、测试规范补上测试沙箱。
- 用户追加：回答下方的复制按钮挪到耗时与用量那一行的末尾，一直显示。

M2 拆成两份（2026-10-15 与用户确认）：M2a（沙箱与代码执行）已完成，**M2b 是本计划**。

**架构：**

- **上传**：`POST /api/threads/{id}/files`，请求体就是文件本身，文件名按 UTF-8 百分号编码放在 `X-File-Name` 请求头。
  - 这个自定义请求头同时满足设计文档 12.2 第 3 条：安全中间件对带它的非 JSON 请求放行，跨站网页要发它必须先预检。
  - 不需要表单解析依赖（`python-multipart`）。
  - 工作区接口新增 `save_upload`（边收边写，超限删除已写部分）。
- **附件**：发消息时带上已上传文件的 ID，运行记录的 `input`（原来就是 JSON `{"message"}`）里存一份 `attachments`，界面历史据此显示，不需要迁移。
  - 主智能体在消息末尾注明文件位置；能看图的模型同时收到图片本身（OpenAI 格式的 `image_url`，经 LiteLLM 网关转给各家）。
  - 换模型清理中间件对不能看图的模型把图片换成说明。
- **预览**：前端按类型选择预览方式。表格由后端新模块 `backend/files/` 读出前 100 行（Excel 用 `openpyxl`）；其余直接读文件内容（边读边传）：
  - 图片用 `<img>`；
  - PDF、网页放进内嵌框；
  - Markdown 用 `react-markdown` 渲染；
  - 文字原样显示。
- **M2a 遗留**：工作区接口新增 `open_file`（打开时检查、之后分块读取）；文件类型集中到 `media_type`（只用 Python 自带的表并补上常用格式）。

**技术栈：**

- 新增 Python 依赖 `openpyxl==3.1.5`（与沙箱里的版本相同），开发依赖 `types-openpyxl==3.1.5.20260827`（类型检查用）。
- 前端新增直接依赖 `react-markdown@10.1.0`。它原来就随 `@assistant-ui/react-markdown` 装着，改为直接依赖，锁文件只多 3 行。
- 用到的现有能力：
  - FastAPI `Request.stream()`、`StreamingResponse`；
  - langchain 消息的多段内容（`image_url`）；
  - TanStack Query；
  - React 19 的 `<Context value>`。

**设计文档：** `docs/specs/2026-10-10-personal-agent-design.md`（第 5 版）：

- 9.3 节（文件进出）；
- 11 节接口表"文件"一行（`POST /threads/{id}/files`、`GET /threads/{id}/files`、`…/content`）；
- 12.2 节第 3 条（上传要求自定义请求头）；
- 13.3 节（右侧可收起的侧栏，其中的"文件"页）；
- 表结构 `runs`"用户输入（消息 + 附件引用）"；
- 第 21 节 M2 行。

> 本计划的全部代码在写计划时已于临时目录实际运行验证（`make check`、集成测试全部通过，数量见各任务检查点）。
>
> 浏览器里已验证：
> - 文件面板与各类预览：GBK 编码的 CSV、两个工作表的 Excel、PDF、Markdown、图片、代码；
> - 拖放上传（一次两个文件）与附件标签；
> - 真实模型读出上传图片里的标题和数值、用代码数出 CSV 的行数；
> - 点产物卡片和附件标签在面板里打开。
>
> 网页预览要在普通浏览器里验证（见"先行探测结论"）。计划中的每段代码由脚本从验证过的文件直接嵌入，并已从改动前的项目出发按本计划逐任务重放、逐字核对。

## 全局约束

- 依赖方向 `backend → agents → config → common`；backend 只用 agents 各模块 `__init__.py` 公开的内容（import-linter 检查）。
- deepagents 只能出现在 `agents/main_agent/runtime/`；例外：`agents/main_agent/workspace/` 可以引用 `deepagents.backends`。
- 新增依赖只有三个，版本写死：
  - `openpyxl==3.1.5`；
  - 开发依赖 `types-openpyxl==3.1.5.20260827`；
  - 前端 `react-markdown@10.1.0`（`pnpm add -E`）。
- 第三方服务与镜像一律由 `deploy/docker-compose.yml` 管理；只操作本项目的容器。
- 密钥只在 `.env`，**执行者不读取、不打印 `.env` 的内容**。
- 只有 `frontend/src/components/chat/` 可以引用 `@assistant-ui/*`；组件只用语义样式类（两条自动检查）。
- 由命令生成的文件不手改：`frontend/src/api/generated/`（`make types`）、`uv.lock`（`uv lock`）、`frontend/package.json` 与 `pnpm-lock.yaml` 里的依赖（`pnpm add`）。
- 前端命令一律通过 `make` 执行，或先把 `~/.nvm/versions/node/v24.21.0/bin` 加到 `PATH` 前面。
- 直接运行 Python 测试时要有环境变量 `LITELLM_LOCAL_MODEL_COST_MAP=True`、`LANGGRAPH_STRICT_MSGPACK=true`（Makefile 与根目录 `conftest.py` 已设置）。集成测试先 `make test-up`（测试数据库与测试沙箱）。
- 注释与文档用中文，代码标识符用英文；注释只写"为什么"。
- **当前不是 git 仓库：不执行任何 git 命令**；每个任务以"检查点"结束。

## 重点关注

1. **一次拖进多个文件、同名文件、文件名里带路径或怪字符** → 每个都保存下来，不覆盖已有文件，不写到 `uploads/` 外面。测试：任务 2 `test_saves_uploads_with_safe_unique_names`、`test_concurrent_uploads_to_a_new_session`。
2. **超大文件**（超过 100MB；或请求头没声明长度、传到一半才超）→ 413"文件超过 100MB 上限"，不留下不完整的文件。测试：任务 2 `test_upload_over_the_limit_leaves_nothing`、`test_upload_over_the_limit_is_refused`；任务 8 浏览器验证第 6 步。
3. **各种来路的表格**：中文系统上 Excel 导出的 GBK CSV、带 BOM 的 UTF-8、行长短不一、Excel 多个工作表 / 日期 / 空单元格、损坏的文件、不是表格的文件 → 正常显示，或给出看得懂的说明。测试：任务 4 `backend/tests/test_preview.py` 全部、`test_table_preview_of_an_uploaded_csv`。
4. **图片交给模型的边界**：模型不能看图或模型信息缺失、图片超过 5MB、图片已被删、同一会话中途换到不能看图的模型 → 不报错，只注明文件位置，历史里的图片换成说明。测试：
   - 任务 3 `test_images_go_only_to_models_that_can_see`、`test_images_too_large_or_gone_are_only_listed`；
   - `test_images_are_replaced_for_models_that_cannot_see`、`test_uploaded_image_reaches_only_models_that_can_see`。
5. **智能体生成的网页里带脚本、同一文件被改写后再预览** → 面板里网页的脚本不执行；预览显示的是新内容（地址带更新时间）。没有自动化测试覆盖内嵌框（单元测试环境没有浏览器）：任务 8 浏览器验证第 3 步在普通浏览器里检查。

## 先行探测结论（2026-10-15 写计划时实测）

| 问题 | 结论 |
|---|---|
| 图片能否经 ChatLiteLLM → LiteLLM 网关送到模型 | 能：OpenAI 格式的 `{"type": "image_url", "image_url": {"url": "data:image/png;base64,…"}}`，claude-opus-4-6 与 gemini-3.5-flash 都正确读出了图里的标题和三个数值 |
| 哪些模型能看图 | 网关的模型信息里三个对话模型都标为 `supports_vision: true`，向量模型为否；本期"不能看图"的情况靠单元测试覆盖 |
| 带图片的消息估算用量会不会出错 | 不会（按低分辨率估，偏低；只用于被中断时的估算显示） |
| PDF 放进带 `Content-Security-Policy: sandbox` 的内嵌框 | 能正常显示（Chromium 内核的阅读器）；现有下载接口直接可用 |
| 网页放进隔离的内嵌框 | Claude 的内置浏览器会拦截所有隔离的内嵌网页（`ERR_BLOCKED_BY_CLIENT`，带不带 `sandbox` 属性、带不带文件名响应头都一样），这是它自己的安全策略；普通浏览器支持这一标准用法，在普通浏览器里验证 |
| Python 自带的文件类型表 | 3.12 没有 `.xlsx`、`.docx`、`.pptx`、`.md`、`.webp`；本机能认出来是因为读了系统的类型表，后端容器的精简镜像里没有。用 `mimetypes.MimeTypes()`（不读系统文件）再补上这几种，结果与环境无关 |
| 附件存在哪里 | `runs.input` 原来就是 JSON `{"message": …}`，设计文档的表结构也写着"消息 + 附件引用"：附件放进同一列，不需要迁移；旧记录没有这个字段，读取时补空列表 |
| 上传要不要表单格式 | 不要：请求体直接是文件，FastAPI 用 `request.stream()` 边收边写，省掉 `python-multipart` 依赖，文件名放在自定义请求头里 |
| 一次拖进多个文件 | 写计划时实测发现：新会话里几个上传同时建 `uploads/` 目录，"先判断再新建"会让晚到的报"已存在"（500）。改为直接新建、已存在则跳过（任务 2） |
| 待发送文件的标识 | 浏览器只在安全环境（https 或本机地址）提供 `crypto.randomUUID`，局域网的 http 页面里没有：改用计数器 |
| `react-markdown` | 10.1.0 已随 assistant-ui 装着；v10 去掉了 `className` 属性，外面包一层 `div.markdown` 沿用回答的排版样式 |
| 智能体读 GBK 编码的 CSV | deepagents 的 `read_file` 只按 UTF-8 读，会报错；模型随后改用执行代码读取（实测会自己恢复），不在本期处理 |

## 文件结构（本计划涉及）

```
agents/main_agent/
├── workspace/media.py             # 新：按文件名判断类型（与环境无关）
├── workspace/base.py、local.py     # 改：open_file（边读边传）、save_upload（上传）、建目录不怕并发
├── runtime/attachments.py         # 新：附件交给模型（注明位置；能看图时附上图片）
├── runtime/agent.py               # 改：run 带附件；按模型能否看图组装
├── models/cleanup.py              # 改：不能看图的模型，历史图片换成说明
└── prompts/system.md              # 改：说明 uploads/
backend/
├── files/preview.py               # 新：CSV / Excel 表格预览
├── api/router.py                  # 改：上传、文件列表、表格预览；下载边读边传
├── runs/                          # 改：运行带附件（schemas、repo、manager）
├── security.py                    # 改：带 X-File-Name 的上传放行
└── api/errors.py、common/errors.py # 改：TooLargeError → 413
config/settings.py、config/app.yaml  # 改：workspace.max_upload_mb
pyproject.toml、uv.lock             # 改：openpyxl
frontend/
├── package.json、pnpm-lock.yaml    # 改：react-markdown
└── src/
    ├── api/                       # 改：上传、文件列表、表格预览、文件原文；类型别名
    ├── features/files/            # 新：文件面板、预览、按类型选择预览方式
    ├── features/chat/             # 改：待发送的文件、用户消息的附件、面板开关
    └── components/chat/           # 改：附件按钮与标签、拖放、点卡片打开面板
docs/                              # 改：测试规范、架构规范、README、需求池、变更记录
```

---

### 任务 1：下载与文件类型（M2a 审查延后的小问题）

**文件：**
- 新建：`agents/main_agent/workspace/media.py`、`agents/tests/test_media_types.py`
- 修改：`agents/main_agent/workspace/base.py`、`local.py`、`__init__.py`、`agents/main_agent/runtime/agent.py`、`backend/api/router.py`、`agents/tests/contracts/test_workspace_contract.py`、`backend/tests/test_api.py`、`docs/development/testing.md`、`frontend/src/api/generated/*`（命令生成）

**接口：**
- 产出（`agents.main_agent.workspace` 公开）：
  - `media_type(path: str) -> str`：不认识的类型为 `application/octet-stream`；
  - `OpenedFile(size: int, chunks: AsyncIterator[bytes])`；
  - `Workspace.open_file(short_id, path) -> OpenedFile`：检查在打开时完成；
  - `read_file` / `open_file` 的报错统一：越界（含指向会话目录外的链接）抛 `PermissionError`；不存在或不是普通文件（如目录）抛 `FileNotFoundError`。
- 产出（接口）：`GET …/files/{file_id}/content` 改为边读边传（带 `Content-Length`）；文件被删除、换成目录或越界链接时一律 404"文件已不存在"。

- [ ] **步骤 1：写失败的测试**

新建 `agents/tests/test_media_types.py`：

```python
from agents.main_agent.workspace import media_type


def test_types_do_not_depend_on_the_host() -> None:
    """后端容器的精简镜像没有系统的文件类型表，Python 自带的表又缺 Office、Markdown 等常用格式：
    只用自带的表再补上这些，结果在本机与容器里一致。"""
    office = "application/vnd.openxmlformats-officedocument"
    assert media_type("outputs/report.xlsx") == f"{office}.spreadsheetml.sheet"
    assert media_type("uploads/方案.docx") == f"{office}.wordprocessingml.document"
    assert media_type("a.pptx") == f"{office}.presentationml.presentation"
    assert media_type("uploads/说明.MD") == "text/markdown"
    assert media_type("photo.webp") == "image/webp"
    assert media_type("data.csv") == "text/csv"
    assert media_type("chart.png") == "image/png"
    assert media_type("Makefile") == "application/octet-stream"
```

工作区契约：分块读取；打开时就报错：

在 `agents/tests/contracts/test_workspace_contract.py` 末尾追加：

```python


async def test_opens_a_file_in_chunks_for_streaming(tmp_path: Path, make: Factory) -> None:
    """下载时分块读取，不把整个文件读进内存。"""
    workspace = make(tmp_path, FakeSandbox())
    outputs = tmp_path / "workspace" / ME / "outputs"
    outputs.mkdir(parents=True)
    data = bytes(range(256)) * 1024
    (outputs / "big.bin").write_bytes(data)
    opened = await workspace.open_file(ME, "outputs/big.bin")
    chunks = [chunk async for chunk in opened.chunks]
    assert opened.size == len(data)
    assert b"".join(chunks) == data
    assert len(chunks) > 1


async def test_unusable_paths_fail_when_opening(tmp_path: Path, make: Factory) -> None:
    """打开时就报错（下载接口据此返回 404，而不是响应开始以后才失败）：
    不存在或是目录 → FileNotFoundError；越界（含指向会话目录外的链接）→ PermissionError。"""
    workspace = make(tmp_path, FakeSandbox())
    _seed_other_session(tmp_path)
    outputs = tmp_path / "workspace" / ME / "outputs"
    (outputs / "folder").mkdir(parents=True)
    (outputs / "link.txt").symlink_to(tmp_path / "workspace" / OTHER / "secret.txt")
    for path in ("outputs/missing.txt", "outputs/folder"):
        with pytest.raises(FileNotFoundError):
            await workspace.open_file(ME, path)
        with pytest.raises(FileNotFoundError):
            await workspace.read_file(ME, path)
    for path in ("outputs/link.txt", f"../{OTHER}/secret.txt"):
        with pytest.raises(PermissionError):
            await workspace.open_file(ME, path)
        with pytest.raises(PermissionError):
            await workspace.read_file(ME, path)
```

下载接口：带 `Content-Length`；文件被换成目录或越界链接时同样是"已不存在"：

在 `backend/tests/test_api.py` 中，把：

```python

        (tmp_path / "workspace" / thread["short_id"] / "outputs" / "销售图.png").unlink()
        gone = await client.get(url)
        assert gone.status_code == 404
        assert gone.json()["detail"] == "文件已不存在"
```

改为：

```python

        assert shown.headers["content-length"] == "4"

        chart = tmp_path / "workspace" / thread["short_id"] / "outputs" / "销售图.png"
        chart.unlink()
        gone = await client.get(url)
        assert gone.status_code == 404
        assert gone.json()["detail"] == "文件已不存在"
        # 被换成目录、或换成指向会话目录外的链接：同样是"已不存在"，不是服务器错误
        chart.mkdir()
        assert (await client.get(url)).json()["detail"] == "文件已不存在"
        chart.rmdir()
        chart.symlink_to(tmp_path / "elsewhere.png")
        assert (await client.get(url)).json()["detail"] == "文件已不存在"
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_media_types.py -q`（预期失败）

预期：收集阶段报错 `ImportError: cannot import name 'media_type'`。

运行：`uv run pytest agents/tests/contracts/test_workspace_contract.py -q`（预期失败）

预期：两个新测试失败，`AttributeError: 'LocalWorkspace' object has no attribute 'open_file'`。

运行：`make test-up`

运行：`uv run pytest -m integration backend/tests/test_api.py -q -k download`（预期失败）

预期：`IsADirectoryError`（文件被换成目录时服务器出错）。

- [ ] **步骤 3：实现**

新建 `agents/main_agent/workspace/media.py`：

```python
"""按文件名判断文件类型（产物登记、上传、预览都用它）。

不读系统的类型表：后端容器的精简镜像里没有，本机的又各不相同。只用 Python 自带的表，
再补上它缺的常用格式，结果在本机与容器里一致。
"""

import mimetypes

_OFFICE = "application/vnd.openxmlformats-officedocument"
_TYPES = mimetypes.MimeTypes()  # 不传文件名：只有 Python 自带的表
for _suffix, _type in {
    ".xlsx": f"{_OFFICE}.spreadsheetml.sheet",
    ".docx": f"{_OFFICE}.wordprocessingml.document",
    ".pptx": f"{_OFFICE}.presentationml.presentation",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".webp": "image/webp",
}.items():
    _TYPES.add_type(_type, _suffix)


def media_type(path: str) -> str:
    return _TYPES.guess_type(path.lower())[0] or "application/octet-stream"
```

在 `agents/main_agent/workspace/base.py` 中，把：

```python

from dataclasses import dataclass
```

改为：

```python

from collections.abc import AsyncIterator
from dataclasses import dataclass
```

在 `agents/main_agent/workspace/base.py` 中，把：

```python

class Workspace(Protocol):
```

改为：

```python

@dataclass(frozen=True)
class OpenedFile:
    """已打开、可分块读取的文件（下载时边读边传）。"""

    size: int
    chunks: AsyncIterator[bytes]


class Workspace(Protocol):
```

在 `agents/main_agent/workspace/base.py` 中，把：

```python

        越界抛 PermissionError，不存在抛 FileNotFoundError。
        """
        ...
```

改为：

```python

        越界（含指向会话目录外的链接）抛 PermissionError；不存在或不是普通文件抛 FileNotFoundError。
        """
        ...

    async def open_file(self, short_id: str, path: str) -> OpenedFile:
        """打开会话目录里的文件供分块读取；检查与报错同 read_file，在打开时就完成。"""
        ...
```

在 `agents/main_agent/workspace/local.py` 中，把：

```python
import asyncio
import re
import shutil
from collections.abc import Callable
from pathlib import Path

```

改为：

```python
import asyncio
import os
import re
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import BinaryIO

```

在 `agents/main_agent/workspace/local.py` 中，把：

```python
from agents.main_agent.context import AgentContext
from agents.main_agent.workspace.base import OutputFile, Sandbox

_SHORT_ID = re.compile(r"c_[0-9a-f]{8}")

```

改为：

```python
from agents.main_agent.context import AgentContext
from agents.main_agent.workspace.base import OpenedFile, OutputFile, Sandbox

_SHORT_ID = re.compile(r"c_[0-9a-f]{8}")
_CHUNK = 64 * 1024

```

在 `agents/main_agent/workspace/local.py` 中，把：

```python
    async def read_file(self, short_id: str, path: str) -> bytes:
        session = self._session_dir(short_id).resolve()
        target = (session / path).resolve()
        if session not in target.parents:
            raise PermissionError(f"只能读取会话目录里的文件：{path}")
        return await asyncio.to_thread(target.read_bytes)

```

改为：

```python
    async def read_file(self, short_id: str, path: str) -> bytes:
        target = await asyncio.to_thread(self._existing_file, short_id, path)
        return await asyncio.to_thread(target.read_bytes)

    async def open_file(self, short_id: str, path: str) -> OpenedFile:
        target = await asyncio.to_thread(self._existing_file, short_id, path)
        handle = await asyncio.to_thread(target.open, "rb")
        return OpenedFile(size=os.fstat(handle.fileno()).st_size, chunks=_read_chunks(handle))

    def _existing_file(self, short_id: str, path: str) -> Path:
        session = self._session_dir(short_id).resolve()
        target = (session / path).resolve()  # 解析链接后再比对：指向会话目录外的链接也算越界
        if session not in target.parents:
            raise PermissionError(f"只能读取会话目录里的文件：{path}")
        if not target.is_file():
            raise FileNotFoundError(f"文件不存在：{path}")
        return target

```

在 `agents/main_agent/workspace/local.py` 末尾追加：

```python


async def _read_chunks(handle: BinaryIO) -> AsyncIterator[bytes]:
    try:
        while chunk := await asyncio.to_thread(handle.read, _CHUNK):
            yield chunk
    finally:
        handle.close()
```

在 `agents/main_agent/workspace/__init__.py` 中，把：

```python
    CommandResult,
    OutputFile,
```

改为：

```python
    CommandResult,
    OpenedFile,
    OutputFile,
```

在 `agents/main_agent/workspace/__init__.py` 中，把：

```python
from agents.main_agent.workspace.local import LocalWorkspace
from agents.main_agent.workspace.sandbox_http import HttpSandbox
```

改为：

```python
from agents.main_agent.workspace.local import LocalWorkspace
from agents.main_agent.workspace.media import media_type
from agents.main_agent.workspace.sandbox_http import HttpSandbox
```

在 `agents/main_agent/workspace/__init__.py` 中，把：

```python
    "LocalWorkspace",
    "OutputFile",
```

改为：

```python
    "LocalWorkspace",
    "OpenedFile",
    "OutputFile",
```

在 `agents/main_agent/workspace/__init__.py` 中，把：

```python
    "WorkspaceFileRepo",
    "workspace_file_id",
```

改为：

```python
    "WorkspaceFileRepo",
    "media_type",
    "workspace_file_id",
```

产物登记改用 `media_type`：

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
import logging
import mimetypes
from collections.abc import AsyncIterator
```

改为：

```python
import logging
from collections.abc import AsyncIterator
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
from agents.main_agent.runtime.translator import Translator
from agents.main_agent.workspace import Workspace

```

改为：

```python
from agents.main_agent.runtime.translator import Translator
from agents.main_agent.workspace import Workspace, media_type

```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
                size=current[path][0],
                media_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
            )
```

改为：

```python
                size=current[path][0],
                media_type=media_type(path),
            )
```

在 `backend/api/router.py` 中，把：

```python
from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
```

改为：

```python
from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import StreamingResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
```

在 `backend/api/router.py` 中，把：

```python
) -> Response:
    """读取会话里的一个文件：默认在页面里直接显示，download=1 时作为附件下载。"""
    thread = await services.threads.get(thread_id)
```

改为：

```python
) -> Response:
    """读取会话里的一个文件：默认在页面里直接显示，download=1 时作为附件下载。边读边传。"""
    thread = await services.threads.get(thread_id)
```

在 `backend/api/router.py` 中，把：

```python
    try:
        content = await services.agent.workspace.read_file(thread.short_id, record.path)
    except FileNotFoundError:
        raise NotFoundError("文件已不存在") from None
    name = quote(PurePosixPath(record.path).name)
    disposition = "attachment" if download else "inline"
    return Response(
        content,
        media_type=record.media_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{name}",
```

改为：

```python
    try:
        opened = await services.agent.workspace.open_file(thread.short_id, record.path)
    except (FileNotFoundError, PermissionError):
        # 登记之后被删掉、换成目录或换成指向会话目录外的链接
        raise NotFoundError("文件已不存在") from None
    name = quote(PurePosixPath(record.path).name)
    disposition = "attachment" if download else "inline"
    return StreamingResponse(
        opened.chunks,
        media_type=record.media_type,
        headers={
            "Content-Length": str(opened.size),
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{name}",
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest agents/tests/test_media_types.py agents/tests/contracts/test_workspace_contract.py agents/tests/test_main_agent.py -q`

运行：`uv run pytest -m integration backend/tests/test_api.py -q`

预期：全部通过。

- [ ] **步骤 5：测试规范**

在 `docs/development/testing.md` 中，把：

```markdown
| 单元测试（含契约测试、离线先行验证） | 无 | `make test`（`make check` 也会跑） | 什么都不需要 |
| 集成测试 | `@pytest.mark.integration` | `make test-int` | 自动启动 compose `test` 配置组的 `postgres-test`（端口 55432） |
| 真实模型冒烟测试 | `@pytest.mark.live` | `make smoke` | `make infra-up` + `.env` 中的模型密钥；会产生少量费用 |
```

改为：

```markdown
| 单元测试（含契约测试、离线先行验证） | 无 | `make test`（`make check` 也会跑） | 什么都不需要 |
| 集成测试 | `@pytest.mark.integration` | `make test-int` | 自动启动 compose `test` 配置组的 `postgres-test`（端口 55432）与 `sandbox-test`（测试沙箱，端口 58080，工作目录 `workdata/sandbox-test/workspace/`）；用完可 `make test-down` 关掉 |
| 真实模型冒烟测试 | `@pytest.mark.live` | `make smoke` | `make infra-up` + `.env` 中的模型密钥；会产生少量费用 |
```

在 `docs/development/testing.md` 中，把：

```markdown
- **契约测试**：每个可替换接口有一套测试，用参数化列出全部实现；新实现必须加进列表并跑通。agents 的接口在 `agents/tests/contracts/`；backend 的运行时替换点在 `backend/tests/`（如 `test_run_control.py`）。
- **数据库测试**：使用根目录 `conftest.py` 的 `db` 夹具（每个测试前清空业务表）；不要连接开发库。
```

改为：

```markdown
- **契约测试**：每个可替换接口有一套测试，用参数化列出全部实现；新实现必须加进列表并跑通。agents 的接口在 `agents/tests/contracts/`；backend 的运行时替换点在 `backend/tests/`（如 `test_run_control.py`）。
- **沙箱测试**：连接真实测试沙箱的测试放在 `agents/tests/test_sandbox_http.py`，每个测试用新的会话 ID，结束后删掉它建的会话目录；停止、超时、进程回收这类行为只有在真实容器里才测得出来（宿主机上的孤儿进程由系统回收）。
- **数据库测试**：使用根目录 `conftest.py` 的 `db` 夹具（每个测试前清空业务表）；不要连接开发库。
```

- [ ] **步骤 6：检查点**

下载接口的说明改了，重新生成前端类型：

运行：`make types`

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 153 个、前端 71 个）；`make test-int` 全部通过（集成测试 64 个）。

---

### 任务 2：上传接口与文件列表

**文件：**
- 修改：`common/errors.py`、`backend/api/errors.py`、`backend/security.py`、`config/settings.py`、`config/app.yaml`、`agents/main_agent/workspace/base.py`、`local.py`、`backend/api/router.py`、`agents/tests/contracts/test_workspace_contract.py`、`backend/tests/test_security.py`、`backend/tests/conftest.py`、`backend/tests/test_api.py`、`frontend/src/api/generated/*`（命令生成）

**接口：**
- 消费：任务 1 的 `media_type`。
- 产出：
  - `common.errors.TooLargeError`（接口层映射为 413）；
  - `WorkspaceConfig.max_upload_mb: int = 100`；
  - `Workspace.save_upload(short_id, name, chunks: AsyncIterator[bytes], *, max_bytes) -> OutputFile`：存到 `uploads/`，返回实际位置（如 `uploads/销售 (2).xlsx`）与大小；超限抛 `TooLargeError` 并删掉已写部分。
- 产出（接口）：
  - `POST /api/threads/{thread_id}/files`：请求体为文件，请求头 `X-File-Name`（百分号编码），返回 201 与 `WorkspaceFile`（`source` 为 `upload`）；超限 413"文件超过 N MB 上限"；会话不存在 404。
  - `GET /api/threads/{thread_id}/files`：`list[WorkspaceFile]`，按路径排序。
- 产出（安全）：带 `X-File-Name` 请求头的非 JSON POST 不再被 415 拒绝。
- 产出（测试夹具）：`make_client(..., upload_limit_mb=100)`。

- [ ] **步骤 1：写失败的测试**

在 `backend/tests/test_security.py` 中，把：

```python
    assert rejection(SecurityPolicy(), scope) == (415, "只接受 JSON 请求")

```

改为：

```python
    assert rejection(SecurityPolicy(), scope) == (415, "只接受 JSON 请求")


def test_upload_with_file_name_header_is_accepted() -> None:
    """上传的请求体就是文件内容（不是 JSON）；带了自定义请求头 X-File-Name，
    跨站网页要发它必须先预检，浏览器会拦下（设计文档 12.2 第 3 条）。"""
    for headers in ({"content-type": "image/png", "x-file-name": "a.png"}, {"x-file-name": "a"}):
        assert rejection(SecurityPolicy(), _scope(method="POST", headers=headers)) is None

```

工作区契约：保存上传（安全的文件名、同名加序号）、超限不留残片、新会话里同时上传：

在 `agents/tests/contracts/test_workspace_contract.py` 中，把：

```python

from collections.abc import Callable
from pathlib import Path
```

改为：

```python

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
```

在 `agents/tests/contracts/test_workspace_contract.py` 中，把：

```python
from agents.tests.fakes import FakeSandbox

```

改为：

```python
from agents.tests.fakes import FakeSandbox
from common.errors import TooLargeError

```

在 `agents/tests/contracts/test_workspace_contract.py` 末尾追加：

```python


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def test_saves_uploads_with_safe_unique_names(tmp_path: Path, make: Factory) -> None:
    """上传存到 uploads/：只取文件名本身（去掉目录部分与开头的点），同名时加序号、不覆盖。"""
    workspace = make(tmp_path, FakeSandbox())
    saved = [
        await workspace.save_upload(ME, name, _chunks(*parts), max_bytes=10)
        for name, parts in (
            ("销售.xlsx", (b"ab", b"c")),
            ("销售.xlsx", (b"x",)),
            ("../../etc/passwd", (b"x",)),
            ("C:\\Users\\me\\.env", (b"x",)),
            ("  ", (b"",)),
        )
    ]
    assert [(f.path, f.size) for f in saved] == [
        ("uploads/销售.xlsx", 3),
        ("uploads/销售 (2).xlsx", 1),
        ("uploads/passwd", 1),
        ("uploads/env", 1),
        ("uploads/未命名文件", 0),
    ]
    assert await workspace.read_file(ME, "uploads/销售.xlsx") == b"abc"
    listing = workspace.agent_backend.ls(f"/workspace/{ME}/uploads/")
    assert len(listing.entries or []) == 5  # 智能体在自己的目录里能看到


async def test_upload_over_the_limit_leaves_nothing(tmp_path: Path, make: Factory) -> None:
    workspace = make(tmp_path, FakeSandbox())
    with pytest.raises(TooLargeError):
        await workspace.save_upload(ME, "big.bin", _chunks(b"12345", b"67890"), max_bytes=8)
    assert list((tmp_path / "workspace" / ME / "uploads").iterdir()) == []


async def test_concurrent_uploads_to_a_new_session(tmp_path: Path, make: Factory) -> None:
    """新会话里一次拖进多个文件：几个上传同时建目录，都要能保存。"""
    workspace = make(tmp_path, FakeSandbox())
    saved = await asyncio.gather(
        *(workspace.save_upload(ME, f"{i}.txt", _chunks(b"x"), max_bytes=10) for i in range(8))
    )
    assert sorted(f.path for f in saved) == sorted(f"uploads/{i}.txt" for i in range(8))
```

在 `backend/tests/conftest.py` 中，把：

```python
from config import Settings
from config.settings import AgentConfig

```

改为：

```python
from config import Settings
from config.settings import AgentConfig, WorkspaceConfig

```

在 `backend/tests/conftest.py` 中，把：

```python
        workspace: LocalWorkspace | None = None,
    ) -> AsyncIterator[AsyncClient]:
```

改为：

```python
        workspace: LocalWorkspace | None = None,
        upload_limit_mb: int = 100,
    ) -> AsyncIterator[AsyncClient]:
```

在 `backend/tests/conftest.py` 中，把：

```python
            agent=AgentConfig(default_model="fake-model"),
        )
```

改为：

```python
            agent=AgentConfig(default_model="fake-model"),
            workspace=WorkspaceConfig(max_upload_mb=upload_limit_mb),
        )
```

在 `backend/tests/test_api.py` 中，把：

```python
from typing import Any

```

改为：

```python
from typing import Any
from urllib.parse import quote

```

在 `backend/tests/test_api.py` 末尾追加：

```python


async def test_upload_list_and_download(make_client: ClientFactory, tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path, FakeSandbox())
    async with make_client(ScriptedChatModel(responses=[]), workspace=workspace) as client:
        thread = (await client.post("/api/threads", json={})).json()
        files = f"/api/threads/{thread['id']}/files"
        headers = {"X-File-Name": quote("销售 数据.csv"), "Content-Type": "text/csv"}
        response = await client.post(files, content=b"a,b\n1,2\n", headers=headers)
        assert response.status_code == 201
        uploaded = response.json()
        assert (uploaded["path"], uploaded["source"], uploaded["size"]) == (
            "uploads/销售 数据.csv",
            "upload",
            8,
        )
        assert uploaded["media_type"] == "text/csv"
        assert [item["id"] for item in (await client.get(files)).json()] == [uploaded["id"]]
        content = await client.get(f"{files}/{uploaded['id']}/content")
        assert content.content == b"a,b\n1,2\n"

        unknown = f"/api/threads/{uuid.uuid4()}/files"
        assert (await client.get(unknown)).status_code == 404
        assert (await client.post(unknown, content=b"x", headers=headers)).status_code == 404


async def test_upload_over_the_limit_is_refused(make_client: ClientFactory, tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path, FakeSandbox())
    model = ScriptedChatModel(responses=[])
    async with make_client(model, workspace=workspace, upload_limit_mb=1) as client:
        thread = (await client.post("/api/threads", json={})).json()
        files = f"/api/threads/{thread['id']}/files"
        response = await client.post(
            files, content=b"x" * (1024 * 1024 + 1), headers={"X-File-Name": "big.bin"}
        )
        assert response.status_code == 413
        assert response.json()["detail"] == "文件超过 1MB 上限"
        assert (await client.get(files)).json() == []
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest backend/tests/test_security.py agents/tests/contracts/test_workspace_contract.py -q`（预期失败）

预期：收集阶段报错 `ImportError: cannot import name 'TooLargeError' from 'common.errors'`。

运行：`uv run pytest -m integration backend/tests/test_api.py -q -k upload`（预期失败）

预期：两个上传测试失败，`assert 415 == 201`、`assert 415 == 413`（上传被"只接受 JSON 请求"拦下）。

- [ ] **步骤 3：实现**

在 `common/errors.py` 末尾追加：

```python


class TooLargeError(AppError):
    """内容超过允许的大小，例如上传的文件超过上限。"""
```

在 `backend/api/errors.py` 中，把：

```python

from common.errors import AppError, ConflictError, NotFoundError, UpstreamError

_STATUS: dict[type[AppError], int] = {NotFoundError: 404, ConflictError: 409, UpstreamError: 503}

```

改为：

```python

from common.errors import AppError, ConflictError, NotFoundError, TooLargeError, UpstreamError

_STATUS: dict[type[AppError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    TooLargeError: 413,
    UpstreamError: 503,
}

```

在 `backend/security.py` 中，把：

```python
3. POST 必须是 JSON：迫使跨站请求先发预检请求而被浏览器拦下（PUT / PATCH / DELETE 本来就要预检）；
4. 配置了访问令牌（.env 的 ACCESS_TOKEN）时，/api 下的请求需要令牌：
```

改为：

```python
3. POST 必须是 JSON：迫使跨站请求先发预检请求而被浏览器拦下（PUT / PATCH / DELETE 本来就要预检）；
   上传的请求体是文件本身，改为要求自定义请求头 X-File-Name，同样迫使跨站请求先预检；
4. 配置了访问令牌（.env 的 ACCESS_TOKEN）时，/api 下的请求需要令牌：
```

在 `backend/security.py` 中，把：

```python
            return status.HTTP_403_FORBIDDEN, "不允许的来源"
        if method == "POST" and not headers.get("content-type", "").startswith("application/json"):
            return status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "只接受 JSON 请求"
```

改为：

```python
            return status.HTTP_403_FORBIDDEN, "不允许的来源"
        is_json = headers.get("content-type", "").startswith("application/json")
        if method == "POST" and not is_json and "x-file-name" not in headers:
            return status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "只接受 JSON 请求"
```

在 `config/settings.py` 中，把：

```python
    command_timeout: int = 120  # 命令默认时限（秒）；超时由沙箱杀掉整个进程组

```

改为：

```python
    command_timeout: int = 120  # 命令默认时限（秒）；超时由沙箱杀掉整个进程组
    max_upload_mb: int = 100  # 单个上传文件的上限

```

在 `config/app.yaml` 中，把：

```yaml
  command_timeout: 120 # 命令默认时限（秒），超时杀掉整个进程组

```

改为：

```yaml
  command_timeout: 120 # 命令默认时限（秒），超时杀掉整个进程组
  max_upload_mb: 100 # 单个上传文件的上限（MB）

```

在 `agents/main_agent/workspace/base.py` 中，把：

```python

    async def remove(self, short_id: str) -> None:
```

改为：

```python

    async def save_upload(
        self, short_id: str, name: str, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> OutputFile:
        """把上传的文件存到会话的 uploads/，返回实际保存的位置（相对会话目录）与大小。

        只取文件名本身（去掉目录部分与开头的点）；已有同名文件时加序号，不覆盖。
        超过 max_bytes 抛 common.errors.TooLargeError，不留下不完整的文件。
        """
        ...

    async def remove(self, short_id: str) -> None:
```

建目录改为"直接新建、已存在则跳过"（同时到来的几个上传不会互相撞上），运行开始时建目录也用它：

在 `agents/main_agent/workspace/local.py` 中，把：

```python
import asyncio
import os
```

改为：

```python
import asyncio
import itertools
import os
```

在 `agents/main_agent/workspace/local.py` 中，把：

```python
from agents.main_agent.workspace.base import OpenedFile, OutputFile, Sandbox

_SHORT_ID = re.compile(r"c_[0-9a-f]{8}")
_CHUNK = 64 * 1024

```

改为：

```python
from agents.main_agent.workspace.base import OpenedFile, OutputFile, Sandbox
from common.errors import TooLargeError

_SHORT_ID = re.compile(r"c_[0-9a-f]{8}")
_CHUNK = 64 * 1024
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f]")

```

在 `agents/main_agent/workspace/local.py` 中，把：

```python
    def _prepare(self, short_id: str) -> None:
        # 原来要等沙箱第一次执行命令才建，模型先查看自己的目录会得到"路径不存在"。
        # 新建的目录放开权限：backend 在容器里是 root、沙箱是 uid 1000，在区分 uid 的文件系统上
        # 沙箱也要能在里面写文件（mkdir 的权限受 umask 影响，所以单独设置）
        session = self._session_dir(short_id)
        for directory in (session, session / "outputs"):
            try:
                directory.mkdir(parents=True)
            except FileExistsError:
                continue
            directory.chmod(0o777)

```

改为：

```python
    def _prepare(self, short_id: str) -> None:
        # 原来要等沙箱第一次执行命令才建，模型先查看自己的目录会得到"路径不存在"
        session = self._session_dir(short_id)
        _make_shared_dirs(session, session / "outputs")

```

在 `agents/main_agent/workspace/local.py` 中，把：

```python
        return target

```

改为：

```python
        return target

    async def save_upload(
        self, short_id: str, name: str, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> OutputFile:
        session = self._session_dir(short_id)
        await asyncio.to_thread(_make_shared_dirs, session, session / "uploads")
        target, handle = await asyncio.to_thread(_reserve, session / "uploads", _safe_name(name))
        size = 0
        try:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise TooLargeError(f"文件超过 {max_bytes // (1024 * 1024)}MB 上限")
                await asyncio.to_thread(handle.write, chunk)
        except BaseException:  # 超限、请求中断（取消）都不留下不完整的文件
            handle.close()
            await asyncio.to_thread(target.unlink, missing_ok=True)
            raise
        handle.close()
        stat = await asyncio.to_thread(target.stat)
        return OutputFile(f"uploads/{target.name}", size, stat.st_mtime)

```

在 `agents/main_agent/workspace/local.py` 末尾追加：

```python


def _safe_name(name: str) -> str:
    """只留文件名本身：去掉目录部分（/ 与 \\ 都算）、控制字符和开头的点（不生成隐藏文件）。"""
    base = _UNSAFE_NAME.sub("", name.replace("\\", "/").rsplit("/", 1)[-1]).strip().lstrip(".")
    return base or "未命名文件"


def _make_shared_dirs(*directories: Path) -> None:
    """依次建好目录，已存在的跳过（不先判断是否存在：同时上传的几个文件会同时来建）。

    新建的目录放开权限：backend 在容器里是 root、沙箱是 uid 1000，在区分 uid 的文件系统上
    沙箱也要能在里面写文件（mkdir 的权限受 umask 影响，所以单独设置）。
    """
    for directory in directories:
        try:
            directory.mkdir(parents=True)
        except FileExistsError:
            continue
        directory.chmod(0o777)


def _reserve(directory: Path, name: str) -> tuple[Path, BinaryIO]:
    """以独占方式新建文件（同名已存在时加序号），返回位置与打开的文件。"""
    stem, suffix = Path(name).stem, Path(name).suffix
    for number in itertools.count(1):
        candidate = directory / (name if number == 1 else f"{stem} ({number}){suffix}")
        try:
            return candidate, candidate.open("xb")
        except FileExistsError:
            continue
    raise AssertionError("unreachable")
```

在 `backend/api/router.py` 中，把：

```python
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import StreamingResponse
```

改为：

```python
from typing import Annotated
from urllib.parse import quote, unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
```

在 `backend/api/router.py` 中，把：

```python
from agents.main_agent.usage import ThreadUsage, UsageRecord
from backend.api.deps import ServicesDep
from backend.runs import RunCreate, RunHistory, RunRecord
from backend.threads import Thread, ThreadCreate, ThreadOrder, ThreadUpdate
from common.errors import NotFoundError

```

改为：

```python
from agents.main_agent.usage import ThreadUsage, UsageRecord
from agents.main_agent.workspace import WorkspaceFile, media_type
from backend.api.deps import ServicesDep
from backend.runs import RunCreate, RunHistory, RunRecord
from backend.threads import Thread, ThreadCreate, ThreadOrder, ThreadUpdate
from common.errors import NotFoundError, TooLargeError

```

在 `backend/api/router.py` 中，把：

```python
    return await services.usage.for_thread(thread_id)

```

改为：

```python
    return await services.usage.for_thread(thread_id)


@api_router.get("/threads/{thread_id}/files")
async def list_files(thread_id: UUID, services: ServicesDep) -> list[WorkspaceFile]:
    """会话里登记过的文件：上传与产物，按路径排序。"""
    await services.threads.get(thread_id)
    return await services.files.for_thread(thread_id)


@api_router.post(
    "/threads/{thread_id}/files",
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"requestBody": {"content": {"application/octet-stream": {}}, "required": True}},
)
async def upload_file(
    thread_id: UUID,
    request: Request,
    services: ServicesDep,
    x_file_name: Annotated[str, Header(description="文件名，按 UTF-8 百分号编码")],
) -> WorkspaceFile:
    """上传文件到会话的 uploads/：请求体就是文件内容，文件名放在 X-File-Name 请求头。"""
    thread = await services.threads.get(thread_id)
    limit_mb = services.settings.workspace.max_upload_mb
    declared = request.headers.get("content-length")
    if declared is not None and int(declared) > limit_mb * 1024 * 1024:
        raise TooLargeError(f"文件超过 {limit_mb}MB 上限")  # 不必等传完再拒绝
    saved = await services.agent.workspace.save_upload(
        thread.short_id, unquote(x_file_name), request.stream(), max_bytes=limit_mb * 1024 * 1024
    )
    return await services.files.record(
        thread.id, saved.path, source="upload", size=saved.size, media_type=media_type(saved.path)
    )

```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest backend/tests/test_security.py agents/tests/contracts/test_workspace_contract.py -q`

运行：`uv run pytest -m integration backend/tests/test_api.py -q`

预期：全部通过（单元 49 个；接口 20 个）。

- [ ] **步骤 5：检查点**

新增了接口，重新生成前端类型：

运行：`make types`

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 157 个、前端 71 个）；`make test-int` 全部通过（集成测试 66 个）。

---

### 任务 3：附件随消息交给智能体

**文件：**
- 新建：`agents/main_agent/runtime/attachments.py`、`agents/tests/test_attachments.py`
- 修改：`agents/main_agent/runtime/__init__.py`、`agents/main_agent/runtime/agent.py`、`agents/main_agent/models/cleanup.py`、`agents/prompts/system.md`、`backend/runs/schemas.py`、`backend/runs/__init__.py`、`backend/runs/repo.py`、`backend/runs/manager.py`、`agents/tests/fakes.py`、`agents/tests/test_main_agent.py`、`agents/tests/test_model_cleanup.py`、`agents/tests/test_subagents.py`、`backend/tests/test_manager.py`、`frontend/src/features/chat/reducer.test.ts`、`frontend/src/api/generated/*`（命令生成）

**接口：**
- 消费：任务 2 登记的上传文件（`WorkspaceFileRepo.get`）、`Workspace.read_file`。
- 产出（agents）：
  - `Attachment(path: str, media_type: str, size: int)`（不可变数据类，`path` 相对会话目录）；
  - `user_content(message, attachments, *, short_id, workspace, vision) -> str | list[dict]`：没有附件时返回原文；
  - `IMAGE_TYPES`（png / jpeg / gif / webp）、`MAX_IMAGE_BYTES = 5MB`；
  - `MainAgent.run(..., attachments: Sequence[Attachment] = ())`；
  - `ModelSwitchCleanupMiddleware(model, *, vision: bool)`、`strip_images(message)`、`IMAGE_OMITTED`。
- 产出（backend）：
  - `RunCreate.attachments: list[UUID]`（默认空，最多 10 个）；
  - `RunAttachment(id, path, media_type, size)`；
  - `RunRecord.attachments: list[RunAttachment]`（`RunHistory` 继承）；
  - 别的会话的文件 → `NotFoundError`（404）。
- 产出（测试替身）：`FakeGateway(model, *, vision_models=frozenset())`。

- [ ] **步骤 1：写失败的测试**

新建 `agents/tests/test_attachments.py`：

```python
"""用户随消息上传的文件（设计文档 9.3）：告诉模型文件在哪里；能看图的模型同时收到图片本身。"""

import base64
from pathlib import Path

from agents.main_agent.runtime import Attachment, user_content
from agents.main_agent.runtime.attachments import MAX_IMAGE_BYTES
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeSandbox

SHORT = "c_000000b1"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _workspace(tmp_path: Path, files: dict[str, bytes]) -> LocalWorkspace:
    for path, data in files.items():
        target = tmp_path / "workspace" / SHORT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return LocalWorkspace(tmp_path, FakeSandbox())


async def test_message_without_attachments_is_unchanged(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {})
    assert (
        await user_content("你好", [], short_id=SHORT, workspace=workspace, vision=True) == "你好"
    )


async def test_attachments_are_listed_with_their_full_paths(tmp_path: Path) -> None:
    files = [Attachment("uploads/销售.xlsx", XLSX, 10), Attachment("uploads/b.csv", "text/csv", 3)]
    content = await user_content(
        "分析一下", files, short_id=SHORT, workspace=_workspace(tmp_path, {}), vision=True
    )
    paths = f"/workspace/{SHORT}/uploads/销售.xlsx、/workspace/{SHORT}/uploads/b.csv"
    assert content == f"分析一下\n\n（用户上传了文件：{paths}）"


async def test_images_go_only_to_models_that_can_see(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {"uploads/a.png": b"png-bytes"})
    image = Attachment("uploads/a.png", "image/png", 9)
    content = await user_content(
        "图里是什么", [image], short_id=SHORT, workspace=workspace, vision=True
    )
    encoded = base64.b64encode(b"png-bytes").decode()
    assert content == [
        {
            "type": "text",
            "text": f"图里是什么\n\n（用户上传了文件：/workspace/{SHORT}/uploads/a.png）",
        },
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
    ]
    # 不能看图的模型只知道文件在哪里（可以用代码处理）
    blind = await user_content(
        "图里是什么", [image], short_id=SHORT, workspace=workspace, vision=False
    )
    assert blind == f"图里是什么\n\n（用户上传了文件：/workspace/{SHORT}/uploads/a.png）"


async def test_images_too_large_or_gone_are_only_listed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {"uploads/big.jpg": b"x"})
    big = Attachment("uploads/big.jpg", "image/jpeg", MAX_IMAGE_BYTES + 1)
    gone = Attachment("uploads/gone.png", "image/png", 10)
    content = await user_content(
        "看", [big, gone], short_id=SHORT, workspace=workspace, vision=True
    )
    assert isinstance(content, str)
```

在 `agents/tests/test_model_cleanup.py` 中，把：

```python

from agents.main_agent.models.cleanup import strip_foreign_thinking

```

改为：

```python

from agents.main_agent.models.cleanup import IMAGE_OMITTED, strip_foreign_thinking, strip_images

```

在 `agents/tests/test_model_cleanup.py` 末尾追加：

```python


def test_images_are_replaced_for_models_that_cannot_see() -> None:
    """换到不能看图的模型时，历史里的图片换成一句说明（原样发过去会被拒绝）；对话存档不变。"""
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    question = HumanMessage(content=[{"type": "text", "text": "看图"}, image])
    assert strip_images(question).content == [
        {"type": "text", "text": "看图"},
        {"type": "text", "text": IMAGE_OMITTED},
    ]
    assert question.content[1] == image
    plain = HumanMessage(content="hi")
    assert strip_images(plain) is plain
```

在 `agents/tests/fakes.py` 中，把：

```python

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

```

改为：

```python

    def __init__(
        self, model: BaseChatModel, *, vision_models: frozenset[str] = frozenset()
    ) -> None:
        self._model = model
        self._vision_models = vision_models  # 这些模型版本"能看图"

```

在 `agents/tests/fakes.py` 中，把：

```python
    def model_info(self, name: str) -> ModelInfo | None:
        return ModelInfo(name=name)

```

改为：

```python
    def model_info(self, name: str) -> ModelInfo | None:
        return ModelInfo(name=name, supports_vision=name in self._vision_models)

```

在 `agents/tests/test_main_agent.py` 中，把：

```python
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.runtime import (
    FileCreated,
```

改为：

```python
import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.runtime import (
    Attachment,
    FileCreated,
```

在 `agents/tests/test_main_agent.py` 末尾追加：

```python


async def test_uploaded_image_reaches_only_models_that_can_see(tmp_path: Path) -> None:
    """能看图的模型收到图片本身；同一会话换到不能看图的模型时，历史里的图片换成说明。"""
    uploads = tmp_path / "workspace" / SHORT / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "a.png").write_bytes(b"png")
    model = ScriptedChatModel(responses=[AIMessage("是一张图表"), AIMessage("好")])
    agent = MainAgent(
        gateway=FakeGateway(model, vision_models=frozenset({"eyes"})),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),
    )
    image = Attachment("uploads/a.png", "image/png", 3)
    async for _ in agent.run(
        thread_id="t1",
        thread_short_id=SHORT,
        run_id="r1",
        message="图里是什么",
        model="eyes",
        attachments=[image],
    ):
        pass
    async for _ in agent.run(
        thread_id="t1", thread_short_id=SHORT, run_id="r2", message="再说说", model="blind"
    ):
        pass
    first, second = model.received
    assert _block_types(first[-1]) == ["text", "image_url"]
    earlier_question = next(m for m in second if isinstance(m, HumanMessage))
    assert _block_types(earlier_question) == ["text", "text"]


def _block_types(message: BaseMessage) -> list[str]:
    assert isinstance(message.content, list)
    return [block["type"] for block in message.content if isinstance(block, dict)]
```

系统提示词要告诉模型上传的文件在 `uploads/`：

在 `agents/tests/test_subagents.py` 中，把：

```python
def test_system_prompt_explains_files_sandbox_and_delegation() -> None:
    """系统提示词告诉模型：能执行代码、产物放 outputs/、数据分析派 data_analyst、先看技能。"""
    prompt = (ROOT / "agents" / "prompts" / "system.md").read_text(encoding="utf-8")
    for phrase in ("execute", "outputs/", "data_analyst", "/skills/"):
        assert phrase in prompt, phrase
```

改为：

```python
def test_system_prompt_explains_files_sandbox_and_delegation() -> None:
    """系统提示词告诉模型：能执行代码、用户上传在 uploads/、产物放 outputs/、
    数据分析派 data_analyst、先看技能。"""
    prompt = (ROOT / "agents" / "prompts" / "system.md").read_text(encoding="utf-8")
    for phrase in ("execute", "uploads/", "outputs/", "data_analyst", "/skills/"):
        assert phrase in prompt, phrase
```

在 `backend/tests/test_manager.py` 末尾追加：

```python


async def test_attachments_are_recorded_and_given_to_the_agent(db: Pool, tmp_path: Path) -> None:
    thread = await ThreadRepo(db).create(model="m")
    uploads = tmp_path / "workspace" / thread.short_id / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "a.csv").write_text("x,y")
    record = await WorkspaceFileRepo(db).record(
        thread.id, "uploads/a.csv", source="upload", size=3, media_type="text/csv"
    )
    model = ScriptedChatModel(responses=[AIMessage("好")])
    workspace = LocalWorkspace(tmp_path, FakeSandbox())
    manager = _manager(db, RunRepo(db), model, workspace=workspace)
    run = await manager.start(thread.id, RunCreate(message="看看", attachments=[record.id]))
    assert [(a.id, a.path, a.media_type, a.size) for a in run.attachments] == [
        (record.id, "uploads/a.csv", "text/csv", 3)
    ]
    await asyncio.wait_for(_drain(manager, run.id), timeout=5)
    assert (await RunRepo(db).history(thread.id))[0].attachments == run.attachments
    assert f"/workspace/{thread.short_id}/uploads/a.csv" in str(model.received[0][-1].content)


async def test_attachments_from_other_threads_are_refused(db: Pool) -> None:
    threads = ThreadRepo(db)
    thread, other = await threads.create(model="m"), await threads.create(model="m")
    foreign = await WorkspaceFileRepo(db).record(
        other.id, "uploads/a.csv", source="upload", size=3, media_type="text/csv"
    )
    runs = RunRepo(db)
    manager = _manager(db, runs)
    with pytest.raises(NotFoundError):
        await manager.start(thread.id, RunCreate(message="看看", attachments=[foreign.id]))
    assert await runs.history(thread.id) == []
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_attachments.py agents/tests/test_model_cleanup.py agents/tests/test_main_agent.py agents/tests/test_subagents.py -q`（预期失败）

预期：收集阶段报错 `ImportError: cannot import name 'Attachment'`、`cannot import name 'IMAGE_OMITTED'`。

运行：`uv run pytest -m integration backend/tests/test_manager.py -q -k attachments`（预期失败）

预期：两个测试失败（`RunRecord` 没有 `attachments`；别的会话的文件没有被拒绝）。

- [ ] **步骤 3：实现（agents）**

新建 `agents/main_agent/runtime/attachments.py`：

```python
"""用户随消息上传的文件（设计文档 9.3）。

模型总会知道文件在哪里（可以用代码处理）；能看图的模型同时收到图片本身。
"""

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from agents.main_agent.workspace import Workspace

IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 各家模型单张图片的上限大致在这里（Claude 为 5MB）


@dataclass(frozen=True)
class Attachment:
    path: str  # 相对会话目录，如 uploads/a.png
    media_type: str
    size: int


async def user_content(
    message: str,
    attachments: Sequence[Attachment],
    *,
    short_id: str,
    workspace: Workspace,
    vision: bool,
) -> str | list[dict[str, Any]]:
    """这一轮交给模型的用户消息：没有附件时就是原文；有附件时附上文件位置，能看图时再附上图片。"""
    if not attachments:
        return message
    paths = "、".join(f"/workspace/{short_id}/{item.path}" for item in attachments)
    text = f"{message}\n\n（用户上传了文件：{paths}）"
    images: list[dict[str, Any]] = []
    for item in attachments:
        if not vision or item.media_type not in IMAGE_TYPES or item.size > MAX_IMAGE_BYTES:
            continue
        try:
            data = await workspace.read_file(short_id, item.path)
        except OSError:
            continue  # 文件已不在：模型照样知道路径，会自己发现
        encoded = base64.b64encode(data).decode()
        images.append(
            {"type": "image_url", "image_url": {"url": f"data:{item.media_type};base64,{encoded}"}}
        )
    return [{"type": "text", "text": text}, *images] if images else text
```

在 `agents/main_agent/runtime/__init__.py` 中，把：

```python
from agents.main_agent.runtime.agent import MainAgent
from agents.main_agent.runtime.events import (
```

改为：

```python
from agents.main_agent.runtime.agent import MainAgent
from agents.main_agent.runtime.attachments import Attachment, user_content
from agents.main_agent.runtime.events import (
```

在 `agents/main_agent/runtime/__init__.py` 中，把：

```python
    "EVENT_ADAPTER",
    "Event",
```

改为：

```python
    "EVENT_ADAPTER",
    "Attachment",
    "Event",
```

在 `agents/main_agent/runtime/__init__.py` 中，把：

```python
    "UsageTotals",
]
```

改为：

```python
    "UsageTotals",
    "user_content",
]
```

在 `agents/main_agent/models/cleanup.py` 中，把：

```python
"""换模型清理（设计文档 7.1）：会话中途换了模型时，旧模型产生的思考内容不交给新模型。

思考内容（含签名）只对产生它的模型有效，交给别家模型可能被拒绝。只在发给模型的请求里剥除，
对话存档保持原样，换回原模型时仍然完整。
"""
```

改为：

```python
"""换模型清理（设计文档 7.1）：会话中途换了模型时，请求里去掉新模型用不了的内容。

- 旧模型产生的思考内容（含签名）只对产生它的模型有效，交给别家模型可能被拒绝；
- 换到不能看图的模型时，历史里用户上传的图片换成一句说明（原样发过去会被拒绝）。

只在发给模型的请求里处理，对话存档保持原样，换回原模型时仍然完整。
"""
```

在 `agents/main_agent/models/cleanup.py` 中，把：

```python
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage

```

改为：

```python
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

```

在 `agents/main_agent/models/cleanup.py` 中，把：

```python
_THINKING_BLOCKS = frozenset({"thinking", "redacted_thinking", "reasoning"})

```

改为：

```python
_THINKING_BLOCKS = frozenset({"thinking", "redacted_thinking", "reasoning"})
IMAGE_OMITTED = "[图片已省略：当前模型不能看图，可以用代码处理图片文件]"

```

在 `agents/main_agent/models/cleanup.py` 中，把：

```python

class ModelSwitchCleanupMiddleware(AgentMiddleware):
    """每次调用模型前清理请求里的消息；model 为当前使用的模型版本名。"""

    def __init__(self, model: str) -> None:
        super().__init__()
        self._model = model

    def _clean(self, request: ModelRequest) -> ModelRequest:
        messages = [strip_foreign_thinking(m, self._model) for m in request.messages]
        return request.override(messages=messages)
```

改为：

```python

def strip_images(message: AnyMessage) -> AnyMessage:
    """用户消息里的图片换成一句说明；没有图片时原样返回。"""
    content = message.content
    if not isinstance(message, HumanMessage) or not isinstance(content, list):
        return message
    if not any(isinstance(b, dict) and b.get("type") == "image_url" for b in content):
        return message
    replaced = [
        {"type": "text", "text": IMAGE_OMITTED}
        if isinstance(block, dict) and block.get("type") == "image_url"
        else block
        for block in content
    ]
    return message.model_copy(update={"content": replaced})


class ModelSwitchCleanupMiddleware(AgentMiddleware):
    """每次调用模型前清理请求里的消息；model 为当前使用的模型版本名，vision 为它能否看图。"""

    def __init__(self, model: str, *, vision: bool) -> None:
        super().__init__()
        self._model = model
        self._vision = vision

    def _clean(self, request: ModelRequest) -> ModelRequest:
        messages = [strip_foreign_thinking(m, self._model) for m in request.messages]
        if not self._vision:
            messages = [strip_images(m) for m in messages]
        return request.override(messages=messages)
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
import logging
from collections.abc import AsyncIterator
from pathlib import Path
```

改为：

```python
import logging
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
from agents.main_agent.models import ModelGateway, ModelSwitchCleanupMiddleware
from agents.main_agent.runtime.events import (
```

改为：

```python
from agents.main_agent.models import ModelGateway, ModelSwitchCleanupMiddleware
from agents.main_agent.runtime.attachments import Attachment, user_content
from agents.main_agent.runtime.events import (
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
    async def run(
        self, *, thread_id: str, thread_short_id: str, run_id: str, message: str, model: str
    ) -> AsyncIterator[Event]:
```

改为：

```python
    async def run(
        self,
        *,
        thread_id: str,
        thread_short_id: str,
        run_id: str,
        message: str,
        model: str,
        attachments: Sequence[Attachment] = (),
    ) -> AsyncIterator[Event]:
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
            graph = self._graph_for(model)
            async for part in graph.astream(
                {"messages": [{"role": "user", "content": message}]},
                {
```

改为：

```python
            graph = self._graph_for(model)
            content = await user_content(
                message,
                attachments,
                short_id=thread_short_id,
                workspace=self.workspace,
                vision=self._can_see(model),
            )
            async for part in graph.astream(
                {"messages": [{"role": "user", "content": content}]},
                {
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
                TodoListMiddleware(),  # deepagents 0.7 默认不带待办清单，手动加回
                ModelSwitchCleanupMiddleware(model),
                InterruptionMarkerMiddleware(),  # 被打断的一轮补上"已中断"，模型不会重做
```

改为：

```python
                TodoListMiddleware(),  # deepagents 0.7 默认不带待办清单，手动加回
                ModelSwitchCleanupMiddleware(model, vision=self._can_see(model)),
                InterruptionMarkerMiddleware(),  # 被打断的一轮补上"已中断"，模型不会重做
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
        return self._graphs[model]

```

改为：

```python
        return self._graphs[model]

    def _can_see(self, model: str) -> bool:
        """模型能否看图（来自网关的模型信息；不知道时按不能处理）。"""
        info = self.models.model_info(model)
        return bool(info and info.supports_vision)

```

在 `agents/prompts/system.md` 中，把：

```markdown
- 每个会话有自己的工作目录（见本提示末尾），你可以在里面读写文件，并用 execute 工具在隔离的沙箱里运行命令：Python 3，已装 pandas、numpy、matplotlib、seaborn、openpyxl、python-docx、python-pptx、pymupdf、pillow；沙箱不能上网，不能安装新包。
- 交给用户的文件（图表、表格、报告等）放到工作目录的 outputs/ 下，回答里说明文件名；用户能在界面上直接查看和下载。
```

改为：

```markdown
- 每个会话有自己的工作目录（见本提示末尾），你可以在里面读写文件，并用 execute 工具在隔离的沙箱里运行命令：Python 3，已装 pandas、numpy、matplotlib、seaborn、openpyxl、python-docx、python-pptx、pymupdf、pillow；沙箱不能上网，不能安装新包。
- 用户上传的文件在工作目录的 uploads/ 下，消息末尾会注明本轮上传了哪些文件；能看图时，上传的图片也会直接附在消息里。
- 交给用户的文件（图表、表格、报告等）放到工作目录的 outputs/ 下，回答里说明文件名；用户能在界面上直接查看和下载。
```

- [ ] **步骤 4：实现（backend）**

附件存进运行记录的 `input`（`{"message", "attachments"}`），旧记录读出时补空列表：

在 `backend/runs/schemas.py` 中，把：

```python

from pydantic import BaseModel, StringConstraints

```

改为：

```python

from pydantic import BaseModel, Field, StringConstraints

```

在 `backend/runs/schemas.py` 中，把：

```python
    model: str | None = None

```

改为：

```python
    model: str | None = None
    # 这条消息附带的文件：已上传到本会话的文件 ID（POST /threads/{id}/files 的返回）
    attachments: list[UUID] = Field(default=[], max_length=10)


class RunAttachment(BaseModel):
    """随消息附带的文件。运行记录里存一份，界面历史据此在用户消息下显示。"""

    id: UUID
    path: str  # 相对会话目录，如 uploads/a.xlsx
    media_type: str
    size: int

```

在 `backend/runs/schemas.py` 中，把：

```python
    message: str
    error: str | None
```

改为：

```python
    message: str
    attachments: list[RunAttachment]
    error: str | None
```

在 `backend/runs/__init__.py` 中，把：

```python
from backend.runs.repo import RunRepo
from backend.runs.schemas import RunCreate, RunHistory, RunRecord

__all__ = ["RunCreate", "RunHistory", "RunManager", "RunRecord", "RunRepo"]
```

改为：

```python
from backend.runs.repo import RunRepo
from backend.runs.schemas import RunAttachment, RunCreate, RunHistory, RunRecord

__all__ = ["RunAttachment", "RunCreate", "RunHistory", "RunManager", "RunRecord", "RunRepo"]
```

在 `backend/runs/repo.py` 中，把：

```python

from uuid import UUID
```

改为：

```python

from collections.abc import Sequence
from uuid import UUID
```

在 `backend/runs/repo.py` 中，把：

```python
from agents.main_agent.runtime import UsageTotals
from backend.runs.schemas import RunHistory, RunRecord
from backend.runtime import EventEnvelope
```

改为：

```python
from agents.main_agent.runtime import UsageTotals
from backend.runs.schemas import RunAttachment, RunHistory, RunRecord
from backend.runtime import EventEnvelope
```

在 `backend/runs/repo.py` 中，把：

```python

_COLUMNS = "id, thread_id, status, model, input->>'message' AS message, error, created_at"

```

改为：

```python

# 用户输入存在 input 里：{"message": 原文, "attachments": [附带的文件]}（没有附件的旧记录不带后者）
_COLUMNS = (
    "id, thread_id, status, model, input->>'message' AS message, "
    "COALESCE(input->'attachments', '[]'::jsonb) AS attachments, error, created_at"
)

```

在 `backend/runs/repo.py` 中，把：

```python

    async def create(self, *, thread_id: UUID, model: str, message: str) -> RunRecord:
        """新建一条运行中的记录；同一会话已有进行中的运行时抛 ConflictError（由唯一索引保证）。"""
        try:
```

改为：

```python

    async def create(
        self,
        *,
        thread_id: UUID,
        model: str,
        message: str,
        attachments: Sequence[RunAttachment] = (),
    ) -> RunRecord:
        """新建一条运行中的记录；同一会话已有进行中的运行时抛 ConflictError（由唯一索引保证）。"""
        user_input = {
            "message": message,
            "attachments": [item.model_dump(mode="json") for item in attachments],
        }
        try:
```

在 `backend/runs/repo.py` 中，把：

```python
                    f"VALUES (%s, %s, 'running', %s, %s) RETURNING {_COLUMNS}",
                    (new_id(), thread_id, model, Jsonb({"message": message})),
                )
```

改为：

```python
                    f"VALUES (%s, %s, 'running', %s, %s) RETURNING {_COLUMNS}",
                    (new_id(), thread_id, model, Jsonb(user_input)),
                )
```

在 `backend/runs/manager.py` 中，把：

```python
from agents.main_agent.runtime import (
    Event,
```

改为：

```python
from agents.main_agent.runtime import (
    Attachment,
    Event,
```

在 `backend/runs/manager.py` 中，把：

```python
from backend.runs.repo import RunRepo
from backend.runs.schemas import RunCreate, RunRecord
from backend.runs.writer import EventWriter
from backend.runtime import EventBus, EventEnvelope, RunControl
from backend.threads import ThreadRepo
from common.errors import ConflictError

```

改为：

```python
from backend.runs.repo import RunRepo
from backend.runs.schemas import RunAttachment, RunCreate, RunRecord
from backend.runs.writer import EventWriter
from backend.runtime import EventBus, EventEnvelope, RunControl
from backend.threads import ThreadRepo
from common.errors import ConflictError, NotFoundError

```

在 `backend/runs/manager.py` 中，把：

```python
        thread = await self._threads.get(thread_id)
        run = await self._runs.create(
            thread_id=thread.id, model=body.model or thread.model, message=body.message
        )
```

改为：

```python
        thread = await self._threads.get(thread_id)
        attachments = [await self._attachment(thread.id, file_id) for file_id in body.attachments]
        run = await self._runs.create(
            thread_id=thread.id,
            model=body.model or thread.model,
            message=body.message,
            attachments=attachments,
        )
```

在 `backend/runs/manager.py` 中，把：

```python
                model=run.model,
            ):
```

改为：

```python
                model=run.model,
                attachments=[Attachment(a.path, a.media_type, a.size) for a in run.attachments],
            ):
```

在 `backend/runs/manager.py` 中，把：

```python

    async def _record_file(self, run: RunRecord, event: FileCreated) -> None:
```

改为：

```python

    async def _attachment(self, thread_id: UUID, file_id: UUID) -> RunAttachment:
        """消息附带的文件必须是本会话登记过的文件。"""
        record = await self._files.get(file_id)
        if record.thread_id != thread_id:
            raise NotFoundError(f"附件不存在：{file_id}")
        return RunAttachment(
            id=record.id, path=record.path, media_type=record.media_type, size=record.size
        )

    async def _record_file(self, run: RunRecord, event: FileCreated) -> None:
```

- [ ] **步骤 5：运行测试，确认通过**

运行：`uv run pytest agents/tests/test_attachments.py agents/tests/test_model_cleanup.py agents/tests/test_main_agent.py agents/tests/test_subagents.py -q`

运行：`uv run pytest -m integration backend/tests/test_manager.py backend/tests/test_api.py -q`

预期：全部通过。

- [ ] **步骤 6：前端类型与测试夹具**

运行记录多了 `attachments`，重新生成前端类型；前端测试里的界面历史样例补上空的附件列表（否则类型检查不通过）：

运行：`make types`

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
        message: "hi",
        error: null,
```

改为：

```ts
        message: "hi",
        attachments: [],
        error: null,
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
        message: "hi",
        error: "服务重启中断",
```

改为：

```ts
        message: "hi",
        attachments: [],
        error: "服务重启中断",
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
    message: "hi",
    error: null,
```

改为：

```ts
    message: "hi",
    attachments: [],
    error: null,
```

- [ ] **步骤 7：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 163 个、前端 71 个）；`make test-int` 全部通过（集成测试 68 个）。

---

### 任务 4：表格预览接口

**文件：**
- 新建：`backend/files/__init__.py`、`backend/files/preview.py`、`backend/tests/test_preview.py`
- 修改：`pyproject.toml`、`uv.lock`（命令生成）、`backend/api/router.py`、`backend/tests/test_api.py`、`frontend/src/api/generated/*`（命令生成）

**接口：**
- 消费：任务 1 的 `Workspace.read_file`。
- 产出（`backend.files`）：
  - `TablePreview(sheets: list[str], sheet: str | None, rows: list[list[str]], truncated: bool)`：每行补齐到同样的列数，第一行通常是表头；
  - `table_preview(name, data, *, sheet=None, limit=100) -> TablePreview`；
  - `PreviewError`（消息直接给用户看）；
  - `MAX_PREVIEW_BYTES = 20MB`。
- 产出（接口）：`GET /api/threads/{thread_id}/files/{file_id}/table?sheet=`：
  - 不是表格或工作表不存在 → 422 带说明；
  - 超过 20MB → 413"文件太大，无法预览，请下载查看"；
  - 别的会话的文件 → 404。

- [ ] **步骤 1：新增依赖**

在 `pyproject.toml` 中，把：

```toml
    "pyyaml==6.0.3",
]
```

改为：

```toml
    "pyyaml==6.0.3",
    "openpyxl==3.1.5",
]
```

在 `pyproject.toml` 中，把：

```toml
    "ruff==0.17.0",
    "types-pyyaml==6.0.12.20260906",
```

改为：

```toml
    "ruff==0.17.0",
    "types-openpyxl==3.1.5.20260827",
    "types-pyyaml==6.0.12.20260906",
```

运行：`uv lock`

预期：`uv.lock` 新增 `openpyxl 3.1.5`、`et-xmlfile 2.0.0`、`types-openpyxl 3.1.5.20260827`。

- [ ] **步骤 2：写失败的测试**

新建 `backend/tests/test_preview.py`：

```python
"""表格预览（设计文档 9.3）：CSV / Excel 只显示前若干行，单元格一律转成文字。"""

import io
from datetime import datetime

import pytest
from openpyxl import Workbook

from backend.files import PreviewError, table_preview


def _xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    book = Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_csv_with_bom_or_from_chinese_excel_is_readable() -> None:
    """Excel 导出的 CSV 常带 BOM，中文系统上还常是 GBK 编码。"""
    utf8 = table_preview("a.csv", "﻿地区,金额\n华东,120\n".encode())
    gbk = table_preview("b.csv", "地区,金额\n华东,120\n".encode("gbk"))
    for preview in (utf8, gbk):
        assert preview.rows == [["地区", "金额"], ["华东", "120"]]
        assert (preview.sheets, preview.sheet, preview.truncated) == ([], None, False)


def test_only_the_first_rows_are_shown() -> None:
    data = "\n".join(f"{i},{i * 2}" for i in range(150)).encode()
    preview = table_preview("a.csv", data, limit=100)
    assert len(preview.rows) == 100
    assert preview.rows[-1] == ["99", "198"]
    assert preview.truncated is True


def test_rows_of_different_lengths_are_padded() -> None:
    preview = table_preview("a.tsv", b"a\tb\tc\n1\n")
    assert preview.rows == [["a", "b", "c"], ["1", "", ""]]


def test_excel_sheets_can_be_switched() -> None:
    data = _xlsx(
        {
            "汇总": [["地区", "金额"], ["华东", 120.5], ["华南", None]],
            "明细": [["日期"], [datetime(2026, 10, 1, 9, 30)]],
        }
    )
    first = table_preview("报表.xlsx", data)
    assert (first.sheets, first.sheet) == (["汇总", "明细"], "汇总")
    assert first.rows == [["地区", "金额"], ["华东", "120.5"], ["华南", ""]]
    detail = table_preview("报表.xlsx", data, sheet="明细")
    assert (detail.sheet, detail.rows) == ("明细", [["日期"], ["2026-10-01 09:30:00"]])


def test_unknown_sheet_or_broken_file_is_explained() -> None:
    data = _xlsx({"汇总": [["a"]]})
    with pytest.raises(PreviewError, match="工作表不存在：明细"):
        table_preview("a.xlsx", data, sheet="明细")
    with pytest.raises(PreviewError, match="不是有效的 Excel 文件"):
        table_preview("a.xlsx", b"not a zip")
    with pytest.raises(PreviewError, match="不能按表格预览"):
        table_preview("a.png", b"png")
```

在 `backend/tests/test_api.py` 末尾追加：

```python


async def test_table_preview_of_an_uploaded_csv(make_client: ClientFactory, tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path, FakeSandbox())
    async with make_client(ScriptedChatModel(responses=[]), workspace=workspace) as client:
        thread = (await client.post("/api/threads", json={})).json()
        files = f"/api/threads/{thread['id']}/files"
        csv = (
            await client.post(files, content=b"a,b\n1,2\n", headers={"X-File-Name": "t.csv"})
        ).json()
        png = (await client.post(files, content=b"png", headers={"X-File-Name": "p.png"})).json()

        table = await client.get(f"{files}/{csv['id']}/table")
        assert table.json() == {
            "sheets": [],
            "sheet": None,
            "rows": [["a", "b"], ["1", "2"]],
            "truncated": False,
        }
        refused = await client.get(f"{files}/{png['id']}/table")
        assert refused.status_code == 422
        assert refused.json()["detail"] == "这种文件不能按表格预览"

        other = (await client.post("/api/threads", json={})).json()
        stolen = f"/api/threads/{other['id']}/files/{csv['id']}/table"
        assert (await client.get(stolen)).status_code == 404
```

- [ ] **步骤 3：运行测试，确认失败**

运行：`uv run pytest backend/tests/test_preview.py -q`（预期失败）

预期：收集阶段报错 `ModuleNotFoundError: No module named 'backend.files'`。

运行：`uv run pytest -m integration backend/tests/test_api.py -q -k table`（预期失败）

预期：接口还不存在，返回的不是表格内容。

- [ ] **步骤 4：实现**

新建 `backend/files/preview.py`：

```python
"""表格预览（设计文档 9.3）：CSV / Excel 只取前若干行，单元格一律转成文字，交给前端画表格。"""

import csv
import io
from datetime import date, datetime, time
from pathlib import PurePosixPath
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel

PREVIEW_ROWS = 100
MAX_COLUMNS = 50
MAX_PREVIEW_BYTES = 20 * 1024 * 1024  # 更大的文件整读进内存不划算，请用户下载查看
_DELIMITERS = {".csv": ",", ".tsv": "\t"}
_EXCEL = frozenset({".xlsx", ".xlsm"})


class TablePreview(BaseModel):
    sheets: list[str]  # Excel 的工作表名（按顺序）；CSV 为空
    sheet: str | None  # 当前显示的工作表
    rows: list[list[str]]  # 前若干行（第一行通常是表头），每行补齐到同样的列数
    truncated: bool  # 后面还有没显示的行


class PreviewError(Exception):
    """不能按表格预览；消息直接给用户看。"""


def table_preview(
    name: str, data: bytes, *, sheet: str | None = None, limit: int = PREVIEW_ROWS
) -> TablePreview:
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in _DELIMITERS:
        reader = csv.reader(io.StringIO(_decode(data)), delimiter=_DELIMITERS[suffix])
        rows = [row for _, row in zip(range(limit + 1), reader, strict=False)]
        return _preview(rows, limit, sheets=[], sheet=None)
    if suffix in _EXCEL:
        return _excel(data, sheet, limit)
    raise PreviewError("这种文件不能按表格预览")


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")  # Excel 导出的 UTF-8 文件常带 BOM
    except UnicodeDecodeError:
        return data.decode("gb18030", errors="replace")  # 中文系统上的 Excel 导出常是 GBK


def _excel(data: bytes, sheet: str | None, limit: int) -> TablePreview:
    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, KeyError, OSError) as exc:
        raise PreviewError("不是有效的 Excel 文件") from exc
    try:
        names = book.sheetnames
        name = sheet or names[0]
        if name not in names:
            raise PreviewError(f"工作表不存在：{name}")
        rows = [
            [_text(value) for value in row]
            for row in book[name].iter_rows(max_row=limit + 1, values_only=True)
        ]
    finally:
        book.close()
    return _preview(rows, limit, sheets=names, sheet=name)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date | time):
        return value.isoformat()
    return str(value)


def _preview(
    rows: list[list[str]], limit: int, *, sheets: list[str], sheet: str | None
) -> TablePreview:
    shown = rows[:limit]
    width = min(MAX_COLUMNS, max((_used_width(row) for row in shown), default=0))
    return TablePreview(
        sheets=sheets,
        sheet=sheet,
        rows=[(row + [""] * width)[:width] for row in shown],
        truncated=len(rows) > limit,
    )


def _used_width(row: list[str]) -> int:
    """去掉行尾空单元格后的列数（Excel 的整行常带一长串空格子）。"""
    for index in range(len(row), 0, -1):
        if row[index - 1]:
            return index
    return 0
```

新建 `backend/files/__init__.py`：

```python
"""会话文件的预览（文件本身的登记与读写在 agents 的工作区模块）。"""

from backend.files.preview import MAX_PREVIEW_BYTES, PreviewError, TablePreview, table_preview

__all__ = ["MAX_PREVIEW_BYTES", "PreviewError", "TablePreview", "table_preview"]
```

下载与预览共用"会话 + 文件"的检查：

在 `backend/api/router.py` 中，把：

```python

from collections.abc import AsyncIterator
```

改为：

```python

import asyncio
from collections.abc import AsyncIterator
```

在 `backend/api/router.py` 中，把：

```python

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
```

改为：

```python

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
```

在 `backend/api/router.py` 中，把：

```python
from agents.main_agent.workspace import WorkspaceFile, media_type
from backend.api.deps import ServicesDep
from backend.runs import RunCreate, RunHistory, RunRecord
```

改为：

```python
from agents.main_agent.workspace import WorkspaceFile, media_type
from backend.api.deps import Services, ServicesDep
from backend.files import MAX_PREVIEW_BYTES, PreviewError, TablePreview, table_preview
from backend.runs import RunCreate, RunHistory, RunRecord
```

在 `backend/api/router.py` 中，把：

```python
    """读取会话里的一个文件：默认在页面里直接显示，download=1 时作为附件下载。边读边传。"""
    thread = await services.threads.get(thread_id)
    record = await services.files.get(file_id)
    if record.thread_id != thread.id:
        raise NotFoundError("文件不存在")
    try:
```

改为：

```python
    """读取会话里的一个文件：默认在页面里直接显示，download=1 时作为附件下载。边读边传。"""
    thread, record = await _thread_file(services, thread_id, file_id)
    try:
```

在 `backend/api/router.py` 中，把：

```python
        },
    )


```

改为：

```python
        },
    )


@api_router.get("/threads/{thread_id}/files/{file_id}/table")
async def file_table(
    thread_id: UUID, file_id: UUID, services: ServicesDep, sheet: str | None = None
) -> TablePreview:
    """CSV / Excel 文件的前若干行（表格预览）；sheet 为 Excel 的工作表名，缺省为第一个。"""
    thread, record = await _thread_file(services, thread_id, file_id)
    if record.size > MAX_PREVIEW_BYTES:
        raise TooLargeError("文件太大，无法预览，请下载查看")
    try:
        data = await services.agent.workspace.read_file(thread.short_id, record.path)
    except (FileNotFoundError, PermissionError):
        raise NotFoundError("文件已不存在") from None
    try:
        return await asyncio.to_thread(table_preview, record.path, data, sheet=sheet)
    except PreviewError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


async def _thread_file(
    services: Services, thread_id: UUID, file_id: UUID
) -> tuple[Thread, WorkspaceFile]:
    """会话与其中登记过的一个文件；文件不属于该会话时同样是"不存在"。"""
    thread = await services.threads.get(thread_id)
    record = await services.files.get(file_id)
    if record.thread_id != thread.id:
        raise NotFoundError("文件不存在")
    return thread, record


```

- [ ] **步骤 5：运行测试，确认通过**

运行：`uv run pytest backend/tests/test_preview.py -q`

运行：`uv run pytest -m integration backend/tests/test_api.py -q`

预期：全部通过（预览 5 个；接口 21 个）。

- [ ] **步骤 6：检查点**

运行：`make types`

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 168 个、前端 71 个）；`make test-int` 全部通过（集成测试 69 个）。

---

### 任务 5：右侧文件面板与预览

**文件：**
- 新建：`frontend/src/features/files/kind.ts`、`kind.test.ts`、`FilePanel.tsx`、`FilePreview.tsx`、`frontend/src/components/chat/fileActions.ts`
- 修改：`frontend/package.json`、`pnpm-lock.yaml`（命令生成）、`frontend/src/api/types.ts`、`client.ts`、`client.test.ts`、`queries.ts`、`frontend/src/components/chat/format.ts`、`adapter.ts`、`adapter.test.ts`、`parts.tsx`、`ChatThread.tsx`、`frontend/src/features/chat/ChatView.tsx`

**接口：**
- 消费：任务 2 的 `GET …/files`、任务 4 的 `GET …/table`、任务 1 的 `…/content`。
- 产出（`api/`）：
  - 类型别名 `WorkspaceFile`、`TablePreview`；
  - `api.listFiles(threadId)`；
  - `api.tablePreview(threadId, fileId, sheet: string | null)`；
  - `api.fileText(threadId, fileId)`（文件原文，失败时抛 `ApiError` 带后端的说明）；
  - `filesQuery(threadId)`（键 `["files", threadId]`）；
  - `tablePreviewQuery(file, sheet)`、`fileTextQuery(file)`（键里带 `updated_at`）。
- 产出（`features/files/`）：
  - `previewKind(file) -> "image" | "table" | "pdf" | "markdown" | "html" | "text" | "none"`；
  - `groupFiles(files) -> { uploads, outputs }`；
  - `FilePanel({ threadId, selectedId, onSelect, onClose })`；
  - `FilePreview({ file })`。
- 产出（`components/chat/`）：
  - `fileName(path)`（`format.ts`）；
  - `FileCardData.fileId`；
  - `OpenFileContext`（在面板里打开一个文件）；
  - `ChatThread` 新增必填属性 `onOpenFile(fileId)`。

- [ ] **步骤 1：新增依赖**

运行：`cd frontend && pnpm add -E react-markdown@10.1.0`

预期：`package.json` 的依赖多一行 `"react-markdown": "10.1.0"`；`pnpm-lock.yaml` 只多 3 行（包本来就装着）。

- [ ] **步骤 2：写失败的测试**

新建 `frontend/src/features/files/kind.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import type { WorkspaceFile } from "../../api/types";
import { groupFiles, previewKind } from "./kind";

const file = (path: string, media_type: string, size = 10): WorkspaceFile => ({
  id: path,
  thread_id: "t1",
  path,
  source: path.startsWith("uploads/") ? "upload" : "output",
  media_type,
  size,
  created_at: "2026-10-15T00:00:00Z",
  updated_at: "2026-10-15T00:00:00Z",
});

describe("按文件类型选择预览方式", () => {
  it("图片、表格、PDF、Markdown、网页各有预览", () => {
    expect(previewKind(file("outputs/a.png", "image/png"))).toBe("image");
    expect(previewKind(file("outputs/a.svg", "image/svg+xml"))).toBe("image");
    expect(previewKind(file("uploads/a.csv", "text/csv"))).toBe("table");
    expect(previewKind(file("uploads/a.TSV", "text/tab-separated-values"))).toBe("table");
    const xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    expect(previewKind(file("outputs/报表.xlsx", xlsx))).toBe("table");
    expect(previewKind(file("outputs/a.pdf", "application/pdf"))).toBe("pdf");
    expect(previewKind(file("outputs/a.md", "text/markdown"))).toBe("markdown");
    expect(previewKind(file("outputs/a.html", "text/html"))).toBe("html");
  });

  it("文字与代码直接显示原文；太大的、其他类型只能下载", () => {
    expect(previewKind(file("outputs/a.py", "text/x-python"))).toBe("text");
    expect(previewKind(file("outputs/a.json", "application/json"))).toBe("text");
    expect(previewKind(file("outputs/log.txt", "text/plain", 2 * 1024 * 1024))).toBe("none");
    expect(previewKind(file("uploads/a.docx", "application/vnd.ms-word"))).toBe("none");
    expect(previewKind(file("uploads/a.bin", "application/octet-stream"))).toBe("none");
  });
});

describe("文件面板的分组", () => {
  it("上传与产物分开，各自保持原来的顺序", () => {
    const files = [
      file("outputs/b.png", "image/png"),
      file("uploads/a.csv", "text/csv"),
      file("outputs/c.md", "text/markdown"),
    ];
    const groups = groupFiles(files);
    expect(groups.uploads.map((f) => f.path)).toEqual(["uploads/a.csv"]);
    expect(groups.outputs.map((f) => f.path)).toEqual(["outputs/b.png", "outputs/c.md"]);
  });
});
```

在 `frontend/src/api/client.test.ts` 末尾追加：

```ts

describe("会话文件", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("表格预览按工作表名取数据，名字经过编码", async () => {
    const preview = { sheets: ["明细"], sheet: "明细", rows: [["a"]], truncated: false };
    const fetchMock = vi.fn(async () => Response.json(preview));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.tablePreview("t1", "f1", "明细")).resolves.toEqual(preview);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/threads/t1/files/f1/table?sheet=%E6%98%8E%E7%BB%86",
      expect.anything(),
    );
    await api.tablePreview("t1", "f1", null);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/threads/t1/files/f1/table", expect.anything());
  });

  it("读取文件原文；文件已不在时给出后端的说明", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("# 标题", { headers: { "content-type": "text/markdown" } })),
    );
    await expect(api.fileText("t1", "f1")).resolves.toBe("# 标题");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ detail: "文件已不存在" }, { status: 404 })),
    );
    await expect(api.fileText("t1", "f1")).rejects.toThrow("文件已不存在");
  });
});
```

产物卡片的数据带上文件 ID（点卡片时在面板里打开）：

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
        data: {
          name: "chart.png",
```

改为：

```ts
        data: {
          fileId: "f1",
          name: "chart.png",
```

- [ ] **步骤 3：运行测试，确认失败**

运行：`cd frontend && pnpm exec vitest run src/features/files src/api/client.test.ts src/components/chat/adapter.test.ts`（预期失败）

预期：
- `kind.test.ts` 找不到 `./kind`；
- `api.tablePreview is not a function`、`api.fileText is not a function`；
- 文件数据片段缺少 `fileId`。

- [ ] **步骤 4：实现数据层**

在 `frontend/src/api/types.ts` 中，把：

```ts
export type TodoItem = Schemas["TodoItem"];

```

改为：

```ts
export type TodoItem = Schemas["TodoItem"];
export type WorkspaceFile = Schemas["WorkspaceFile"];
export type TablePreview = Schemas["TablePreview"];

```

在 `frontend/src/api/client.ts` 中，把：

```ts
import type { ModelInfo, RunHistory, RunRecord, Thread, ThreadUsage } from "./types";

```

改为：

```ts
import type {
  ModelInfo,
  RunHistory,
  RunRecord,
  TablePreview,
  Thread,
  ThreadUsage,
  WorkspaceFile,
} from "./types";

```

在 `frontend/src/api/client.ts` 中，把：

```ts

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
```

改为：

```ts

/** 发请求；连不上或状态码不是 2xx 时抛出看得懂的错误。 */
async function send(path: string, init?: RequestInit): Promise<Response> {
  let resp: Response;
```

在 `frontend/src/api/client.ts` 中，把：

```ts
  }
  if (resp.status === 204) return undefined as T; // 没有内容（如保存顺序）
```

改为：

```ts
  }
  return resp;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await send(path, init);
  if (resp.status === 204) return undefined as T; // 没有内容（如保存顺序）
```

在 `frontend/src/api/client.ts` 中，把：

```ts
  threadUsage: (threadId: string) => request<ThreadUsage>(`/threads/${threadId}/usage`),
  // 令牌正确时服务器写入 Cookie，之后的请求（含推送）由浏览器自动带上
```

改为：

```ts
  threadUsage: (threadId: string) => request<ThreadUsage>(`/threads/${threadId}/usage`),
  listFiles: (threadId: string) => request<WorkspaceFile[]>(`/threads/${threadId}/files`),
  /** CSV / Excel 的前若干行；sheet 为 Excel 的工作表名，null 表示第一个。 */
  tablePreview: (threadId: string, fileId: string, sheet: string | null) =>
    request<TablePreview>(
      `/threads/${threadId}/files/${fileId}/table` +
        (sheet === null ? "" : `?sheet=${encodeURIComponent(sheet)}`),
    ),
  /** 文件原文（Markdown、代码等文字文件的预览）。 */
  fileText: async (threadId: string, fileId: string) =>
    (await send(`/threads/${threadId}/files/${fileId}/content`)).text(),
  // 令牌正确时服务器写入 Cookie，之后的请求（含推送）由浏览器自动带上
```

在 `frontend/src/api/queries.ts` 中，把：

```ts
import { api, needsAccessToken } from "./client";

```

改为：

```ts
import { api, needsAccessToken } from "./client";
import type { WorkspaceFile } from "./types";

```

在 `frontend/src/api/queries.ts` 中，把：

```ts

/** 会话累计用量；每次运行结束后由对话区主动刷新。 */
```

改为：

```ts

/** 会话里的文件（上传与产物）；收到 file.created 或上传完成时由对话区主动刷新。 */
export function filesQuery(threadId: string) {
  return { queryKey: ["files", threadId], queryFn: () => api.listFiles(threadId) };
}

// 预览按文件的更新时间缓存：同一文件被改写后（文件 ID 不变）重新读取
export function tablePreviewQuery(file: WorkspaceFile, sheet: string | null) {
  return {
    queryKey: ["file-table", file.id, file.updated_at, sheet],
    queryFn: () => api.tablePreview(file.thread_id, file.id, sheet),
    retry: 0,
  };
}

export function fileTextQuery(file: WorkspaceFile) {
  return {
    queryKey: ["file-text", file.id, file.updated_at],
    queryFn: () => api.fileText(file.thread_id, file.id),
    retry: 0,
  };
}

/** 会话累计用量；每次运行结束后由对话区主动刷新。 */
```

新建 `frontend/src/features/files/kind.ts`：

```ts
import type { WorkspaceFile } from "../../api/types";

/** 文件面板里的预览方式（设计文档 9.3）；none 表示只能下载。 */
export type PreviewKind = "image" | "table" | "pdf" | "markdown" | "html" | "text" | "none";

const TABLE_SUFFIXES = [".csv", ".tsv", ".xlsx", ".xlsm"];
const TEXT_TYPES = new Set(["application/json", "application/xml", "application/javascript"]);
const MAX_TEXT_BYTES = 1024 * 1024; // 更大的文字文件不在页面里显示，请下载查看

export function previewKind(
  file: Pick<WorkspaceFile, "path" | "media_type" | "size">,
): PreviewKind {
  const path = file.path.toLowerCase();
  const type = file.media_type;
  if (type.startsWith("image/")) return "image";
  if (TABLE_SUFFIXES.some((suffix) => path.endsWith(suffix))) return "table";
  if (type === "application/pdf") return "pdf";
  if (type === "text/html") return "html";
  const isText = type.startsWith("text/") || TEXT_TYPES.has(type);
  if (!isText || file.size > MAX_TEXT_BYTES) return "none";
  return type === "text/markdown" ? "markdown" : "text";
}

/** 面板里分两组：用户上传的、智能体生成的（接口返回时已按路径排好）。 */
export function groupFiles(files: WorkspaceFile[]): {
  uploads: WorkspaceFile[];
  outputs: WorkspaceFile[];
} {
  return {
    uploads: files.filter((file) => file.source === "upload"),
    outputs: files.filter((file) => file.source === "output"),
  };
}
```

文件名的取法从转换函数里提出来，卡片与面板共用：

在 `frontend/src/components/chat/format.ts` 末尾追加：

```ts

/** 路径里的文件名（最后一段）。 */
export function fileName(path: string): string {
  return path.split("/").at(-1) ?? path;
}
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
import type { ChatItem, ChatState } from "../../features/chat/reducer";

```

改为：

```ts
import type { ChatItem, ChatState } from "../../features/chat/reducer";
import { fileName } from "./format";

```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
export interface FileCardData {
  name: string;
```

改为：

```ts
export interface FileCardData {
  fileId: string;
  name: string;
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
      const data: FileCardData = {
        name: item.path.split("/").at(-1) ?? item.path,
        path: item.path,
```

改为：

```ts
      const data: FileCardData = {
        fileId: item.fileId,
        name: fileName(item.path),
        path: item.path,
```

- [ ] **步骤 5：运行测试，确认通过**

运行：`cd frontend && pnpm exec vitest run src/features/files src/api/client.test.ts src/components/chat/adapter.test.ts`

预期：全部通过。

- [ ] **步骤 6：面板与预览**

点产物卡片的图片或文件名时，经 `OpenFileContext` 在面板里打开（"打开""下载"按钮保持不变）：

新建 `frontend/src/components/chat/fileActions.ts`：

```ts
import { createContext } from "react";

/** 在右侧文件面板里打开一个文件（由页面提供；产物卡片、附件标签点击时调用）。 */
export const OpenFileContext = createContext<(fileId: string) => void>(() => {});
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import remarkGfm from "remark-gfm";
```

改为：

```tsx
} from "lucide-react";
import { useContext, useEffect, useState, type ReactNode } from "react";
import remarkGfm from "remark-gfm";
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
} from "./adapter";
import { formatSize } from "./format";
```

改为：

```tsx
} from "./adapter";
import { OpenFileContext } from "./fileActions";
import { formatSize } from "./format";
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx

/** 产物文件卡片：图片直接显示；其他文件显示名称与大小。都可以在新标签页打开或下载。 */
export const FilePart: DataMessagePartComponent = ({ data }) => {
  const file = data as FileCardData;
  return (
    <div className="my-2 max-w-md overflow-hidden rounded-lg border border-border bg-card text-sm">
      {file.mediaType.startsWith("image/") && (
        <a href={file.url} target="_blank" rel="noopener noreferrer">
          <img
```

改为：

```tsx

/**
 * 产物文件卡片：图片直接显示；其他文件显示名称与大小。
 * 点图片或文件名在右侧文件面板里预览；也可以在新标签页打开或下载。
 */
export const FilePart: DataMessagePartComponent = ({ data }) => {
  const file = data as FileCardData;
  const openFile = useContext(OpenFileContext);
  return (
    <div className="my-2 max-w-md overflow-hidden rounded-lg border border-border bg-card text-sm">
      {file.mediaType.startsWith("image/") && (
        <button
          className="block w-full"
          onClick={() => openFile(file.fileId)}
          title="在文件面板里预览"
        >
          <img
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
          />
        </a>
      )}
      <div className="flex items-center gap-2 px-3 py-2">
        <FileText className="size-4 shrink-0 text-muted-foreground" />
        <span className="truncate" title={file.path}>
          {file.name}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">{formatSize(file.size)}</span>
```

改为：

```tsx
          />
        </button>
      )}
      <div className="flex items-center gap-2 px-3 py-2">
        <FileText className="size-4 shrink-0 text-muted-foreground" />
        <button
          className="truncate hover:underline"
          title={`${file.path}（在文件面板里预览）`}
          onClick={() => openFile(file.fileId)}
        >
          {file.name}
        </button>
        <span className="shrink-0 text-xs text-muted-foreground">{formatSize(file.size)}</span>
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
import { toThreadMessages, type FileUrl } from "./adapter";
import { AssistantMessage, UserMessage } from "./parts";
```

改为：

```tsx
import { toThreadMessages, type FileUrl } from "./adapter";
import { OpenFileContext } from "./fileActions";
import { AssistantMessage, UserMessage } from "./parts";
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
  fileUrl: FileUrl;
}
```

改为：

```tsx
  fileUrl: FileUrl;
  /** 在右侧文件面板里打开一个文件。 */
  onOpenFile: (fileId: string) => void;
}
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
  fileUrl,
}: ChatThreadProps) {
```

改为：

```tsx
  fileUrl,
  onOpenFile,
}: ChatThreadProps) {
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
        <ThreadPrimitive.Viewport className="flex flex-1 flex-col overflow-y-auto">
          <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-8">
            <ThreadPrimitive.Empty>
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center text-muted-foreground">
                <Sparkles className="size-8 text-warning" />
                <p className="text-lg text-foreground">今天想做点什么？</p>
                <p className="text-sm">输入问题开始对话，Enter 发送，Shift+Enter 换行</p>
              </div>
            </ThreadPrimitive.Empty>
            <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
          </div>
        </ThreadPrimitive.Viewport>
        <div className="mx-auto w-full max-w-3xl px-6 pb-6">
          {notice && (
            <div
              role="alert"
              className="mb-2 flex items-center gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
            >
              <span className="flex-1">{notice}</span>
              <button
                aria-label="关闭提示"
                className="rounded-md p-0.5 hover:bg-danger/10"
                onClick={onDismissNotice}
              >
                <X className="size-3.5" />
              </button>
            </div>
          )}
          <ComposerPrimitive.Root className="flex items-end gap-2 rounded-xl border border-border bg-card p-2 shadow-lg focus-within:border-ring">
            <ComposerPrimitive.Input
              autoFocus
              rows={1}
              placeholder="给智能体发消息…"
              className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 outline-none placeholder:text-muted-foreground"
            />
            <AuiIf condition={({ thread }) => !thread.isRunning}>
              <ComposerPrimitive.Send
                aria-label="发送"
                className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity disabled:opacity-30"
              >
                <ArrowUp className="size-4" />
              </ComposerPrimitive.Send>
            </AuiIf>
            <AuiIf condition={({ thread }) => thread.isRunning}>
              <ComposerPrimitive.Cancel
                aria-label="停止"
                className="flex size-9 items-center justify-center rounded-lg border border-border text-foreground transition-colors hover:bg-muted"
              >
                <Square className="size-3.5 fill-current" />
              </ComposerPrimitive.Cancel>
            </AuiIf>
          </ComposerPrimitive.Root>
        </div>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
```

改为：

```tsx
    <AssistantRuntimeProvider runtime={runtime}>
      <OpenFileContext value={onOpenFile}>
        <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
          <ThreadPrimitive.Viewport className="flex flex-1 flex-col overflow-y-auto">
            <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-8">
              <ThreadPrimitive.Empty>
                <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center text-muted-foreground">
                  <Sparkles className="size-8 text-warning" />
                  <p className="text-lg text-foreground">今天想做点什么？</p>
                  <p className="text-sm">输入问题开始对话，Enter 发送，Shift+Enter 换行</p>
                </div>
              </ThreadPrimitive.Empty>
              <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
            </div>
          </ThreadPrimitive.Viewport>
          <div className="mx-auto w-full max-w-3xl px-6 pb-6">
            {notice && (
              <div
                role="alert"
                className="mb-2 flex items-center gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
              >
                <span className="flex-1">{notice}</span>
                <button
                  aria-label="关闭提示"
                  className="rounded-md p-0.5 hover:bg-danger/10"
                  onClick={onDismissNotice}
                >
                  <X className="size-3.5" />
                </button>
              </div>
            )}
            <ComposerPrimitive.Root className="flex items-end gap-2 rounded-xl border border-border bg-card p-2 shadow-lg focus-within:border-ring">
              <ComposerPrimitive.Input
                autoFocus
                rows={1}
                placeholder="给智能体发消息…"
                className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 outline-none placeholder:text-muted-foreground"
              />
              <AuiIf condition={({ thread }) => !thread.isRunning}>
                <ComposerPrimitive.Send
                  aria-label="发送"
                  className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity disabled:opacity-30"
                >
                  <ArrowUp className="size-4" />
                </ComposerPrimitive.Send>
              </AuiIf>
              <AuiIf condition={({ thread }) => thread.isRunning}>
                <ComposerPrimitive.Cancel
                  aria-label="停止"
                  className="flex size-9 items-center justify-center rounded-lg border border-border text-foreground transition-colors hover:bg-muted"
                >
                  <Square className="size-3.5 fill-current" />
                </ComposerPrimitive.Cancel>
              </AuiIf>
            </ComposerPrimitive.Root>
          </div>
        </ThreadPrimitive.Root>
      </OpenFileContext>
    </AssistantRuntimeProvider>
```

新建 `frontend/src/features/files/FilePanel.tsx`：

```tsx
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileText, Image, LoaderCircle, Sheet, X } from "lucide-react";
import { readableError } from "../../api/client";
import { filesQuery } from "../../api/queries";
import type { WorkspaceFile } from "../../api/types";
import { fileName, formatSize } from "../../components/chat/format";
import { FilePreview } from "./FilePreview";
import { groupFiles, previewKind } from "./kind";

interface FilePanelProps {
  threadId: string;
  /** 正在预览的文件；null 时显示文件列表。 */
  selectedId: string | null;
  onSelect: (fileId: string | null) => void;
  onClose: () => void;
}

/** 右侧文件面板（设计文档 13.3）：本会话上传与生成的文件，点开即预览。 */
export function FilePanel({ threadId, selectedId, onSelect, onClose }: FilePanelProps) {
  const files = useQuery(filesQuery(threadId));
  const selected = files.data?.find((file) => file.id === selectedId) ?? null;
  return (
    <aside className="flex w-[28rem] shrink-0 flex-col border-l border-border bg-card/60">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        {selected ? (
          <button
            className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
            onClick={() => onSelect(null)}
          >
            <ArrowLeft className="size-4 shrink-0" />
            全部文件
          </button>
        ) : (
          <span className="font-medium">文件</span>
        )}
        <button
          aria-label="收起文件面板"
          className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          onClick={onClose}
        >
          <X className="size-4" />
        </button>
      </div>
      {files.isError ? (
        <p className="p-4 text-sm text-danger">文件列表加载失败：{readableError(files.error)}</p>
      ) : !files.data ? (
        <p className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" />
          加载中…
        </p>
      ) : selected ? (
        <FilePreview key={selected.id} file={selected} />
      ) : (
        <FileList files={files.data} onSelect={onSelect} />
      )}
    </aside>
  );
}

function FileList({
  files,
  onSelect,
}: {
  files: WorkspaceFile[];
  onSelect: (fileId: string) => void;
}) {
  if (files.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        还没有文件。上传的文件和智能体生成的文件都会出现在这里。
      </p>
    );
  }
  const { uploads, outputs } = groupFiles(files);
  return (
    <div className="flex-1 space-y-4 overflow-y-auto p-3">
      {[
        { title: "上传的文件", items: uploads },
        { title: "生成的文件", items: outputs },
      ]
        .filter((group) => group.items.length > 0)
        .map((group) => (
          <section key={group.title}>
            <h3 className="mb-1 px-2 text-xs text-muted-foreground">{group.title}</h3>
            <ul>
              {group.items.map((file) => (
                <li key={file.id}>
                  <button
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
                    title={file.path}
                    onClick={() => onSelect(file.id)}
                  >
                    <KindIcon file={file} />
                    <span className="truncate">{fileName(file.path)}</span>
                    <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                      {formatSize(file.size)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
    </div>
  );
}

function KindIcon({ file }: { file: WorkspaceFile }) {
  const kind = previewKind(file);
  const Icon = kind === "image" ? Image : kind === "table" ? Sheet : FileText;
  return <Icon className="size-4 shrink-0 text-muted-foreground" />;
}
```

新建 `frontend/src/features/files/FilePreview.tsx`：

```tsx
import { useQuery } from "@tanstack/react-query";
import { Download, ExternalLink, LoaderCircle } from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fileContentUrl, readableError } from "../../api/client";
import { fileTextQuery, tablePreviewQuery } from "../../api/queries";
import type { WorkspaceFile } from "../../api/types";
import { fileName, formatSize } from "../../components/chat/format";
import { previewKind } from "./kind";

const LINK_BUTTON = "rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground";

/**
 * 按类型预览一个文件（设计文档 9.3）：图片直接显示；CSV / Excel 显示前若干行；PDF 用浏览器阅读器；
 * Markdown 渲染；网页放在隔离的内嵌框里（不执行脚本）；文字原样显示；其他只能下载。
 */
export function FilePreview({ file }: { file: WorkspaceFile }) {
  const name = fileName(file.path);
  // 带上更新时间：同一文件被改写后（地址不变）浏览器不会用旧的缓存
  const src = `${fileContentUrl(file.thread_id, file.id, false)}?v=${encodeURIComponent(file.updated_at)}`;
  const kind = previewKind(file);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 px-4 py-2 text-sm">
        <span className="truncate font-medium" title={file.path}>
          {name}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">{formatSize(file.size)}</span>
        <span className="ml-auto flex shrink-0 gap-1">
          <a
            href={src}
            target="_blank"
            rel="noopener noreferrer"
            className={LINK_BUTTON}
            title="在新标签页打开"
          >
            <ExternalLink className="size-4" />
          </a>
          <a
            href={fileContentUrl(file.thread_id, file.id, true)}
            download={name}
            className={LINK_BUTTON}
            title="下载"
          >
            <Download className="size-4" />
          </a>
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-4 pb-4">
        {kind === "image" && (
          <img src={src} alt={name} className="max-w-full rounded-md bg-muted" />
        )}
        {kind === "pdf" && <iframe src={src} title={name} className="h-full w-full rounded-md" />}
        {kind === "html" && (
          // sandbox 不带 allow-scripts：智能体生成的网页里的脚本不执行
          <iframe src={src} title={name} sandbox="" className="h-full w-full rounded-md" />
        )}
        {kind === "table" && <TableView file={file} />}
        {(kind === "markdown" || kind === "text") && (
          <TextView file={file} markdown={kind === "markdown"} />
        )}
        {kind === "none" && (
          <p className="text-sm text-muted-foreground">这种文件不能在页面里预览，请下载后查看。</p>
        )}
      </div>
    </div>
  );
}

function TableView({ file }: { file: WorkspaceFile }) {
  const [sheet, setSheet] = useState<string | null>(null);
  const table = useQuery(tablePreviewQuery(file, sheet));
  if (table.isError) return <p className="text-sm text-danger">{readableError(table.error)}</p>;
  if (!table.data) return <Loading />;
  const [header, ...body] = table.data.rows;
  return (
    <div className="space-y-2 text-sm">
      {table.data.sheets.length > 1 && (
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="工作表">
          {table.data.sheets.map((name) => (
            <button
              key={name}
              role="tab"
              aria-selected={name === table.data.sheet}
              className="rounded-md border border-border px-2 py-0.5 text-xs aria-selected:bg-primary aria-selected:text-primary-foreground"
              onClick={() => setSheet(name)}
            >
              {name}
            </button>
          ))}
        </div>
      )}
      {header ? (
        <table className="w-full border-collapse font-mono text-xs">
          <thead>
            <tr>
              {header.map((cell, index) => (
                <th key={index} className="border border-border bg-muted px-2 py-1 text-left">
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, index) => (
                  <td key={index} className="border border-border px-2 py-1 whitespace-nowrap">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-muted-foreground">这张表是空的。</p>
      )}
      {table.data.truncated && (
        <p className="text-xs text-muted-foreground">
          只显示前 {table.data.rows.length} 行，完整内容请下载查看。
        </p>
      )}
    </div>
  );
}

function TextView({ file, markdown }: { file: WorkspaceFile; markdown: boolean }) {
  const text = useQuery(fileTextQuery(file));
  if (text.isError) return <p className="text-sm text-danger">{readableError(text.error)}</p>;
  if (text.data === undefined) return <Loading />;
  return markdown ? (
    <div className="markdown text-sm">
      <Markdown remarkPlugins={[remarkGfm]}>{text.data}</Markdown>
    </div>
  ) : (
    <pre className="font-mono text-xs whitespace-pre-wrap">{text.data}</pre>
  );
}

function Loading() {
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <LoaderCircle className="size-4 animate-spin" />
      加载中…
    </p>
  );
}
```

顶栏加"文件"按钮；收到 `file.created` 时刷新文件列表：

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, fileContentUrl, readableError } from "../../api/client";
import { subscribeRun } from "../../api/events";
import { historyQuery, recheckAccess, threadUsageQuery } from "../../api/queries";
import type { RunHistory, Thread } from "../../api/types";
import { ChatThread } from "../../components/chat";
import { ModelSelect } from "../models/ModelSelect";
```

改为：

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, fileContentUrl, readableError } from "../../api/client";
import { subscribeRun } from "../../api/events";
import { filesQuery, historyQuery, recheckAccess, threadUsageQuery } from "../../api/queries";
import type { RunHistory, Thread } from "../../api/types";
import { ChatThread } from "../../components/chat";
import { FilePanel } from "../files/FilePanel";
import { ModelSelect } from "../models/ModelSelect";
```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
  const stopWhenStarted = useRef(false);
  const fileUrl = useCallback(
```

改为：

```tsx
  const stopWhenStarted = useRef(false);
  // 右侧文件面板：是否展开、正在预览哪个文件（null 为文件列表）
  const [panel, setPanel] = useState<{ open: boolean; fileId: string | null }>({
    open: false,
    fileId: null,
  });
  const openFile = useCallback((fileId: string) => setPanel({ open: true, fileId }), []);
  const fileUrl = useCallback(
```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
      setState((current) => applyEvent(current, event));
      if (event.type === "run.finished") {
```

改为：

```tsx
      setState((current) => applyEvent(current, event));
      if (event.type === "file.created") {
        void queryClient.invalidateQueries({ queryKey: filesQuery(thread.id).queryKey });
      }
      if (event.type === "run.finished") {
```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
  return (
    <>
      <header className="flex items-center justify-between gap-4 border-b border-border px-6 py-3">
        <h1 className="truncate font-medium">{thread.title || "新会话"}</h1>
        <div className="flex shrink-0 items-center gap-4">
          <ThreadUsageBadge threadId={thread.id} />
          <ModelSelect value={model} onChange={setModel} />
        </div>
      </header>
      <ChatThread
        state={state}
        notice={notice}
        onDismissNotice={() => setNotice(null)}
        onSend={send}
        onCancel={cancel}
        fileUrl={fileUrl}
      />
    </>
  );
```

改为：

```tsx
  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-border px-6 py-3">
          <h1 className="truncate font-medium">{thread.title || "新会话"}</h1>
          <div className="flex shrink-0 items-center gap-4">
            <ThreadUsageBadge threadId={thread.id} />
            <ModelSelect value={model} onChange={setModel} />
            <button
              aria-pressed={panel.open}
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-muted-foreground hover:bg-muted hover:text-foreground aria-pressed:text-foreground"
              onClick={() => setPanel((current) => ({ open: !current.open, fileId: null }))}
            >
              <FolderOpen className="size-4" />
              文件
            </button>
          </div>
        </header>
        <ChatThread
          state={state}
          notice={notice}
          onDismissNotice={() => setNotice(null)}
          onSend={send}
          onCancel={cancel}
          fileUrl={fileUrl}
          onOpenFile={openFile}
        />
      </div>
      {panel.open && (
        <FilePanel
          threadId={thread.id}
          selectedId={panel.fileId}
          onSelect={(fileId) => setPanel({ open: true, fileId })}
          onClose={() => setPanel({ open: false, fileId: null })}
        />
      )}
    </div>
  );
```

- [ ] **步骤 7：检查点**

运行：`make check`

预期：全部通过（Python 单元测试 168 个、前端 76 个）。界面在任务 8 的浏览器验证里检查。

---

### 任务 6：上传与附件（前端）

**文件：**
- 新建：`frontend/src/features/chat/uploads.ts`、`uploads.test.ts`、`frontend/src/components/chat/uploads.tsx`
- 修改：`frontend/src/api/types.ts`、`client.ts`、`client.test.ts`、`frontend/src/features/chat/reducer.ts`、`reducer.test.ts`、`ChatView.tsx`、`frontend/src/components/chat/adapter.ts`、`adapter.test.ts`、`parts.tsx`、`ChatThread.tsx`

**接口：**
- 消费：任务 2 的上传接口、任务 3 的 `RunCreate.attachments` 与 `RunHistory.attachments`、任务 5 的 `OpenFileContext` 与 `filesQuery`。
- 产出（`api/`）：
  - 类型别名 `RunAttachment`；
  - `api.uploadFile(threadId, file: File) -> WorkspaceFile`；
  - `api.startRun(threadId, message, model, attachments: string[] = [])`：没有附件时请求体不带这个字段。
- 产出（`features/chat/uploads.ts`）：
  - `PendingUpload { key, name, size, status: "uploading" | "done" | "failed", file?, error? }`；
  - `startUpload`、`finishUpload`、`failUpload`、`removeUpload`；
  - `readyAttachments(list) -> WorkspaceFile[] | null`（还有文件在上传时为 null）。
- 产出（事件处理器）：
  - `ChatItem` 的用户项新增可选的 `attachments: RunAttachment[]`（没有附件时不带这个字段）；
  - `addUserMessage(state, id, text, attachments = [])`。
- 产出（`components/chat/`）：
  - `UserAttachment { fileId, name, size }`：用户消息的附件放在 `metadata.custom.attachments`；
  - `ChatThread` 新增必填属性 `uploads`、`onAddFiles(files)`、`onRemoveUpload(key)`；
  - `AttachButton`、`UploadChips`。

- [ ] **步骤 1：写失败的测试**

新建 `frontend/src/features/chat/uploads.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import type { WorkspaceFile } from "../../api/types";
import { failUpload, finishUpload, readyAttachments, removeUpload, startUpload } from "./uploads";

const record = (id: string): WorkspaceFile => ({
  id,
  thread_id: "t1",
  path: `uploads/${id}.csv`,
  source: "upload",
  media_type: "text/csv",
  size: 3,
  created_at: "2026-10-15T00:00:00Z",
  updated_at: "2026-10-15T00:00:00Z",
});

describe("输入框上方待发送的文件", () => {
  it("选中即开始上传；完成、失败按各自的标识更新，同名文件互不影响", () => {
    let list = startUpload([], "k1", "a.csv", 3);
    list = startUpload(list, "k2", "a.csv", 5);
    list = finishUpload(list, "k1", record("f1"));
    list = failUpload(list, "k2", "文件超过 100MB 上限");
    expect(list).toEqual([
      { key: "k1", name: "a.csv", size: 3, status: "done", file: record("f1") },
      { key: "k2", name: "a.csv", size: 5, status: "failed", error: "文件超过 100MB 上限" },
    ]);
    expect(removeUpload(list, "k2").map((item) => item.key)).toEqual(["k1"]);
  });

  it("发送时只带上传完成的文件；还有文件在上传时要等它传完", () => {
    let list = startUpload([], "k1", "a.csv", 3);
    expect(readyAttachments(list)).toBeNull();
    list = finishUpload(list, "k1", record("f1"));
    list = failUpload(startUpload(list, "k2", "b.csv", 3), "k2", "上传失败");
    expect(readyAttachments(list)).toEqual([record("f1")]);
    expect(readyAttachments([])).toEqual([]);
  });
});
```

在 `frontend/src/features/chat/reducer.test.ts` 末尾追加：

```ts

describe("用户消息的附件", () => {
  const attachment = { id: "f1", path: "uploads/a.csv", media_type: "text/csv", size: 3 };

  it("发送时带上附件；界面历史里的附件同样显示", () => {
    expect(addUserMessage(emptyChat, "u1", "看看", [attachment]).items).toEqual([
      { kind: "user", id: "u1", text: "看看", attachments: [attachment] },
    ]);
    const runs: RunHistory[] = [
      {
        id: "r1",
        thread_id: "t1",
        status: "completed",
        model: "m",
        message: "看看",
        attachments: [attachment],
        error: null,
        created_at: "2026-10-15T00:00:00Z",
        events: [],
      },
    ];
    expect(chatFromHistory(runs).items).toEqual([
      { kind: "user", id: "user-r1", text: "看看", attachments: [attachment] },
    ]);
  });
});
```

在 `frontend/src/components/chat/adapter.test.ts` 末尾追加：

```ts

describe("用户消息的附件", () => {
  it("放进消息的自定义信息，显示为可点开的文件标签", () => {
    const state: ChatState = {
      running: false,
      items: [
        {
          kind: "user",
          id: "u1",
          text: "看看",
          attachments: [{ id: "f1", path: "uploads/销售.csv", media_type: "text/csv", size: 3 }],
        },
      ],
    };
    const [user] = toThreadMessages(state, fileUrl);
    expect(user?.metadata?.custom).toEqual({
      attachments: [{ fileId: "f1", name: "销售.csv", size: 3 }],
    });
  });
});
```

在 `frontend/src/api/client.test.ts` 末尾追加：

```ts

describe("上传与附件", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("上传：请求体就是文件，文件名编码后放在 X-File-Name 请求头", async () => {
    const fetchMock = vi.fn(async () => Response.json({ id: "f1" }, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["a,b"], "销售 数据.csv", { type: "text/csv" });
    await expect(api.uploadFile("t1", file)).resolves.toEqual({ id: "f1" });
    expect(fetchMock).toHaveBeenCalledWith("/api/threads/t1/files", {
      method: "POST",
      body: file,
      headers: {
        "Content-Type": "text/csv",
        "X-File-Name": "%E9%94%80%E5%94%AE%20%E6%95%B0%E6%8D%AE.csv",
      },
    });
    await api.uploadFile("t1", new File(["x"], "data"));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/threads/t1/files",
      expect.objectContaining({
        headers: { "Content-Type": "application/octet-stream", "X-File-Name": "data" },
      }),
    );
  });

  it("发消息时带上附件的文件 ID", async () => {
    const fetchMock = vi.fn(async () => Response.json({ id: "r1" }, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.startRun("t1", "看看", "m", ["f1"]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/threads/t1/runs",
      expect.objectContaining({
        body: JSON.stringify({ message: "看看", model: "m", attachments: ["f1"] }),
      }),
    );
  });
});
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && pnpm exec vitest run`（预期失败）

预期：
- `uploads.test.ts` 找不到 `./uploads`；
- `api.uploadFile is not a function`；
- 发消息的请求体里没有 `attachments`；
- 用户消息没有带上附件；
- 共 4 个测试失败、1 个测试文件无法加载。

- [ ] **步骤 3：实现数据层**

新建 `frontend/src/features/chat/uploads.ts`：

```ts
import type { WorkspaceFile } from "../../api/types";

/** 输入框上方待发送的文件：选中后立即上传，上传完成的随下一条消息作为附件发出。 */
export interface PendingUpload {
  key: string; // 页面生成，区分同名文件
  name: string;
  size: number;
  status: "uploading" | "done" | "failed";
  file?: WorkspaceFile; // 上传完成后的登记信息
  error?: string;
}

export function startUpload(
  list: PendingUpload[],
  key: string,
  name: string,
  size: number,
): PendingUpload[] {
  return [...list, { key, name, size, status: "uploading" }];
}

export function finishUpload(
  list: PendingUpload[],
  key: string,
  file: WorkspaceFile,
): PendingUpload[] {
  return list.map((item) => (item.key === key ? { ...item, status: "done", file } : item));
}

export function failUpload(list: PendingUpload[], key: string, error: string): PendingUpload[] {
  return list.map((item) => (item.key === key ? { ...item, status: "failed", error } : item));
}

export function removeUpload(list: PendingUpload[], key: string): PendingUpload[] {
  return list.filter((item) => item.key !== key);
}

/** 发送时附带的文件（上传失败的不带）；还有文件在上传时返回 null，要等它传完。 */
export function readyAttachments(list: PendingUpload[]): WorkspaceFile[] | null {
  if (list.some((item) => item.status === "uploading")) return null;
  return list.flatMap((item) => (item.file ? [item.file] : []));
}
```

在 `frontend/src/api/types.ts` 中，把：

```ts
export type RunRecord = Schemas["RunRecord"];
export type UsageTotals = Schemas["UsageTotals"];
```

改为：

```ts
export type RunRecord = Schemas["RunRecord"];
export type RunAttachment = Schemas["RunAttachment"];
export type UsageTotals = Schemas["UsageTotals"];
```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
  InterruptedUsage,
  RunHistory,
```

改为：

```ts
  InterruptedUsage,
  RunAttachment,
  RunHistory,
```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
export type ChatItem =
  | { kind: "user"; id: string; text: string }
  | { kind: "assistant"; id: string; text: string }
```

改为：

```ts
export type ChatItem =
  // attachments：随这条消息发出的文件（没有附件时不带这个字段）
  | { kind: "user"; id: string; text: string; attachments?: RunAttachment[] }
  | { kind: "assistant"; id: string; text: string }
```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts

export function addUserMessage(state: ChatState, id: string, text: string): ChatState {
  return { ...state, items: [...state.items, { kind: "user", id, text }] };
}
```

改为：

```ts

export function addUserMessage(
  state: ChatState,
  id: string,
  text: string,
  attachments: RunAttachment[] = [],
): ChatState {
  const item: ChatItem =
    attachments.length > 0 ? { kind: "user", id, text, attachments } : { kind: "user", id, text };
  return { ...state, items: [...state.items, item] };
}
```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
      applyEvent,
      addUserMessage(state, `user-${run.id}`, run.message),
    );
```

改为：

```ts
      applyEvent,
      addUserMessage(state, `user-${run.id}`, run.message, run.attachments),
    );
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
  return status === "running" && !active ? "interrupted" : status;
}
```

改为：

```ts
  return status === "running" && !active ? "interrupted" : status;
}

/** 用户消息下方的附件标签（点开在文件面板里预览）。 */
export interface UserAttachment {
  fileId: string;
  name: string;
  size: number;
}
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
    if (first?.kind === "user") {
      return { id: first.id, role: "user", content: [{ type: "text", text: first.text }] };
    }
```

改为：

```ts
    if (first?.kind === "user") {
      const attachments: UserAttachment[] = (first.attachments ?? []).map((file) => ({
        fileId: file.id,
        name: fileName(file.path),
        size: file.size,
      }));
      return {
        id: first.id,
        role: "user",
        content: [{ type: "text", text: first.text }],
        ...(attachments.length > 0 ? { metadata: { custom: { attachments } } } : {}),
      };
    }
```

在 `frontend/src/api/client.ts` 中，把：

```ts
  listModels: () => request<ModelInfo[]>("/models"),
  startRun: (threadId: string, message: string, model: string) =>
    request<RunRecord>(`/threads/${threadId}/runs`, {
      method: "POST",
      body: JSON.stringify({ message, model }),
    }),
```

改为：

```ts
  listModels: () => request<ModelInfo[]>("/models"),
  /** attachments：随消息发出的文件（已上传到本会话的文件 ID）。 */
  startRun: (threadId: string, message: string, model: string, attachments: string[] = []) =>
    request<RunRecord>(`/threads/${threadId}/runs`, {
      method: "POST",
      body: JSON.stringify(
        attachments.length > 0 ? { message, model, attachments } : { message, model },
      ),
    }),
  /**
   * 上传文件到会话的 uploads/：请求体就是文件本身，文件名编码后放在 X-File-Name 请求头
   * （自定义请求头也让跨站网页无法直接伪造上传，设计文档 12.2）。
   */
  uploadFile: (threadId: string, file: File) =>
    request<WorkspaceFile>(`/threads/${threadId}/files`, {
      method: "POST",
      body: file,
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-File-Name": encodeURIComponent(file.name),
      },
    }),
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`cd frontend && pnpm exec vitest run`

预期：全部通过（82 个）。

- [ ] **步骤 5：界面**

附件按钮与输入框上方的文件标签（独立成文件，`ChatThread.tsx` 不至于太长）：

新建 `frontend/src/components/chat/uploads.tsx`：

```tsx
import { LoaderCircle, Paperclip, TriangleAlert, X } from "lucide-react";
import { useRef } from "react";
import type { PendingUpload } from "../../features/chat/uploads";
import { formatSize } from "./format";

/** 输入框里的"添加附件"按钮：可一次选多个文件。 */
export function AttachButton({ onAddFiles }: { onAddFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <button
        type="button"
        aria-label="添加附件"
        title="添加附件（也可以把文件拖进对话区）"
        className="flex size-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
        onClick={() => input.current?.click()}
      >
        <Paperclip className="size-4" />
      </button>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        onChange={(event) => {
          onAddFiles([...(event.target.files ?? [])]);
          event.target.value = ""; // 同一个文件可以再选一次
        }}
      />
    </>
  );
}

/** 输入框上方待发送的文件：上传中转圈，失败显示原因，都可以移除。 */
export function UploadChips({
  uploads,
  onRemove,
}: {
  uploads: PendingUpload[];
  onRemove: (key: string) => void;
}) {
  if (uploads.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1.5 px-1 pb-1">
      {uploads.map((upload) => (
        <li
          key={upload.key}
          title={upload.error ?? upload.name}
          className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs ${
            upload.status === "failed" ? "border-danger/40 text-danger" : "border-border"
          }`}
        >
          {upload.status === "uploading" && <LoaderCircle className="size-3.5 animate-spin" />}
          {upload.status === "failed" && <TriangleAlert className="size-3.5" />}
          {upload.status === "done" && <Paperclip className="size-3.5 text-muted-foreground" />}
          <span className="max-w-48 truncate">{upload.name}</span>
          <span className="text-muted-foreground">
            {upload.status === "failed" ? upload.error : formatSize(upload.size)}
          </span>
          <button
            type="button"
            aria-label={`移除 ${upload.name}`}
            className="rounded p-0.5 hover:bg-muted"
            onClick={() => onRemove(upload.key)}
          >
            <X className="size-3" />
          </button>
        </li>
      ))}
    </ul>
  );
}
```

对话区可以拖放文件；输入框上方显示待发送的文件：

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
} from "@assistant-ui/react";
import { ArrowUp, Sparkles, Square, X } from "lucide-react";
import { useMemo } from "react";
import type { ChatState } from "../../features/chat/reducer";
import { toThreadMessages, type FileUrl } from "./adapter";
import { OpenFileContext } from "./fileActions";
import { AssistantMessage, UserMessage } from "./parts";
```

改为：

```tsx
} from "@assistant-ui/react";
import { ArrowUp, Sparkles, Square, Upload, X } from "lucide-react";
import { useMemo, useState, type DragEvent } from "react";
import type { ChatState } from "../../features/chat/reducer";
import type { PendingUpload } from "../../features/chat/uploads";
import { toThreadMessages, type FileUrl } from "./adapter";
import { OpenFileContext } from "./fileActions";
import { AttachButton, UploadChips } from "./uploads";
import { AssistantMessage, UserMessage } from "./parts";
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
  onOpenFile: (fileId: string) => void;
}

```

改为：

```tsx
  onOpenFile: (fileId: string) => void;
  /** 输入框上方待发送的文件；选中或拖进来的文件交给 onAddFiles 上传。 */
  uploads: PendingUpload[];
  onAddFiles: (files: File[]) => void;
  onRemoveUpload: (key: string) => void;
}

const hasFiles = (event: DragEvent) => event.dataTransfer.types.includes("Files");

```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
  onOpenFile,
}: ChatThreadProps) {
  // 只在状态变化时重新转换：assistant-ui 按消息对象是否相同决定是否重新处理
```

改为：

```tsx
  onOpenFile,
  uploads,
  onAddFiles,
  onRemoveUpload,
}: ChatThreadProps) {
  const [dragging, setDragging] = useState(false);
  // 只在状态变化时重新转换：assistant-ui 按消息对象是否相同决定是否重新处理
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
      <OpenFileContext value={onOpenFile}>
        <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
          <ThreadPrimitive.Viewport className="flex flex-1 flex-col overflow-y-auto">
```

改为：

```tsx
      <OpenFileContext value={onOpenFile}>
        <ThreadPrimitive.Root
          className="relative flex min-h-0 flex-1 flex-col"
          onDragOver={(event) => {
            if (!hasFiles(event)) return;
            event.preventDefault(); // 允许放下
            setDragging(true);
          }}
          onDragLeave={(event) => {
            // 移到对话区里的子元素上也会触发：只在真正离开对话区时收起提示
            if (!event.currentTarget.contains(event.relatedTarget as Node | null))
              setDragging(false);
          }}
          onDrop={(event) => {
            if (!hasFiles(event)) return;
            event.preventDefault();
            setDragging(false);
            onAddFiles([...event.dataTransfer.files]);
          }}
        >
          {dragging && (
            <div className="pointer-events-none absolute inset-2 z-10 flex items-center justify-center gap-2 rounded-xl border-2 border-dashed border-primary/60 bg-background/80 text-foreground">
              <Upload className="size-5" />
              松开即可上传
            </div>
          )}
          <ThreadPrimitive.Viewport className="flex flex-1 flex-col overflow-y-auto">
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
            )}
            <ComposerPrimitive.Root className="flex items-end gap-2 rounded-xl border border-border bg-card p-2 shadow-lg focus-within:border-ring">
              <ComposerPrimitive.Input
                autoFocus
                rows={1}
                placeholder="给智能体发消息…"
                className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 outline-none placeholder:text-muted-foreground"
              />
              <AuiIf condition={({ thread }) => !thread.isRunning}>
                <ComposerPrimitive.Send
                  aria-label="发送"
                  className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity disabled:opacity-30"
                >
                  <ArrowUp className="size-4" />
                </ComposerPrimitive.Send>
              </AuiIf>
              <AuiIf condition={({ thread }) => thread.isRunning}>
                <ComposerPrimitive.Cancel
                  aria-label="停止"
                  className="flex size-9 items-center justify-center rounded-lg border border-border text-foreground transition-colors hover:bg-muted"
                >
                  <Square className="size-3.5 fill-current" />
                </ComposerPrimitive.Cancel>
              </AuiIf>
            </ComposerPrimitive.Root>
```

改为：

```tsx
            )}
            <ComposerPrimitive.Root className="rounded-xl border border-border bg-card p-2 shadow-lg focus-within:border-ring">
              <UploadChips uploads={uploads} onRemove={onRemoveUpload} />
              <div className="flex items-end gap-2">
                <AttachButton onAddFiles={onAddFiles} />
                <ComposerPrimitive.Input
                  autoFocus
                  rows={1}
                  placeholder="给智能体发消息…"
                  className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 outline-none placeholder:text-muted-foreground"
                />
                <AuiIf condition={({ thread }) => !thread.isRunning}>
                  <ComposerPrimitive.Send
                    aria-label="发送"
                    className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity disabled:opacity-30"
                  >
                    <ArrowUp className="size-4" />
                  </ComposerPrimitive.Send>
                </AuiIf>
                <AuiIf condition={({ thread }) => thread.isRunning}>
                  <ComposerPrimitive.Cancel
                    aria-label="停止"
                    className="flex size-9 items-center justify-center rounded-lg border border-border text-foreground transition-colors hover:bg-muted"
                  >
                    <Square className="size-3.5 fill-current" />
                  </ComposerPrimitive.Cancel>
                </AuiIf>
              </div>
            </ComposerPrimitive.Root>
```

用户消息下方显示附件标签，点开在面板里预览：

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
  LoaderCircle,
  Timer,
```

改为：

```tsx
  LoaderCircle,
  Paperclip,
  Timer,
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
  type TurnUsage,
} from "./adapter";
```

改为：

```tsx
  type TurnUsage,
  type UserAttachment,
} from "./adapter";
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
/** 用户消息：气泡底色就是主色，全局选中色（主色半透明）在上面看不出来，所以这里用反色高亮。 */
export const UserMessage = () => (
```

改为：

```tsx
/** 用户消息：气泡底色就是主色，全局选中色（主色半透明）在上面看不出来，所以这里用反色高亮。 */
/** 用户消息下方的附件标签：点开在文件面板里预览。 */
function UserAttachments() {
  const custom = useAuiState(({ message }) => message.metadata.custom);
  const openFile = useContext(OpenFileContext);
  const attachments = custom.attachments as UserAttachment[] | undefined;
  if (!attachments?.length) return null;
  return (
    <div className="mt-1 flex max-w-[80%] flex-wrap justify-end gap-1">
      {attachments.map((file) => (
        <button
          key={file.fileId}
          className="flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs hover:bg-muted"
          title="在文件面板里预览"
          onClick={() => openFile(file.fileId)}
        >
          <Paperclip className="size-3.5 text-muted-foreground" />
          <span className="max-w-48 truncate">{file.name}</span>
          <span className="text-muted-foreground">{formatSize(file.size)}</span>
        </button>
      ))}
    </div>
  );
}

export const UserMessage = () => (
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
    </div>
    <ActionBarPrimitive.Root className="mt-1 flex gap-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
```

改为：

```tsx
    </div>
    <UserAttachments />
    <ActionBarPrimitive.Root className="mt-1 flex gap-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
```

选中即上传；发送时还有文件在上传则提示稍候；发出去的文件从输入框上方移走：

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
} from "./reducer";

```

改为：

```tsx
} from "./reducer";
import {
  failUpload,
  finishUpload,
  readyAttachments,
  removeUpload,
  startUpload,
  type PendingUpload,
} from "./uploads";

```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
  const stopWhenStarted = useRef(false);
  // 右侧文件面板：是否展开、正在预览哪个文件（null 为文件列表）
```

改为：

```tsx
  const stopWhenStarted = useRef(false);
  // 输入框上方待发送的文件。标识用计数器生成（crypto.randomUUID 在局域网的 http 页面里不可用）
  const [uploads, setUploads] = useState<PendingUpload[]>([]);
  const uploadSeq = useRef(0);
  // 右侧文件面板：是否展开、正在预览哪个文件（null 为文件列表）
```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
  /** 发送成功返回 true；失败时撤回乐观显示的消息并提示原因，返回 false 让输入框恢复原文。 */
  const send = async (text: string): Promise<boolean> => {
    const userId = `user-${Date.now()}`;
    setNotice(null);
    stopWhenStarted.current = false;
    setState((current) => ({ ...addUserMessage(current, userId, text), running: true }));
    try {
      const run = await api.startRun(thread.id, text, model);
      setActive({ id: run.id, afterSeq: 0 });
```

改为：

```tsx
  /** 发送成功返回 true；失败时撤回乐观显示的消息并提示原因，返回 false 让输入框恢复原文。 */
  /** 选中或拖进来的文件：立即上传，完成后刷新文件面板。 */
  const addFiles = (files: File[]): void => {
    for (const file of files) {
      uploadSeq.current += 1;
      const key = `upload-${uploadSeq.current}`;
      setUploads((current) => startUpload(current, key, file.name, file.size));
      api.uploadFile(thread.id, file).then(
        (record) => {
          setUploads((current) => finishUpload(current, key, record));
          void queryClient.invalidateQueries({ queryKey: filesQuery(thread.id).queryKey });
        },
        (error: unknown) => {
          setUploads((current) => failUpload(current, key, readableError(error)));
          recheckAccess(queryClient, error);
        },
      );
    }
  };

  const send = async (text: string): Promise<boolean> => {
    const files = readyAttachments(uploads);
    if (files === null) {
      setNotice("文件还在上传，请等上传完成再发送");
      return false;
    }
    const attachments = files.map(({ id, path, media_type, size }) => ({
      id,
      path,
      media_type,
      size,
    }));
    const userId = `user-${Date.now()}`;
    setNotice(null);
    stopWhenStarted.current = false;
    setState((current) => ({
      ...addUserMessage(current, userId, text, attachments),
      running: true,
    }));
    try {
      const run = await api.startRun(
        thread.id,
        text,
        model,
        files.map((file) => file.id),
      );
      // 发出的文件从输入框上方移走（发送途中新加的、失败的留着）
      const sent = new Set(files.map((file) => file.id));
      setUploads((current) => current.filter((item) => !item.file || !sent.has(item.file.id)));
      setActive({ id: run.id, afterSeq: 0 });
```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
          onOpenFile={openFile}
        />
```

改为：

```tsx
          onOpenFile={openFile}
          uploads={uploads}
          onAddFiles={addFiles}
          onRemoveUpload={(key) => setUploads((current) => removeUpload(current, key))}
        />
```

- [ ] **步骤 6：检查点**

运行：`make check`

预期：全部通过（Python 单元测试 168 个、前端 82 个）。

---

### 任务 7：回答下方的复制按钮（用户追加）

用户 2026-10-15 追加：每轮回答下方的复制按钮挪到"耗时 · 输入 · 输出 · 费用"那一行的末尾，一直显示，不用鼠标移上去才出现。

**文件：**
- 修改：`frontend/src/components/chat/parts.tsx`

**接口：**
- 无新增接口。`AssistantFooter` 末尾放复制按钮（`ActionBarPrimitive.Root hideWhenRunning` 包着 `ActionBarPrimitive.Copy`）：
  - 回答进行中隐藏；
  - 没有用量信息的回答（如服务重启中断）这一行只有复制按钮；
  - 原来回答下方单独一行、鼠标移上去才出现的复制按钮删掉。
- 用户消息下方的复制按钮不变。

- [ ] **步骤 1：改界面**

纯展示改动（项目的前端单元测试只覆盖纯逻辑），在任务 8 的浏览器验证里检查。顺带删掉 `ElapsedTime` 上方一行放错位置的旧注释：

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx

/** 回答下方：已停止标记与本轮用量（可展开每次调用明细）。 */
/** 运行中的已用时间，每秒刷新。 */
```

改为：

```tsx

/** 运行中的已用时间，每秒刷新。 */
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx

function AssistantFooter() {
```

改为：

```tsx

/**
 * 回答下方的一行：耗时、已停止、被中断调用的估算、本轮用量（可展开明细），末尾是复制按钮。
 * 复制按钮一直显示（不用鼠标移上去才出现），只在回答进行中隐藏。
 */
function AssistantFooter() {
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
  const timing = custom.timing as TurnTiming | undefined;
  if (!usage && !stopped && !interrupted && !timing) return null;
  return (
```

改为：

```tsx
  const timing = custom.timing as TurnTiming | undefined;
  return (
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
      )}
    </div>
```

改为：

```tsx
      )}
      <ActionBarPrimitive.Root hideWhenRunning className="flex">
        <ActionBarPrimitive.Copy
          className="-my-1 rounded-md p-1 hover:bg-muted hover:text-foreground"
          aria-label="复制"
          title="复制回答"
        >
          <Copy className="size-3.5" />
        </ActionBarPrimitive.Copy>
      </ActionBarPrimitive.Root>
    </div>
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
    <AssistantFooter />
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="mt-1 flex gap-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100"
    >
      <ActionBarPrimitive.Copy
        className="rounded-md p-1 hover:bg-muted hover:text-foreground"
        aria-label="复制"
      >
        <Copy className="size-3.5" />
      </ActionBarPrimitive.Copy>
    </ActionBarPrimitive.Root>
  </MessagePrimitive.Root>
```

改为：

```tsx
    <AssistantFooter />
  </MessagePrimitive.Root>
```

- [ ] **步骤 2：检查点**

运行：`make check`

预期：全部通过（Python 单元测试 168 个、前端 82 个）。

---

### 任务 8：文档收尾与端到端验证

**文件：**
- 修改：`docs/development/architecture.md`、`README.md`、`docs/requirements/backlog.md`、`docs/changelog.md`

- [ ] **步骤 1：架构规范与 README**

架构规范第 10 节补上上传、附件与预览（新增约定 8～10）；第 11 节约定 2 改为上传接口已落实的做法：

在 `docs/development/architecture.md` 中，把：

````markdown
写文件或执行命令之后 → 检查 outputs/ 的新增或改动 → file.created 事件 → 产物卡片
```
````

改为：

````markdown
写文件或执行命令之后 → 检查 outputs/ 的新增或改动 → file.created 事件 → 产物卡片
用户上传 → POST /api/threads/{id}/files（请求体就是文件）→ uploads/ → 随下一条消息作为附件交给智能体
文件面板 → GET /api/threads/{id}/files（列表）→ 按类型预览（表格走 …/table，其余直接读 …/content）
```
````

在 `docs/development/architecture.md` 中，把：

```markdown
| `agents/main_agent/runtime/files.py` | 智能体看到的文件树：`/workspace/`（工作区）、`/skills/`（技能，只读）、`/.agent/`（大段工具输出的转存，存在对话存档里） |
| `deploy/sandbox/` | 沙箱镜像：执行服务、预装库的锁定文件（`make sandbox-lock` 生成）、中文字体配置 |
```

改为：

```markdown
| `agents/main_agent/runtime/files.py` | 智能体看到的文件树：`/workspace/`（工作区）、`/skills/`（技能，只读）、`/.agent/`（大段工具输出的转存，存在对话存档里） |
| `agents/main_agent/workspace/media.py` | 按文件名判断类型：只用 Python 自带的表并补上 Office、Markdown 等常用格式，本机与容器里结果一致 |
| `agents/main_agent/runtime/attachments.py` | 消息附带的文件交给模型：注明文件位置；能看图的模型同时收到图片本身 |
| `backend/files/preview.py` | 表格预览：CSV / Excel 的前若干行，单元格一律转成文字 |
| `frontend/src/features/files/` | 右侧文件面板与各类预览（`kind.ts` 按类型选择预览方式） |
| `frontend/src/features/chat/uploads.ts` | 输入框上方待发送的文件（上传中、完成、失败） |
| `deploy/sandbox/` | 沙箱镜像：执行服务、预装库的锁定文件（`make sandbox-lock` 生成）、中文字体配置 |
```

在 `docs/development/architecture.md` 中，把：

```markdown
5. **产物**：只看 `outputs/`。backend 收到 `file.created` 时直接算出文件 ID 填进事件再推送，登记在后台完成（处理事件的循环里不能有真正的等待，见第 9 节约定 2）；收尾时等登记写完再推送结束事件，前端收到后即可下载。
6. **下载**：先核对文件属于该会话（不属于时返回 404），再按登记的路径读取；响应带 `Content-Security-Policy: sandbox` 与 `X-Content-Type-Options: nosniff`，智能体生成的 HTML / SVG 直接打开时不执行脚本。
7. **改了沙箱**：`deploy/sandbox/` 下的执行服务或依赖改了以后运行 `make build`；改依赖先改 `requirements.in` 再运行 `make sandbox-lock`。

```

改为：

```markdown
5. **产物**：只看 `outputs/`。backend 收到 `file.created` 时直接算出文件 ID 填进事件再推送，登记在后台完成（处理事件的循环里不能有真正的等待，见第 9 节约定 2）；收尾时等登记写完再推送结束事件，前端收到后即可下载。
6. **下载**：先核对文件属于该会话（不属于时返回 404），再按登记的路径边读边传（`Workspace.open_file`）；文件被删除、换成目录或换成指向会话目录外的链接时返回 404"文件已不存在"。响应带 `Content-Security-Policy: sandbox` 与 `X-Content-Type-Options: nosniff`，智能体生成的 HTML / SVG 直接打开时不执行脚本。
7. **改了沙箱**：`deploy/sandbox/` 下的执行服务或依赖改了以后运行 `make build`；改依赖先改 `requirements.in` 再运行 `make sandbox-lock`。
8. **上传**：`POST /api/threads/{id}/files`，请求体就是文件本身，文件名按 UTF-8 百分号编码放在 `X-File-Name` 请求头（这个自定义请求头同时满足第 11 节约定 2）。单个文件上限 `config/app.yaml` 的 `workspace.max_upload_mb`（默认 100MB）：请求头声明的长度超限时立即拒绝，传输中超限时删掉已写的部分，都返回 413。只保留文件名本身（去掉目录部分、控制字符和开头的点），同名时加序号，不覆盖已有文件；登记为来源 `upload`。
9. **附件**：发消息时 `attachments` 带上本会话已上传文件的 ID（最多 10 个，别的会话的文件返回 404），运行记录的 `input` 里存一份（`{"message", "attachments"}`），界面历史据此在用户消息下显示附件。交给模型时在消息末尾注明文件位置；当前模型能看图（网关的模型信息，不知道时按不能处理）时，PNG / JPEG / GIF / WebP 且不超过 5MB 的图片同时作为图片内容发出。同一会话换到不能看图的模型时，换模型清理中间件把历史里的图片换成一句说明（对话存档不变）。
10. **预览**：前端按类型选择预览方式（`features/files/kind.ts`）。表格走 `GET …/files/{fid}/table?sheet=`：只读不超过 20MB 的文件，取前 100 行、50 列，CSV 依次按 UTF-8（可带 BOM）、GB18030 解码。网页放在不允许脚本的内嵌框里（Claude 的内置浏览器会拦截这类内嵌框，要在普通浏览器里验证）；超过 1MB 的文字文件不在页面里显示。预览地址带 `?v=<更新时间>`，同一文件被改写后不会显示浏览器缓存的旧内容。

```

在 `docs/development/architecture.md` 中，把：

```markdown
1. 不开启跨域（CORS）：前端与接口同源（开发时经 Vite 转发），跨站网页读不到任何接口结果。
2. 新增接口无需额外处理；新增**文件上传**接口（M2）时，额外要求一个自定义请求头（表单上传是"简单请求"，不受第 3 条约束）。
3. 前端遇到 401 显示令牌页（`features/auth/AccessTokenGate.tsx`），提交后服务器写入只供服务器读取的 Cookie（存的是由令牌派生的值，不是令牌原文），推送连接（EventSource）也自动带上。页面打开后后端才设令牌时，发送、停止与各种修改操作遇到 401 会重新加载会话列表（`recheckAccess`），页面随之切到令牌页。
```

改为：

```markdown
1. 不开启跨域（CORS）：前端与接口同源（开发时经 Vite 转发），跨站网页读不到任何接口结果。
2. 新增接口无需额外处理。**文件上传**接口的请求体是文件本身（不是 JSON），改为要求自定义请求头 `X-File-Name`，同样迫使跨站请求先预检（表单上传是"简单请求"，不受第 3 条约束）。
3. 前端遇到 401 显示令牌页（`features/auth/AccessTokenGate.tsx`），提交后服务器写入只供服务器读取的 Cookie（存的是由令牌派生的值，不是令牌原文），推送连接（EventSource）也自动带上。页面打开后后端才设令牌时，发送、停止与各种修改操作遇到 401 会重新加载会话列表（`recheckAccess`），页面随之切到令牌页。
```

在 `README.md` 中，把：

```markdown

`make up` 只在第一次（还没有镜像时）构建镜像，之后直接启动。改了东西后：
```

改为：

```markdown

上传文件：点输入框左边的回形针，或把文件拖进对话区（单个文件上限 100MB，见 `config/app.yaml` 的 `workspace.max_upload_mb`），文件随下一条消息交给智能体；能看图的模型会直接看到上传的图片。点顶栏的"文件"打开右侧文件面板，可预览图片、CSV / Excel、PDF、Markdown、网页与代码。

`make up` 只在第一次（还没有镜像时）构建镜像，之后直接启动。改了东西后：
```

- [ ] **步骤 2：需求池与变更记录**

在 `docs/requirements/backlog.md` 中，把：

```markdown
| R05a | 沙箱镜像与执行服务、每个会话隔离的工作目录、执行代码（停止时连同子进程结束）、智能体技能与数据分析员子智能体、产物检测与产物卡片（可打开 / 下载）、删除会话时清理工作目录 | M2a | 高 | 完成 |
| R05b | 文件上传、右侧文件面板、预览（图片 / CSV / Excel / PDF / Markdown / HTML）、图片发给能看图的模型 | M2b | 高 | 计划 |
| R06 | 统一知识库（文档 + 记忆 + 常驻条目） | M3 | 高 | 计划 |
```

改为：

```markdown
| R05a | 沙箱镜像与执行服务、每个会话隔离的工作目录、执行代码（停止时连同子进程结束）、智能体技能与数据分析员子智能体、产物检测与产物卡片（可打开 / 下载）、删除会话时清理工作目录 | M2a | 高 | 完成 |
| R05b | 文件上传、右侧文件面板、预览（图片 / CSV / Excel / PDF / Markdown / HTML）、图片发给能看图的模型；M2a 延后的下载、文件类型等小问题 | M2b | 高 | 完成 |
| R06 | 统一知识库（文档 + 记忆 + 常驻条目） | M3 | 高 | 计划 |
```

在 `docs/changelog.md` 中，把：

```markdown
## 未发布

```

改为：

```markdown
## 未发布

### M2b 文件上传与预览（完成）

- 新增：上传文件（设计文档 9.3）——点输入框左边的回形针或把文件拖进对话区，选中即开始上传，输入框上方显示上传中 / 完成 / 失败，可移除；单个文件上限 100MB（`config/app.yaml` 的 `workspace.max_upload_mb`）。文件存到会话目录的 `uploads/`（只保留文件名本身，同名时加序号），登记为来源"上传"。接口 `POST /api/threads/{id}/files`（请求体就是文件，文件名放在 `X-File-Name` 请求头）、`GET /api/threads/{id}/files`。
- 新增：附件随消息交给智能体——消息末尾注明文件位置；能看图的模型同时收到上传的图片（PNG / JPEG / GIF / WebP，不超过 5MB）；同一会话换到不能看图的模型时，历史里的图片换成一句说明。用户消息下方显示附件，刷新后仍在（运行记录里存一份）。
- 新增：右侧文件面板——顶栏"文件"打开，列出本会话上传与生成的文件；预览图片、CSV / Excel 前 100 行（Excel 可切换工作表，CSV 支持 GBK 编码）、PDF（浏览器阅读器）、Markdown、网页（隔离的内嵌框，不执行脚本）与代码；点产物卡片或附件标签直接在面板里打开。接口 `GET /api/threads/{id}/files/{文件 ID}/table`。新增依赖 `openpyxl` 3.1.5（后端读 Excel）、`react-markdown` 10.1.0（原来就随 assistant-ui 装着，改为直接依赖）。
- 改进：回答下方的复制按钮挪到耗时与用量那一行的末尾，一直显示（原来要把鼠标移到回答上才出现，而且在回答下面单独占一行）。
- 改进（M2a 延后的小问题）：下载改为边读边传；文件类型不再依赖系统的类型表（后端容器里 Excel、Word、PPT 原来被当成未知类型）；文件被换成目录或指向会话目录外的链接时下载返回 404（原为 500）；测试规范补上测试沙箱。

```

- [ ] **步骤 3：浏览器端到端验证**

先运行 `make build`（后端加了 `openpyxl`、前端加了 `react-markdown` 并改了界面，要重新构建镜像），再在**普通浏览器**（Chrome / Safari）里打开 http://127.0.0.1:8000。第 2、4 步会调用真实模型，选 `gemini-3.5-flash`，费用约 0.05 美元。

准备几份文件：
- 一张图片；
- 一份用中文系统 Excel 另存的 CSV（GBK 编码）；
- 一份有两个工作表的 Excel；
- 一份 PDF；
- 一份 Markdown；
- 一份网页：内容是 `<p id=x>脚本没有执行</p><script>document.getElementById('x').textContent='脚本执行了！'</script>`。

1. **上传**：新建会话，点输入框左边的回形针选中图片与 CSV。
   - 输入框上方出现两个文件标签，转圈后显示大小。
   - 再把 Excel、PDF、Markdown、网页一起拖进对话区：出现"松开即可上传"，松开后都上传成功。
2. **附件交给智能体**：
   - 移除除图片和 CSV 以外的标签，发送"先说说图里是什么，再告诉我 CSV 有几行数据（不用派数据分析员）"；
   - 用户消息下方显示两个附件标签；
   - 回答正确描述了图片内容，并说出 CSV 的行数；
   - 刷新页面后附件标签仍在。
3. **文件面板**：点顶栏"文件"，面板分"上传的文件"列出全部 6 个文件，逐个点开：
   - 图片直接显示；
   - CSV 显示成表格，中文不乱码；
   - Excel 能切换两个工作表；
   - PDF 用浏览器阅读器显示；
   - Markdown 渲染出标题与列表；
   - 网页显示"脚本没有执行"（脚本没有运行）；
   - 每个文件右上角都能在新标签页打开、下载。
4. **产物与附件标签**：
   - 发送"用 write_file 写一个 outputs/总结.md：一级标题'总结'，下面一个两行的表格"；
   - 点回答里的产物卡片文件名，面板打开并渲染这份 Markdown；
   - 点第 2 步用户消息下的 CSV 附件标签，面板切到 CSV 预览。
5. **复制按钮**：
   - 每轮回答下方"耗时 · 输入 · 输出 · 费用"那一行的末尾有复制按钮，鼠标不移上去也能看到；回答进行中不显示；
   - 点它，再到别处粘贴，得到这轮回答的文字。
6. **超大文件**：
   - 终端运行 `mkfile 101m /tmp/big.bin`（Linux 用 `truncate -s 101M /tmp/big.bin`），把它拖进对话区；
   - 文件标签显示"文件超过 100MB 上限"，点 × 可移除；
   - 运行 `rm /tmp/big.bin` 删掉它。

预期：以上全部符合描述。

- [ ] **步骤 4：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 168 个、前端 82 个）；`make test-int` 全部通过（集成测试 69 个）。

收尾：
- 全部通过后，`docs/changelog.md` 的 M2b 小节保持"（完成）"、`docs/requirements/backlog.md` 的 R05b 保持"完成"；
- 若浏览器验证有未通过项，两处改回"进行中"并记录原因。

---

## 自查记录（写计划时完成）

- **设计覆盖**（第 21 节 M2 行剩余部分）：
  - **文件上传**（9.3"上传"）：
    - 存到 `uploads/` → 任务 2；
    - 智能体收到提示"用户上传了 uploads/xxx" → 任务 3（消息末尾注明位置，系统提示词说明 `uploads/`）；
    - 默认单文件上限 100MB → 任务 2；
    - 图片若当前模型能看图则作为图片内容发给模型 → 任务 3。
  - **预览**（9.3"预览"）：
    - 图片、CSV / Excel 前若干行、PDF 用浏览器阅读器、Markdown 渲染、HTML 隔离内嵌框、其他提供下载 → 任务 4、5；
    - 下载接口校验路径 → M2a 已按登记的文件 ID 下载，任务 1 补上换成目录 / 越界链接时的 404。
  - **登记**：上传记入 `workspace_files`（来源"上传"）→ 任务 2；删除会话时连同目录与登记一起删除 → M2a 已有。
  - 接口表"文件"一行 → 任务 1、2、4；12.2 第 3 条（上传要求自定义请求头）→ 任务 2；13.3 节右侧侧栏的"文件"页 → 任务 5；`runs`"用户输入（消息 + 附件引用）"→ 任务 3。
  - 用户追加的复制按钮调整 → 任务 7。
  - M2a 审查延后的小问题中与本期相关的几条（下载读进内存、越界返回 500、Office 类型、测试规范）→ 任务 1。其余几条留在 M2a 执行记录的延后清单里：被停止那条命令的产物不出卡片、客户端停机不关闭、日志同步写、链接行为的契约测试。
- **与设计文档的差异：**
  1. 9.3 节"会话附件可一键同时加入知识库"、接口表里上传接口的"可选同时加入知识库"：属于 M3（统一知识库），本期不做。
  2. 9.3 节"Markdown 和代码渲染或高亮"：代码只原样显示，不做语法高亮（与 R13"回答里的代码高亮"一并做）。
  3. 13.3 节右侧侧栏有"待办、文件、知识、用量"几页：本期只做"文件"一页（待办在对话里显示，知识、用量属于 M3、M5），侧栏默认收起、点顶栏"文件"打开。
  4. 上传接口不用表单格式（multipart），请求体直接是文件、文件名放在请求头：省掉一个依赖，自定义请求头本身满足 12.2 第 3 条。
  5. 网页预览不执行脚本：智能体生成的交互式网页（如带脚本的图表）在面板里、在新标签页里都不会运行脚本（下载接口的响应头同样禁止），需要时下载后在本机打开。
- **占位扫描：** 无"待定 / 以后实现"类步骤。
- **类型与命名一致性：** 已用严格类型检查、mypy 与重放验证。
  - `attachments` 在 `RunCreate`（文件 ID 列表）、`RunRecord` / `RunHistory`（`RunAttachment` 列表）、前端 `api.startRun`、事件处理器的用户项、转换函数的 `UserAttachment` 里各自一致；
  - `OpenFileContext` 在产物卡片、附件标签、`ChatThread` 里一致；
  - `previewKind` 的取值在面板图标与预览组件里一致。
