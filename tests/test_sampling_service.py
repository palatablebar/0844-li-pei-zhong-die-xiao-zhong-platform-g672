import pytest

from app.review.store import Store
from app.sampling import service
from app.sampling.store import PERIOD_BUILDING, PERIOD_PUBLISHED, SamplingStore
from tests.sampling_factory import make_group, seed_approved_run

@pytest.fixture
def stores(tmp_path):
    db = tmp_path / "workbench.sqlite3"
    return SamplingStore(db), Store(db)


def two_batches(run_store):
    g1a = make_group("M1|2026-11-01", "M1", "2026-11-01", ["MEDICARE", "PRIVATE"], 1000)
    g1b = make_group("M1|2026-11-01", "M1", "2026-11-01", ["MEDICARE", "PRIVATE"], 1300)
    g2 = make_group("M2|2026-11-02", "M2", "2026-11-02", ["SELF"], 400)
    g3 = make_group("M3|2026-11-03", "M3", "2026-11-03", ["MEDICARE"], 300)
    r1 = seed_approved_run(run_store, "key-r1", [g1a, g2])
    r2 = seed_approved_run(run_store, "key-r2", [g1b, g3])
    return r1, r2


def test_only_approved_batches_are_considered(stores):
    sample_store, run_store = stores
    two_batches(run_store)
    # 再建一个未签发批次，其组不应进入候选宇宙。
    draft = run_store.create("draft-key", "clean", {"group_payments": []})
    view = service.generate(sample_store, run_store, quota=5)
    assert draft["id"] not in view["universe_run_ids"]
    assert view["filled"] == 3


def test_diff_group_leads_with_reason(stores):
    sample_store, run_store = stores
    two_batches(run_store)
    view = service.generate(sample_store, run_store, quota=5)
    first = view["selections"][0]
    assert first["group_key"] == "M1|2026-11-01"
    assert first["reason_code"] == "CROSS_BATCH_DIFF"
    assert "300" in first["reason_detail"]


def test_retry_does_not_add_or_duplicate(stores):
    sample_store, run_store = stores
    two_batches(run_store)
    first = service.generate(sample_store, run_store, quota=3)
    second = service.generate(sample_store, run_store, quota=3)
    assert [s["group_key"] for s in first["selections"]] == [s["group_key"] for s in second["selections"]]
    assert second["filled"] == first["filled"] == 3
    assert sample_store.count_selections(first["period_id"]) == 3
    assert second["plan_digest"] == first["plan_digest"]


def test_generation_is_resumable_after_interruption(stores, monkeypatch):
    sample_store, run_store = stores
    two_batches(run_store)
    # 模拟在写入第二条入样记录后中断：只保留第一条。
    view = service.generate(sample_store, run_store, quota=3)
    period_id = view["period_id"]
    with sample_store.connect() as db:
        db.execute("DELETE FROM sample_selections WHERE period_id=? AND rank_no>=1", (period_id,))
    assert sample_store.count_selections(period_id) == 1

    resumed = service.generate(sample_store, run_store, quota=3)
    assert resumed["period_id"] == period_id
    assert resumed["filled"] == 3
    keys = [s["group_key"] for s in resumed["selections"]]
    # 恢复后名单与一次跑完完全一致，且无重复。
    assert keys == [s["group_key"] for s in view["selections"]]
    assert len(set(keys)) == len(keys)


def test_newly_signed_batch_waits_for_next_period(stores):
    sample_store, run_store = stores
    r1, _ = two_batches(run_store)
    view = service.generate(sample_store, run_store, quota=3)
    published = service.publish(sample_store, run_store)
    assert published["status"] == PERIOD_PUBLISHED

    # 发布后新签发的批次带一个全新组。
    late = make_group("M9|2026-11-09", "M9", "2026-11-09", ["SELF"], 999)
    late_run_id = seed_approved_run(run_store, "key-late", [late])

    # 旧周期仍可核对当时依据，且不包含新批次。
    old = service.get_period_view(sample_store, view["period_id"])
    assert "M9|2026-11-09" not in {s["group_key"] for s in old["selections"]}
    assert late_run_id not in old["universe_run_ids"]

    # 再生成会开启下一周期，把新批次纳入。
    next_view = service.generate(sample_store, run_store, quota=5)
    assert next_view["period_id"] != view["period_id"]
    assert late_run_id in next_view["universe_run_ids"]
    assert "M9|2026-11-09" in {s["group_key"] for s in next_view["selections"]}


def test_published_period_cannot_be_reopened(stores):
    sample_store, run_store = stores
    two_batches(run_store)
    service.generate(sample_store, run_store, quota=3)
    service.publish(sample_store, run_store)
    # 已发布周期不再是 open 周期，generate 会另开新周期而不是改动旧周期。
    new_view = service.generate(sample_store, run_store, quota=3)
    periods = service.list_periods(sample_store)
    assert len(periods) == 2
    assert periods[1]["status"] == PERIOD_PUBLISHED
    assert new_view["status"] == PERIOD_BUILDING


def test_evidence_snapshot_keeps_payment_basis(stores):
    sample_store, run_store = stores
    r1, r2 = two_batches(run_store)
    view = service.generate(sample_store, run_store, quota=3)
    diff = view["selections"][0]
    evidence = diff["evidence"]
    assert evidence["payment_gap"] == 300
    run_ids = {item["run_id"] for item in evidence["batch_evidence"]}
    assert run_ids == {r1, r2}
    # 每条快照都保留来源摘要与各支付方给付明细。
    for item in evidence["batch_evidence"]:
        assert item["source_sha256"]
        assert item["payments"] and all("payer" in p for p in item["payments"])


def test_quota_caps_the_list(stores):
    sample_store, run_store = stores
    two_batches(run_store)
    view = service.generate(sample_store, run_store, quota=2)
    assert view["quota"] == 2
    assert view["filled"] == 2


def test_generate_without_approved_batches(stores):
    sample_store, run_store = stores
    view = service.generate(sample_store, run_store, quota=5)
    assert view["filled"] == 0
    assert view["selections"] == []


def test_workbench_can_read_reason_for_each_selection(stores):
    sample_store, run_store = stores
    two_batches(run_store)
    view = service.generate(sample_store, run_store, quota=3)
    for item in view["selections"]:
        assert item["reason_code"]
        assert item["reason_detail"]
        assert item["evidence"]["group_key"] == item["group_key"]
