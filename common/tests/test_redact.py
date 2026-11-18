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


def test_vendor_token_formats_are_masked() -> None:
    """各家令牌的固定格式（记忆脱敏，R48）：样例都是编的。"""
    cases = {
        "令牌 github_pat_" + "A1b2C3d4E5" * 4: "令牌 github_pat_***",
        "用 ghp_" + "a1B2c3D4e5" * 3 + "f6 推送": "用 ghp_*** 推送",
        "AKIA" + "ABCDEFGHIJKLMNOP": "AKIA***",
        "谷歌的 AIza" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6": "谷歌的 AIza***",
        "xoxb-" + "1234567890-abcdefghij": "xoxb-***",
        "npm_" + "a1B2c3D4e5" * 3: "npm_***",
        "hf_" + "a1B2c3D4e5" * 3: "hf_***",
        "sk_live_" + "a1B2c3D4e5f6G7h8": "sk_live_***",
    }
    for text, masked in cases.items():
        assert redact(text, []) == masked


def test_private_key_block_is_masked() -> None:
    block = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ\n"
        "AAAAB3NzaC1yc2EAAAADAQABAAABAQC7\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )
    assert redact(f"私钥：\n{block}\n别外传", []) == "私钥：\n***\n别外传"
    # 只贴了前半截（没有结束行）也整段打码
    half = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA7\nb3BlbnNzaC1rZXk="
    assert redact(half, []) == "***"


def test_keys_right_after_chinese_are_masked() -> None:
    """汉字在正则里也算单词字符：紧跟在汉字后面的密钥（中间没有空格）也要认出来。"""
    assert redact("密钥是sk-abcdefgh12345678", []) == "密钥是sk-***"
    assert redact("令牌是ghp_" + "a1B2c3D4e5" * 3 + "f6", []) == "令牌是ghp_***"


def test_token_like_words_are_left_alone() -> None:
    for text in (
        "ghp_ 是 GitHub 令牌的前缀",
        "AKIA 开头的是 AWS 的访问密钥",
        "hf_hub_download(repo_id)",
        "npm_config_registry",
        "MAKIAVELLIANISM1234567",
        "-----BEGIN CERTIFICATE-----",
    ):
        assert redact(text, []) == text
