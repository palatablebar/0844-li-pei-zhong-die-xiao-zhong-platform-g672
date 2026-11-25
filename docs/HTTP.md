# 接口

- `GET /`：工作台。
- `GET /api/catalog`：阶段、字段和样例。
- `POST /api/stages/{stage}`：按阶段返回处理结果。
- `POST /api/runs`：执行完整批次并保存草稿。
- `GET /api/runs/{id}`：读取批次。
- `POST /api/runs/{id}/review`：签发或暂缓，提交 `decision`、`comment`、`expected_revision`。
- `GET /api/runs/{id}/evidence`：下载已签发证据。
- `GET /api/examples/{profile}`：下载样例。
- `POST /api/sampling/generate`：生成或续跑当前抽检周期，提交可选 `quota`（默认 5）。
- `POST /api/sampling/publish`：发布当前周期名单并冻结。
- `GET /api/sampling/periods`：抽检周期列表。
- `GET /api/sampling/periods/current`：当前周期，含每个入样组的原因与给付依据快照。
- `GET /api/sampling/periods/{id}`：单个周期详情。
- `GET /healthz`：健康检查。
