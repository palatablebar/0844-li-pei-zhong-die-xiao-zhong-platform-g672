"""抽检周期与名单的持久化。

生成过程可中断恢复：选择结果按组逐条落库，重试时已存在的入样记录原样保留，
只补齐缺额，永不新增重复名额。周期发布（frozen）后名单冻结，之后新签发的
批次不影响本期。
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

PERIOD_BUILDING = "BUILDING"
PERIOD_PUBLISHED = "PUBLISHED"


class SamplingStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=8)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self):
        with self.connect() as db:
            db.executescript(
                """
            CREATE TABLE IF NOT EXISTS sample_periods(
              id TEXT PRIMARY KEY,
              period_no TEXT NOT NULL,
              status TEXT NOT NULL,
              quota INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              published_at TEXT,
              universe_run_ids TEXT NOT NULL,
              plan_digest TEXT
            );
            CREATE TABLE IF NOT EXISTS sample_selections(
              period_id TEXT NOT NULL,
              rank_no INTEGER NOT NULL,
              group_key TEXT NOT NULL,
              reason_code TEXT NOT NULL,
              reason_detail TEXT NOT NULL,
              evidence TEXT NOT NULL,
              PRIMARY KEY(period_id, group_key),
              UNIQUE(period_id, rank_no)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_building
              ON sample_periods(status) WHERE status='BUILDING';
            """
            )

    def open_period(self):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM sample_periods WHERE status=? ORDER BY created_at DESC LIMIT 1",
                (PERIOD_BUILDING,),
            ).fetchone()
        return dict(row) if row else None

    def latest_period(self):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM sample_periods ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def get_period(self, period_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM sample_periods WHERE id=?", (period_id,)).fetchone()
        return dict(row) if row else None

    def get_or_create_open(self, db, quota, universe_run_ids):
        """在已锁定的事务内原子地取得当前开放周期，不存在则创建。"""
        row = db.execute(
            "SELECT * FROM sample_periods WHERE status=? ORDER BY created_at DESC LIMIT 1",
            (PERIOD_BUILDING,),
        ).fetchone()
        if row is not None:
            return dict(row)
        period_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        period_no = now.strftime("%Y%m") + "-" + uuid.uuid4().hex[:4].upper()
        db.execute(
            "INSERT INTO sample_periods(id,period_no,status,quota,created_at,universe_run_ids) "
            "VALUES(?,?,?,?,?,?)",
            (
                period_id,
                period_no,
                PERIOD_BUILDING,
                int(quota),
                now.isoformat(),
                json.dumps(universe_run_ids, ensure_ascii=False),
            ),
        )
        row = db.execute("SELECT * FROM sample_periods WHERE id=?", (period_id,)).fetchone()
        return dict(row)

    def list_selections(self, period_id):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM sample_selections WHERE period_id=? ORDER BY rank_no ASC", (period_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def count_selections(self, period_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM sample_selections WHERE period_id=?", (period_id,)
            ).fetchone()
        return int(row["n"])

    def insert_selection(self, db, period_id, rank_no, group_key, reason_code, reason_detail, evidence):
        db.execute(
            "INSERT OR IGNORE INTO sample_selections"
            "(period_id,rank_no,group_key,reason_code,reason_detail,evidence) VALUES(?,?,?,?,?,?)",
            (
                period_id,
                int(rank_no),
                group_key,
                reason_code,
                reason_detail,
                json.dumps(evidence, ensure_ascii=False),
            ),
        )

    def set_plan_digest(self, db, period_id, digest):
        db.execute("UPDATE sample_periods SET plan_digest=? WHERE id=?", (digest, period_id))

    def publish_period(self, db, period_id, published_at):
        db.execute(
            "UPDATE sample_periods SET status=?, published_at=? WHERE id=?",
            (PERIOD_PUBLISHED, published_at, period_id),
        )
