"""日志与报错文字打码（设计 2026-10-23 5.12）。"""

from common.redact import redact, secret_values


def test_known_secret_values_from_env_are_masked() -> None:
    env = {
        "LITELLM_MASTER_KEY": "abcd1234efgh",
        "GITHUB_TOKEN": "ghp_abcdefgh1234",
        "MAIL_SECRET": "s3cr3t-value",
        "DB_PASSWORD": "p@ssw0rd!",
        "SHORT_KEY": "abc12",  # 太短：会误伤普通文字，不当密钥
        "HOME": "/root/abcdefgh",  # 名字不像密钥
    }
    secrets = secret_values(env)
    assert sorted(secrets) == sorted(
        ["abcd1234efgh", "ghp_abcdefgh1234", "s3cr3t-value", "p@ssw0rd!"]
    )
    text = "master abcd1234efgh, gh ghp_abcdefgh1234, mail s3cr3t-value, db p@ssw0rd! abc12"
    assert redact(text, secrets) == "master ***, gh ***, mail ***, db *** abc12"
    assert redact("home /root/abcdefgh", secrets) == "home /root/abcdefgh"


def test_common_key_formats_are_masked() -> None:
    assert redact("key sk-abcdefgh12345678 used", []) == "key sk-*** used"
    assert redact("sk-ant-api03-AbC_dEf-123456 rejected", []) == "sk-*** rejected"
    assert redact("Authorization: Bearer abcdefgh.ijk-123=", []) == "Authorization: Bearer ***"
    assert redact("url?api_key=abcdef123456&x=1", []) == "url?api_key=***&x=1"
    assert redact('{"token": "abcdef123456"}', []) == '{"token": "***"}'
    assert redact("password=hunter22", []) == "password=***"


def test_url_credentials_are_masked() -> None:
    url = "postgresql://agent:supersecret@postgres:5432/agent"
    assert redact(url, []) == "postgresql://agent:***@postgres:5432/agent"


def test_ordinary_text_is_left_alone() -> None:
    for text in (
        "pip install scikit-learn",
        "task-1234567890 finished",
        "token: ok",
        "Bearer 是一种认证方式",
        "http://localhost:8000/api/health",
        "密码不对，请重试",
    ):
        assert redact(text, []) == text
