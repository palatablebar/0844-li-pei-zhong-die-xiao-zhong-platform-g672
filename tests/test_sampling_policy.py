from app.sampling.policy import (
    REASON_COVERAGE,
    REASON_DIFF,
    REASON_FILL,
    aggregate_candidates,
    build_plan,
)


def group(run_id, key, member, day, payers, total):
    return {
        "run_id": run_id,
        "groups": [
            {
                "group_key": key,
                "member_id": member,
                "service_date": day,
                "payers": payers,
                "claim_count": len(payers),
                "payment_total": total,
                "payments": [],
            }
        ],
    }


def batches():
    return [
        group("R1", "M1|2026-11-01", "M1", "2026-11-01", ["MEDICARE", "PRIVATE"], 1000),
        group("R2", "M1|2026-11-01", "M1", "2026-11-01", ["MEDICARE", "PRIVATE"], 1300),
        group("R1", "M2|2026-11-02", "M2", "2026-11-02", ["PRIVATE"], 500),
        group("R2", "M2|2026-11-02", "M2", "2026-11-02", ["PRIVATE"], 500),
        group("R1", "M3|2026-11-03", "M3", "2026-11-03", ["SELF"], 400),
        group("R1", "M4|2026-11-04", "M4", "2026-11-04", ["MEDICARE"], 300),
    ]


def candidates():
    return aggregate_candidates(batches())


def by_key(cands):
    return {c["group_key"]: c for c in cands}


def test_gap_is_highest_minus_lowest_total():
    item = by_key(candidates())["M1|2026-11-01"]
    assert item["highest_total"] == 1300
    assert item["lowest_total"] == 1000
    assert item["payment_gap"] == 300
    assert item["payers"] == ["MEDICARE", "PRIVATE"]


def test_equal_totals_have_no_gap():
    item = by_key(candidates())["M2|2026-11-02"]
    assert item["payment_gap"] == 0


def test_payers_are_unioned_across_batches():
    data = [
        group("R1", "G|d", "G", "d", ["MEDICARE"], 10),
        group("R2", "G|d", "G", "d", ["SELF"], 10),
    ]
    item = by_key(aggregate_candidates(data))["G|d"]
    assert item["payers"] == ["MEDICARE", "SELF"]


def test_diff_group_is_forced_first():
    plan = build_plan(candidates(), quota=5)
    assert plan[0] == {"group_key": "M1|2026-11-01", "reason": REASON_DIFF}


def test_diff_groups_sorted_by_gap_descending():
    data = batches() + [
        group("R1", "M9|2026-11-09", "M9", "2026-11-09", ["SELF"], 100),
        group("R2", "M9|2026-11-09", "M9", "2026-11-09", ["SELF"], 2000),
    ]
    cands = aggregate_candidates(data)
    plan = build_plan(cands, quota=2)
    assert [p["group_key"] for p in plan] == ["M9|2026-11-09", "M1|2026-11-01"]
    assert all(p["reason"] == REASON_DIFF for p in plan)


def test_overflow_keeps_largest_gaps_and_respects_quota():
    data = []
    for idx in range(4):
        key = f"M{idx}|d"
        data.append(group("R1", key, f"M{idx}", "d", ["SELF"], 10))
        data.append(group("R2", key, f"M{idx}", "d", ["SELF"], 100 * (idx + 1)))
    plan = build_plan(aggregate_candidates(data), quota=2)
    assert len(plan) == 2
    assert [p["group_key"] for p in plan] == ["M3|d", "M2|d"]


def test_coverage_filling_maximizes_distinct_payers():
    # 唯一差异组强制入样后，剩余名额应优先带来新支付方的组。
    plan = build_plan(candidates(), quota=3)
    keys = [p["group_key"] for p in plan]
    assert keys[0] == "M1|2026-11-01"
    second = by_key(candidates())[keys[1]]
    # M1 已覆盖 MEDICARE/PRIVATE，下一个应带来 SELF 的 M3，而不是只含 PRIVATE 的 M2。
    assert "SELF" in second["payers"]
    assert plan[1]["reason"] == REASON_COVERAGE


def test_fill_reason_when_coverage_cannot_grow():
    data = [
        group("R1", "M1|d", "M1", "d", ["MEDICARE"], 100),
        group("R2", "M1|d", "M1", "d", ["MEDICARE"], 100),
        group("R1", "M2|d", "M2", "d", ["MEDICARE"], 100),
        group("R1", "M3|d", "M3", "d", ["MEDICARE"], 100),
    ]
    plan = build_plan(aggregate_candidates(data), quota=3)
    assert len(plan) == 3
    assert plan[1]["reason"] in {REASON_COVERAGE, REASON_FILL}
    assert plan[-1]["reason"] == REASON_FILL


def test_plan_is_deterministic():
    first = build_plan(candidates(), quota=4)
    second = build_plan(candidates(), quota=4)
    assert first == second


def test_zero_quota_returns_empty():
    assert build_plan(candidates(), quota=0) == []


def test_one_member_one_service_date_is_one_slot():
    # 同一成员同一服务日无论跨多少批次，聚合后只有一个候选组。
    data = [group("R1", "M1|d", "M1", "d", ["SELF"], 10)]
    for idx in range(5):
        data.append(group(f"R{idx+2}", "M1|d", "M1", "d", ["SELF"], 10 + idx))
    cands = aggregate_candidates(data)
    assert len(cands) == 1
    assert len(build_plan(cands, quota=5)) == 1
