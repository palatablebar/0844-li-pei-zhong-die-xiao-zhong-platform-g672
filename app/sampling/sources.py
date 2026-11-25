"""已签发批次的读取仓库。

抽检只看已签发（APPROVED）批次。每个批次的 payload 在签发时已固化，
其中 ``group_payments`` 保留当时各支付方的给付依据，名单发布后仍可核对。
"""
import json


def approved_batches(run_store):
    batches = []
    for row in run_store.list_approved():
        payload = json.loads(row["payload"])
        batches.append(
            {
                "run_id": row["id"],
                "profile": row["profile"],
                "signed_at": row["created_at"],
                "revision": row["revision"],
                "source": payload.get("source", {}),
                "groups": payload.get("group_payments", []),
            }
        )
    return batches
