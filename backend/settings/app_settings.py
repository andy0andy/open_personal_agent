"""设置页的设置（D22）：存在数据库的 app_settings 表；取值顺序 代码默认值 → 数据库 → 同名环境变量。

只有默认对话模型改了立即生效，其余重启后端后生效（启动时 load_settings 读这张表）。
被环境变量覆盖的项页面上不能改：改了也不会生效，只会让人以为改好了。
"""

import os
from collections.abc import Mapping
from typing import Any, Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, JsonValue, ValidationError
from pydantic_core import ErrorDetails

from common.db import Pool
from common.errors import ConflictError, InvalidRequestError, NotFoundError
from config import Settings
from config.settings import SETTING_SPECS, SettingSpec, env_name, read_setting


class SettingView(BaseModel):
    """设置页上的一行：当前值、来源、能否在页面上改、改了何时生效。"""

    key: str
    label: str
    value: JsonValue  # 运行中的值
    upcoming: JsonValue  # 重启后会用的值（环境变量 > 数据库 > 默认值）：输入框显示它
    default: JsonValue  # 代码里的默认值
    source: Literal["default", "db", "env"]
    env_name: str  # 同名环境变量，如 AGENT__DEFAULT_MODEL
    editable: bool
    apply: Literal["now", "restart"]
    note: str | None = None
    restart_pending: bool  # 已存了新值，重启后端后才生效


class SettingValue(BaseModel):
    value: JsonValue


class AppSettingsRepo:
    """app_settings 表的读写：只存页面上改过的项。"""

    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def all(self) -> dict[str, Any]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT key, value FROM app_settings")
            rows = await cur.fetchall()
        return {row["key"]: row["value"] for row in rows}

    async def put(self, key: str, value: Any) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                (key, Jsonb(value)),
            )

    async def delete(self, key: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM app_settings WHERE key = %s", (key,))


class AppSettingsService:
    def __init__(self, settings: Settings, repo: AppSettingsRepo) -> None:
        self._settings = settings  # 运行中的设置（启动时读好的那一份）
        self._repo = repo
        self._defaults = Settings.model_construct()  # 只看代码默认值：不读环境变量与数据库
        self._reset: set[str] = set()  # 这次启动后在页面上"恢复默认"过的项

    async def views(self) -> list[SettingView]:
        stored = await self._repo.all()
        return [self._view(spec, stored) for spec in SETTING_SPECS]

    async def view(self, key: str) -> SettingView:
        return self._view(_spec(key), await self._repo.all())

    async def update(self, key: str, value: Any) -> SettingView:
        spec = _spec(key)
        if not spec.editable:
            raise ConflictError("这一项不能在页面上改")
        if _env_overrides(key):
            raise ConflictError(
                f"已由环境变量 {env_name(key)} 指定：要改请改 .env，然后执行 make restart"
            )
        # 存校验后的值（如开关项传来的 "false" 存成 False，积压小问题 F17），不存原样的请求值
        value = read_setting(self._validate(key, value, await self._repo.all()), key)
        await self._repo.put(key, value)
        self._reset.discard(key)
        if spec.apply == "now":
            self._apply(key, value)
        return await self.view(key)

    async def reset(self, key: str) -> SettingView:
        """删掉页面上存的值：重启后（立即生效的项立即）回到默认值或环境变量的值。"""
        spec = _spec(key)
        if not spec.editable:
            raise ConflictError("这一项不能在页面上改")
        rest = {k: v for k, v in (await self._repo.all()).items() if k != key}
        after = self._settings if _env_overrides(key) else self._defaults
        self._validate(key, read_setting(after, key), rest)
        await self._repo.delete(key)
        self._reset.add(key)
        if spec.apply == "now" and not _env_overrides(key):
            self._apply(key, read_setting(self._defaults, key))
        return await self.view(key)

    def default(self, key: str) -> Any:
        return read_setting(self._defaults, _spec(key).key)

    def _view(self, spec: SettingSpec, stored: dict[str, Any]) -> SettingView:
        value = read_setting(self._settings, spec.key)
        default = read_setting(self._defaults, spec.key)
        if _env_overrides(spec.key):
            source: Literal["default", "db", "env"] = "env"
        elif spec.key in stored:
            source = "db"
        else:
            source = "default"
        upcoming = self._upcoming(spec.key, stored)  # 与运行中的不同就是"重启后生效"
        return SettingView(
            key=spec.key,
            label=spec.label,
            value=value,
            upcoming=upcoming,
            default=default,
            source=source,
            env_name=env_name(spec.key),
            editable=spec.editable and source != "env",
            apply=spec.apply,
            note=spec.note,
            restart_pending=spec.apply == "restart" and spec.editable and upcoming != value,
        )

    def _upcoming(self, key: str, stored: Mapping[str, Any]) -> Any:
        """重启后会用的值：环境变量 > 数据库 > 默认值。

        没在页面上改过的项就是运行中的值（运行中的值可能来自启动参数，如测试）。
        """
        if not _env_overrides(key):
            if key in stored:
                return stored[key]
            if key in self._reset:
                return read_setting(self._defaults, key)
        return read_setting(self._settings, key)

    def _validate(self, key: str, value: Any, stored: Mapping[str, Any]) -> Settings:
        """在重启后会用的那份设置上改这一项，再整体校验（不读环境变量与 .env，只校验取值），
        返回校验后的设置。

        跨项的限制（如命令默认时限不超过最长时限）要和库里已存、还没生效的值一起看（终审 I3）。
        """
        data = self._settings.model_dump()
        for spec in SETTING_SPECS:
            if spec.editable:
                upcoming = value if spec.key == key else self._upcoming(spec.key, stored)
                _assign(data, spec.key, upcoming)
        try:
            return Settings.model_validate(data)
        except ValidationError as exc:
            raise InvalidRequestError(f"取值不合规：{_message(exc.errors()[0])}") from exc

    def _apply(self, key: str, value: Any) -> None:
        *sections, field = key.split(".")
        target: Any = self._settings
        for section in sections:
            target = getattr(target, section)
        setattr(target, field, value)


def _spec(key: str) -> SettingSpec:
    for spec in SETTING_SPECS:
        if spec.key == key:
            return spec
    raise NotFoundError(f"没有这个设置项：{key}")


def _assign(data: dict[str, Any], key: str, value: Any) -> None:
    *sections, field = key.split(".")
    for section in sections:
        data = data[section]
    data[field] = value


def _message(error: ErrorDetails) -> str:
    """校验错误说成中文：设置页上直接给人看。"""
    ctx = error.get("ctx", {})
    match error["type"]:
        case "greater_than":
            return f"应大于 {_number(ctx['gt'])}"
        case "greater_than_equal":
            return f"不能小于 {_number(ctx['ge'])}"
        case "less_than_equal":
            return f"不能大于 {_number(ctx['le'])}"
        case "int_parsing" | "int_type" | "int_from_float":
            return "应是整数"
        case "float_parsing" | "float_type":
            return "应是数字"
        case "bool_parsing" | "bool_type":
            return "应是 true 或 false"
        case _:
            return str(error["msg"]).removeprefix("Value error, ")


def _number(value: Any) -> str:
    """小数字段的界限会被转成 1.0：整数就按整数写。"""
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _env_overrides(key: str) -> bool:
    name = env_name(key)
    return any(variable.upper() == name for variable in os.environ)
