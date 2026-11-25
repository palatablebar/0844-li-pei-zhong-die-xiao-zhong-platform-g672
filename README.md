# 理赔重叠消重台

医保理赔审核员处理重叠消重与支付方顺序的本地工作台。样例、规则和复核记录都在项目内，不依赖外部服务。

## 启动

```bash
docker compose up --build
```

打开 `http://127.0.0.1:${PORT:-18520}`。默认端口见 `docker-compose.yml`。

## 验证

```bash
docker compose exec -T app pytest -q
docker compose config --quiet
```

## 操作

1. 在左侧选阶段，查看采信、整理、计算、判定和对账结果。
2. 选择 `dirty` 样例观察坏行和隔离原因。
3. 换 `clean` 样例执行批次，填写复核意见后签发。
4. 下载证据 JSON，核对来源摘要、指标和签发版本。
5. 先签发一个或多个批次，再在「抽检名单」面板生成抽检：差异组强制先入样，其余名额按支付方覆盖补齐；可中断续跑，发布后当期冻结、新批次留到下期。

业务规则见 `docs/BUSINESS-RULES.md`，字段定义见 `docs/DATA-DICTIONARY.md`。
