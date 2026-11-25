"""抽检工作台接口。

- ``POST /api/sampling/generate``：生成/续跑当前周期（中断可恢复，重试不新增）。
- ``POST /api/sampling/publish``：发布名单，冻结当期，之后新批次留到下期。
- ``GET  /api/sampling/periods``：周期列表。
- ``GET  /api/sampling/periods/current``：当前周期与入样原因。
- ``GET  /api/sampling/periods/<id>``：单个周期（含每个组的给付依据快照）。
"""
from flask import Blueprint, jsonify, request

from app.errors import DomainIssue
from app.sampling import service
from app.sampling.service import DEFAULT_QUOTA

sampling = Blueprint("sampling", __name__)


def stores():
    from flask import current_app
    return current_app.extensions["sampling"], current_app.extensions["runs"]


@sampling.post("/api/sampling/generate")
def generate():
    sample_store, run_store = stores()
    data = request.get_json(silent=True) or {}
    raw_quota = data.get("quota")
    if raw_quota is None:
        quota = DEFAULT_QUOTA
    else:
        try:
            quota = int(raw_quota)
        except (TypeError, ValueError):
            raise DomainIssue("BAD_REQUEST")
    if quota <= 0:
        raise DomainIssue("BAD_REQUEST")
    view = service.generate(sample_store, run_store, quota=quota)
    return jsonify(view)


@sampling.post("/api/sampling/publish")
def publish():
    sample_store, run_store = stores()
    if sample_store.open_period() is None:
        raise DomainIssue("PERIOD_NOT_OPEN", 409)
    view = service.publish(sample_store, run_store)
    return jsonify(view)


@sampling.get("/api/sampling/periods")
def periods():
    sample_store, _ = stores()
    return jsonify(periods=service.list_periods(sample_store))


@sampling.get("/api/sampling/periods/current")
def current():
    sample_store, _ = stores()
    view = service.current_period(sample_store)
    if view is None:
        raise DomainIssue("PERIOD_NOT_FOUND", 404)
    return jsonify(view)


@sampling.get("/api/sampling/periods/<period_id>")
def one(period_id):
    sample_store, _ = stores()
    view = service.get_period_view(sample_store, period_id)
    if view is None:
        raise DomainIssue("PERIOD_NOT_FOUND", 404)
    return jsonify(view)
