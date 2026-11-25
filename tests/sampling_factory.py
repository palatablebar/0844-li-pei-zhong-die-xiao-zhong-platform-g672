"""构造带可控 group_payments 的已签发批次，用于跨批次抽检测试。"""
import json

from app.service import pipeline


def _payload_with_groups(profile, groups):
    payload = pipeline(profile)
    payload["group_payments"] = groups
    return payload


def make_group(key, member, day, payers, total, claims=None):
    if claims is None:
        claims = [
            {
                "claim_id": f"{key.replace('|', '-')}-{payer}",
                "payer": payer,
                "billed_cents": total,
                "approved_cents": total,
                "deductible_cents": 0,
            }
            for payer in payers
        ]
    return {
        "group_key": key,
        "member_id": member,
        "service_date": day,
        "payers": payers,
        "claim_count": len(claims),
        "payment_total": total,
        "payments": claims,
    }


def seed_approved_run(run_store, run_key, groups, profile="clean"):
    payload = _payload_with_groups(profile, groups)
    row = run_store.create(run_key, profile, payload)
    row, problem = run_store.review(row["id"], "APPROVED", "抽检测试签发", row["revision"])
    assert problem is None
    return row["id"]


def stored_groups(run_store, run_id):
    row = run_store.get(run_id)
    return json.loads(row["payload"])["group_payments"]
