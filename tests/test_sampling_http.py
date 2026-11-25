from tests.sampling_factory import make_group, seed_approved_run


def approve_clean(client):
    run = client.post("/api/runs", json={"profile": "clean"}).get_json()
    client.post(
        f"/api/runs/{run['run_id']}/review",
        json={"decision": "APPROVED", "comment": "签发", "expected_revision": 0},
    )
    return run


def seed_two_batches(client, run_store):
    g1a = make_group("M1|2026-11-01", "M1", "2026-11-01", ["MEDICARE", "PRIVATE"], 1000)
    g1b = make_group("M1|2026-11-01", "M1", "2026-11-01", ["MEDICARE", "PRIVATE"], 1300)
    g2 = make_group("M2|2026-11-02", "M2", "2026-11-02", ["SELF"], 400)
    r1 = seed_approved_run(run_store, "http-r1", [g1a, g2])
    r2 = seed_approved_run(run_store, "http-r2", [g1b])
    return r1, r2


def test_current_period_404_when_none(client):
    response = client.get("/api/sampling/periods/current")
    assert response.status_code == 404
    assert response.get_json()["code"] == "PERIOD_NOT_FOUND"


def test_generate_creates_period_from_approved_runs(client):
    approve_clean(client)
    response = client.post("/api/sampling/generate", json={"quota": 5})
    assert response.status_code == 200
    view = response.get_json()
    assert view["status"] == "BUILDING"
    assert view["quota"] == 5
    assert view["filled"] >= 1
    assert view["selections"][0]["reason_code"]
    assert view["selections"][0]["reason_detail"]


def test_generate_is_idempotent_over_http(client):
    approve_clean(client)
    first = client.post("/api/sampling/generate", json={"quota": 5}).get_json()
    second = client.post("/api/sampling/generate", json={"quota": 5}).get_json()
    assert first["period_id"] == second["period_id"]
    assert [s["group_key"] for s in first["selections"]] == [
        s["group_key"] for s in second["selections"]
    ]


def test_default_quota_when_body_omitted(client):
    approve_clean(client)
    view = client.post("/api/sampling/generate", json={}).get_json()
    assert view["quota"] == 5


def test_bad_quota_rejected(client):
    approve_clean(client)
    response = client.post("/api/sampling/generate", json={"quota": 0})
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_REQUEST"


def test_publish_freezes_period(client):
    approve_clean(client)
    client.post("/api/sampling/generate", json={"quota": 5})
    response = client.post("/api/sampling/publish", json={})
    assert response.status_code == 200
    assert response.get_json()["status"] == "PUBLISHED"
    assert response.get_json()["published_at"]


def test_publish_without_open_period_conflicts(client):
    response = client.post("/api/sampling/publish", json={})
    assert response.status_code == 409
    assert response.get_json()["code"] == "PERIOD_NOT_OPEN"


def test_period_listing_and_detail(client):
    approve_clean(client)
    created = client.post("/api/sampling/generate", json={"quota": 3}).get_json()
    listing = client.get("/api/sampling/periods").get_json()["periods"]
    assert any(p["period_id"] == created["period_id"] for p in listing)
    detail = client.get(f"/api/sampling/periods/{created['period_id']}").get_json()
    assert detail["period_no"] == created["period_no"]
    assert len(detail["selections"]) == created["filled"]


def test_unknown_period_returns_404(client):
    response = client.get("/api/sampling/periods/nope123")
    assert response.status_code == 404


def test_diff_reason_visible_in_workbench_payload(client):
    run_store = client.application.extensions["runs"]
    seed_two_batches(client, run_store)
    view = client.post("/api/sampling/generate", json={"quota": 5}).get_json()
    first = view["selections"][0]
    assert first["reason_code"] == "CROSS_BATCH_DIFF"
    assert first["evidence"]["payment_gap"] == 300
    # 工作台能查到入样原因与给付依据快照。
    assert first["reason_detail"]
    assert len(first["evidence"]["batch_evidence"]) == 2


def test_pipeline_payload_carries_group_payments(client):
    run = client.post("/api/runs", json={"profile": "clean"}).get_json()
    assert run["group_payments"], "签发批次应携带结构化理赔组给付数据"
    entry = run["group_payments"][0]
    assert {"group_key", "payers", "payment_total", "payments"} <= set(entry)
