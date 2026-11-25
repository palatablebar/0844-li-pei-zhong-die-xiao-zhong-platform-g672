"""抽检名额选择策略。

规则（见 docs/BUSINESS-RULES.md）：

* 名额固定；同一成员同一服务日的理赔组占一个名额。
* 跨批次给付有差异（组内最高与最低给付总额不同）的理赔组必须先入样；
  名额放不下时，差额从大到小保留。
* 剩余名额优先让支付方覆盖尽量多的理赔组，逐轮选择能带来最多新支付方、
  且组内支付方更丰富的组；无法再扩展覆盖时按稳定顺序补齐。
* 全部选择均为确定性的：相同候选与名额永远得到同一份名单，重试不新增。
"""

# 入样原因码
REASON_DIFF = "CROSS_BATCH_DIFF"          # 跨批次给付有差异，强制入样
REASON_COVERAGE = "PAYER_COVERAGE"        # 带来新支付方，扩大覆盖
REASON_FILL = "QUOTA_FILL"                # 覆盖无法再扩展，按顺序补满

REASON_TEXT = {
    REASON_DIFF: "跨批次给付差异",
    REASON_COVERAGE: "支付方覆盖",
    REASON_FILL: "名额补齐",
}


def aggregate_candidates(batch_groups):
    """把多个已签发批次的理赔组合并为候选池。

    ``batch_groups`` 形如 ``[{"run_id": ..., "groups": [group_payment, ...]}]``。
    同一 ``group_key`` 跨批次的给付总额用于计算差额；支付方取并集。
    """
    merged = {}
    order = []
    for batch in batch_groups:
        for group in batch["groups"]:
            key = group["group_key"]
            if key not in merged:
                merged[key] = {
                    "group_key": key,
                    "member_id": group["member_id"],
                    "service_date": group["service_date"],
                    "payers": set(),
                    "totals": [],
                    "batch_run_ids": [],
                    "claim_count": 0,
                }
                order.append(key)
            candidate = merged[key]
            candidate["payers"].update(group["payers"])
            candidate["totals"].append(int(group["payment_total"]))
            candidate["batch_run_ids"].append(batch["run_id"])
            candidate["claim_count"] = max(candidate["claim_count"], int(group.get("claim_count", 0)))
    candidates = []
    for key in order:
        candidate = merged[key]
        totals = candidate["totals"]
        highest = max(totals)
        lowest = min(totals)
        candidates.append(
            {
                "group_key": key,
                "member_id": candidate["member_id"],
                "service_date": candidate["service_date"],
                "payers": sorted(candidate["payers"]),
                "batch_run_ids": candidate["batch_run_ids"],
                "batch_count": len(totals),
                "claim_count": candidate["claim_count"],
                "highest_total": highest,
                "lowest_total": lowest,
                "payment_gap": highest - lowest,
            }
        )
    return candidates


def build_plan(candidates, quota):
    """返回确定性的入样计划，每项含 group_key 与 reason。"""
    if quota <= 0:
        return []
    diff_groups = sorted(
        (item for item in candidates if item["payment_gap"] > 0),
        key=lambda item: (-item["payment_gap"], item["group_key"]),
    )
    plan = []
    selected = set()
    covered = set()
    for group in diff_groups[:quota]:
        plan.append({"group_key": group["group_key"], "reason": REASON_DIFF})
        selected.add(group["group_key"])
        covered.update(group["payers"])
    if len(plan) >= quota:
        return plan
    while len(plan) < quota:
        available = [item for item in candidates if item["group_key"] not in selected]
        if not available:
            break
        pick = _coverage_pick(available, covered)
        reason = REASON_COVERAGE if covered.union(pick["payers"]) - covered else REASON_FILL
        plan.append({"group_key": pick["group_key"], "reason": reason})
        selected.add(pick["group_key"])
        covered.update(pick["payers"])
    return plan


def _coverage_pick(available, covered):
    def rank(item):
        new_payers = len(set(item["payers"]) - covered)
        return (-new_payers, -len(item["payers"]), item["group_key"])

    return min(available, key=rank)


def reason_detail(candidate, reason):
    """生成工作台展示用的入样原因说明。"""
    if reason == REASON_DIFF:
        return (
            f'{REASON_TEXT[reason]}：最高给付 {candidate["highest_total"]} 分、'
            f'最低 {candidate["lowest_total"]} 分，差额 {candidate["payment_gap"]} 分'
        )
    if reason == REASON_COVERAGE:
        return f'{REASON_TEXT[reason]}：新增支付方 {sorted(set(candidate["payers"]))}'
    return f'{REASON_TEXT[reason]}：覆盖已稳定，按稳定顺序补满名额'
