"""抽检周期的编排服务。

周期在第一次生成时冻结“候选宇宙”（当时全部已签发批次的 run_id）。
之后无论重试还是中断恢复，都只在该宇宙内重新计算确定性计划并补齐缺额；
新签发的批次在本期被忽略，留到下一周期。
"""
import json
from datetime import datetime, timezone

from app.evidence.manifest import stable_digest
from app.sampling.policy import aggregate_candidates, build_plan, reason_detail
from app.sampling.sources import approved_batches
from app.sampling.store import PERIOD_BUILDING

DEFAULT_QUOTA = 5


def _universe(run_store, run_ids=None):
    batches = approved_batches(run_store)
    if run_ids is not None:
        wanted = set(run_ids)
        batches = [batch for batch in batches if batch["run_id"] in wanted]
    return batches


def _candidate_index(candidates):
    return {item["group_key"]: item for item in candidates}


def _evidence_for(candidate, batches):
    """固化入样组在各批次的给付依据，供名单发布后核对。"""
    run_lookup = {batch["run_id"]: batch for batch in batches}
    per_batch = []
    for run_id in candidate["batch_run_ids"]:
        batch = run_lookup.get(run_id)
        group = next((g for g in batch["groups"] if g["group_key"] == candidate["group_key"]), None)
        if group is None:
            continue
        per_batch.append(
            {
                "run_id": run_id,
                "profile": batch["profile"],
                "signed_at": batch["signed_at"],
                "source_sha256": batch["source"].get("sha256", ""),
                "payment_total": group["payment_total"],
                "payers": group["payers"],
                "payments": group["payments"],
            }
        )
    return {
        "group_key": candidate["group_key"],
        "member_id": candidate["member_id"],
        "service_date": candidate["service_date"],
        "highest_total": candidate["highest_total"],
        "lowest_total": candidate["lowest_total"],
        "payment_gap": candidate["payment_gap"],
        "payers": candidate["payers"],
        "batch_evidence": per_batch,
    }


def generate(sample_store, run_store, quota=DEFAULT_QUOTA):
    """生成或续跑当前周期，返回周期视图。重试不新增当期名单。"""
    db = sample_store.connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        # 开放周期的取或建在同一锁内完成，并发只会得到同一个周期。
        period = sample_store.get_or_create_open(db, quota, [b["run_id"] for b in approved_batches(run_store)])
        batches = _universe(run_store, json.loads(period["universe_run_ids"]))
        candidates = aggregate_candidates(batches)
        index = _candidate_index(candidates)
        plan = build_plan(candidates, int(period["quota"]))
        existing = {r["group_key"] for r in db.execute(
            "SELECT group_key FROM sample_selections WHERE period_id=?", (period["id"],)).fetchall()}
        next_rank = db.execute(
            "SELECT COUNT(*) AS n FROM sample_selections WHERE period_id=?", (period["id"],)).fetchone()["n"]
        for entry in plan:
            if entry["group_key"] in existing:
                continue
            candidate = index[entry["group_key"]]
            sample_store.insert_selection(
                db,
                period["id"],
                next_rank,
                entry["group_key"],
                entry["reason"],
                reason_detail(candidate, entry["reason"]),
                _evidence_for(candidate, batches),
            )
            next_rank += 1
        sample_store.set_plan_digest(db, period["id"], stable_digest(plan))
        period_id = period["id"]
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return get_period_view(sample_store, period_id)


def publish(sample_store, run_store):
    db = sample_store.connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM sample_periods WHERE status=? ORDER BY created_at DESC LIMIT 1",
            (PERIOD_BUILDING,),
        ).fetchone()
        if row is None:
            db.rollback()
            return None
        period_id = row["id"]
        sample_store.publish_period(db, period_id, datetime.now(timezone.utc).isoformat())
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return get_period_view(sample_store, period_id)


def get_period_view(sample_store, period_id):
    period = sample_store.get_period(period_id)
    if period is None:
        return None
    selections = sample_store.list_selections(period_id)
    items = []
    for row in selections:
        items.append(
            {
                "rank_no": row["rank_no"],
                "group_key": row["group_key"],
                "reason_code": row["reason_code"],
                "reason_detail": row["reason_detail"],
                "evidence": json.loads(row["evidence"]),
            }
        )
    return {
        "period_id": period["id"],
        "period_no": period["period_no"],
        "status": period["status"],
        "quota": period["quota"],
        "filled": len(items),
        "universe_run_ids": json.loads(period["universe_run_ids"]),
        "plan_digest": period["plan_digest"],
        "created_at": period["created_at"],
        "published_at": period["published_at"],
        "selections": items,
    }


def current_period(sample_store):
    period = sample_store.latest_period()
    if period is None:
        return None
    return get_period_view(sample_store, period["id"])


def list_periods(sample_store):
    # 当前规模下周期数量有限，复用 latest 逻辑逐个读取；保持接口简单。
    views = []
    with sample_store.connect() as db:
        rows = db.execute("SELECT id FROM sample_periods ORDER BY created_at DESC").fetchall()
    for row in rows:
        views.append(get_period_view(sample_store, row["id"]))
    return views
