"""测试不碰真实密钥（设计 2026-10-23 7.6）：带凭据的环境变量清掉，构造设置时不读 .env。

冒烟测试（-m live）要用真实网关，不清。
"""

import os
from pathlib import Path

import dotenv

from config import Settings

_CREDENTIAL_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")


def test_no_credentials_in_test_env() -> None:
    leaked = [name for name in os.environ if name.upper().endswith(_CREDENTIAL_SUFFIXES)]
    assert leaked == []


def test_settings_do_not_read_dotenv() -> None:
    assert Settings.model_config.get("env_file") is None


def test_dotenv_is_not_loaded(tmp_path: Path) -> None:
    """litellm、magika 一导入就读 .env（早于清凭据）：测试里读 .env 什么都不做，库地址也进不来。"""
    env = tmp_path / ".env"
    env.write_text("OPA_DOTENV_PROBE=1\n", encoding="utf-8")
    dotenv.load_dotenv(env)
    assert "OPA_DOTENV_PROBE" not in os.environ
    assert "DATABASE_URL" not in os.environ
