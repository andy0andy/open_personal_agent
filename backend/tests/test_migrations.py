import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from backend.runs import RunRepo
from backend.threads import ThreadRepo
from common.db import Pool
from common.ids import new_id, short_id

pytestmark = pytest.mark.integration


async def test_backend_tables_and_active_run_index_exist(pg_pool: Pool) -> None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            "SELECT to_regclass('public.threads')::text AS threads, "
            "to_regclass('public.runs')::text AS runs, "
            "to_regclass('public.run_events')::text AS run_events, "
            "to_regclass('public.runs_one_active_per_thread')::text AS active_index"
        )
        row = await cur.fetchone()
    assert row == {
        "threads": "threads",
        "runs": "runs",
        "run_events": "run_events",
        "active_index": "runs_one_active_per_thread",
    }


async def test_agents_usage_table_exists(pg_pool: Pool) -> None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute("SELECT to_regclass('public.llm_usage')::text AS usage")
        row = await cur.fetchone()
    assert row == {"usage": "llm_usage"}


async def test_workspace_files_table_exists(pg_pool: Pool) -> None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute("SELECT to_regclass('public.workspace_files')::text AS files")
        row = await cur.fetchone()
    assert row == {"files": "workspace_files"}


async def test_knowledge_items_table_and_vector_extension_exist(pg_pool: Pool) -> None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            "SELECT to_regclass('public.knowledge_items')::text AS items, "
            "(SELECT extname FROM pg_extension WHERE extname = 'vector') AS vector"
        )
        row = await cur.fetchone()
    assert row == {"items": "knowledge_items", "vector": "vector"}


async def test_jobs_table_exists(pg_pool: Pool) -> None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute("SELECT to_regclass('public.jobs')::text AS jobs")
        row = await cur.fetchone()
    assert row == {"jobs": "jobs"}


async def test_threads_have_custom_position(pg_pool: Pool) -> None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'threads' AND column_name = 'position'"
        )
        row = await cur.fetchone()
    assert row == {"data_type": "integer", "is_nullable": "NO"}


async def test_existing_threads_get_positions_by_recent_use(
    db: Pool, alembic_config: Config
) -> None:
    """0003：已有会话按最近使用的顺序排好（最近用过的在上面），升级后列表顺序不变。"""
    command.downgrade(alembic_config, "0002")
    try:
        async with db.connection() as conn:
            for short_id, hours_ago in (("c_old", 3), ("c_new", 1), ("c_mid", 2)):
                await conn.execute(
                    "INSERT INTO threads (id, short_id, model, updated_at) "
                    "VALUES (gen_random_uuid(), %s, 'm', now() - make_interval(hours => %s))",
                    (short_id, hours_ago),
                )
        command.upgrade(alembic_config, "0003")
    finally:
        command.upgrade(alembic_config, "head")

    assert [t.short_id for t in await ThreadRepo(db).list_active()] == ["c_new", "c_mid", "c_old"]


async def test_finished_events_use_interrupted_usage(db: Pool, alembic_config: Config) -> None:
    """0004：已存结束事件的 interrupted 改名为 interrupted_usage（与运行状态 interrupted 区分）；
    M1b 之前存下的结束事件补齐 usage / interrupted_usage（前端类型把它们标为必有）。"""
    estimate = {"input_tokens": 5, "output_tokens": 1, "cost": None}
    old_data = [
        {"status": "completed", "error": None},  # M1b 之前
        {"status": "cancelled", "error": None, "usage": None, "interrupted": estimate},
    ]
    command.downgrade(alembic_config, "0003")
    run_id = new_id()
    try:
        async with db.connection() as conn:
            # 用 0003 时的表结构直接插入：现在的数据访问会读之后才加的列
            thread_id = new_id()
            await conn.execute(
                "INSERT INTO threads (id, short_id, title, model) VALUES (%s, %s, '', 'm')",
                (thread_id, short_id()),
            )
            await conn.execute(
                "INSERT INTO runs (id, thread_id, status, model, input) "
                "VALUES (%s, %s, 'completed', 'm', %s)",
                (run_id, thread_id, Jsonb({"message": "hi"})),
            )
            for seq, data in enumerate(old_data, start=1):
                payload = {
                    "seq": seq,
                    "run_id": str(run_id),
                    "ts": "2026-10-12T00:00:00Z",
                    "type": "run.finished",
                    "agent_path": ["main"],
                    "data": data,
                }
                await conn.execute(
                    "INSERT INTO run_events (run_id, seq, type, payload) VALUES (%s, %s, %s, %s)",
                    (run_id, seq, "run.finished", Jsonb(payload)),
                )
        command.upgrade(alembic_config, "0004")
    finally:
        command.upgrade(alembic_config, "head")

    assert [e.data for e in await RunRepo(db).events(run_id)] == [
        {"status": "completed", "error": None, "usage": None, "interrupted_usage": None},
        {"status": "cancelled", "error": None, "usage": None, "interrupted_usage": estimate},
    ]


async def test_knowledge_documents_table_exists(pg_pool: Pool) -> None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute("SELECT to_regclass('public.knowledge_documents')::text AS name")
        row = await cur.fetchone()
    assert row == {"name": "knowledge_documents"}


async def test_thread_permission_mode_column(db: Pool) -> None:
    """会话的审批权限（迁移 0010）：默认"每次先问"，只认三个取值。"""
    thread = await ThreadRepo(db).create(title="", model="m")
    assert thread.permission_mode == "ask"
    with pytest.raises(psycopg.errors.CheckViolation):
        async with db.connection() as conn:
            await conn.execute(
                "UPDATE threads SET permission_mode = 'other' WHERE id = %s", (thread.id,)
            )


async def test_app_settings_table(db: Pool) -> None:
    """设置页的设置（迁移 0011，D22）：每个设置键一行，值是 JSON。"""
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT a.attname AS name FROM pg_index i JOIN pg_attribute a "
            "ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'app_settings'::regclass AND i.indisprimary"
        )
        assert [row["name"] for row in await cur.fetchall()] == ["key"]


async def test_usage_cost_column_dropped(db: Pool) -> None:
    """后台不再存费用（迁移 0012，设计 4.11）：llm_usage 没有 cost 列。"""
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'llm_usage'"
        )
        columns = {row["column_name"] for row in await cur.fetchall()}
    assert "cost" not in columns
    assert {"input_tokens", "output_tokens", "cache_read_tokens"} <= columns


async def test_runs_retry_of_column(db: Pool) -> None:
    """ "重试这一轮"（迁移 0013，D26）：新运行记下重试的是哪一次；原运行删掉时置空。"""
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT is_nullable, data_type FROM information_schema.columns "
            "WHERE table_name = 'runs' AND column_name = 'retry_of'"
        )
        row = await cur.fetchone()
    assert row is not None
    assert (row["is_nullable"], row["data_type"]) == ("YES", "uuid")


async def test_conversation_turns_table(db: Pool) -> None:
    """会话索引（迁移 0014，设计 2026-10-23 6.1）：每次运行一行，按运行 ID 唯一，带全文检索列。"""
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'conversation_turns'"
        )
        columns = {row["column_name"] for row in await cur.fetchall()}
        cur = await conn.execute(
            "SELECT a.attname AS name FROM pg_index i JOIN pg_attribute a "
            "ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'conversation_turns'::regclass AND i.indisprimary"
        )
        primary = [row["name"] for row in await cur.fetchall()]
    assert {"run_id", "thread_id", "title", "started_at", "user_text", "answer_text"} <= columns
    assert "search" in columns
    assert primary == ["run_id"]


async def test_threads_last_viewed_column(db: Pool) -> None:
    """会话的最后查看时间（迁移 0015，设计 2026-10-23 6.5）：已有会话填升级时的时间，不全亮绿点。"""
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'threads' AND column_name = 'last_viewed_at'"
        )
        row = await cur.fetchone()
    assert row is not None
    assert row["is_nullable"] == "NO"
    assert "now()" in row["column_default"]


async def test_knowledge_suspicious_columns(db: Pool) -> None:
    """记忆的可疑标记（迁移 0016，设计 2026-10-23 6.6）：旧条目没有标记、未确认，照常可用。"""
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'knowledge_items' AND column_name IN ('suspicious', 'trusted')"
        )
        rows = {row["column_name"]: row for row in await cur.fetchall()}
    assert rows["suspicious"]["is_nullable"] == "YES"
    assert rows["trusted"]["is_nullable"] == "NO"
    assert rows["trusted"]["column_default"] == "false"


async def test_tool_usage_table(db: Pool) -> None:
    """工具与技能用量（迁移 0017，设计 2026-10-23 6.8）：独立的表，删会话不影响统计（不设外键）。"""
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'tool_usage'"
        )
        columns = {row["column_name"] for row in await cur.fetchall()}
        cur = await conn.execute(
            "SELECT count(*) AS n FROM information_schema.table_constraints "
            "WHERE table_name = 'tool_usage' AND constraint_type = 'FOREIGN KEY'"
        )
        row = await cur.fetchone()
    assert {"id", "created_at", "thread_id", "run_id", "tool", "skill"} <= columns
    assert row is not None
    assert row["n"] == 0


async def test_knowledge_documents_content_hash_column(db: Pool) -> None:
    """文档的内容哈希（迁移 0018，积压小问题 C12）：旧文档为空，启动时后台补算；按它查重有索引。"""
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'knowledge_documents' AND column_name = 'content_hash'"
        )
        column = await cur.fetchone()
        cur = await conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'knowledge_documents'"
        )
        indexes = [row["indexdef"] for row in await cur.fetchall()]
    assert column is not None
    assert column["is_nullable"] == "YES"
    assert any("content_hash" in index for index in indexes)
