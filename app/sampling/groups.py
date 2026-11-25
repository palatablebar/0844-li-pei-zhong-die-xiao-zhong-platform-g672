"""结构化的理赔组给付数据。

抽检按“同一成员同一服务日”的理赔组进行，需要保留每个批次内每个组
各支付方的给付依据，而不只是汇总数。这里复用整理后的行与消重计算结果，
生成可随批次证据长期保存的结构化给付明细。
"""
from collections import OrderedDict

PAYER_ORDER = {"MEDICARE": 1, "PRIVATE": 2, "SELF": 3}


def collect_group_payments(prepared, results):
    """从整理后的行与计算结果重建每个理赔组的给付明细。

    返回的每个条目都带稳定的组键 ``group_key``，同一成员同一服务日
    在单个批次内只产生一个条目。金额均为整数最小单位（分）。
    """
    grouped = OrderedDict()
    for item in prepared:
        key = (item["member_id"], item["service_date"].isoformat())
        grouped.setdefault(key, []).append(item)
    paid_lookup = {}
    for result in results:
        member, service_date = result["label"].split("|", 1)
        paid_lookup[(member, service_date)] = result.get("paid", 0)
    payments = []
    for (member, service_date), claims in grouped.items():
        ordered = sorted(claims, key=lambda row: (PAYER_ORDER.get(row["payer"].upper(), 99), row["claim_id"]))
        entries = [
            {
                "claim_id": claim["claim_id"],
                "payer": claim["payer"],
                "billed_cents": claim["billed_cents"],
                "approved_cents": claim["approved_cents"],
                "deductible_cents": claim["deductible_cents"],
            }
            for claim in ordered
        ]
        payments.append(
            {
                "group_key": member + "|" + service_date,
                "member_id": member,
                "service_date": service_date,
                "payers": sorted({entry["payer"] for entry in entries}),
                "claim_count": len(entries),
                "payment_total": int(paid_lookup.get((member, service_date), 0)),
                "payments": entries,
            }
        )
    return payments
