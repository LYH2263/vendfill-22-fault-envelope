# VendFill 售货机补货

按货道容量、库存与在途量计算缺口，生成不超缺口、非负的补货单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4800 |
| API | http://localhost:9800 |
| API 文档 | http://localhost:9800/docs |
| Postgres | localhost:5449 |

健康检查：`GET http://localhost:9800/api/health`

## 使用说明

1. 在「点位」「货道」查看售货机布局与库存；货道页可保存容量（非法容量走失败信封）。
2. 在「销量」了解近期出货。
3. 打开「补货小票」按缺口生成建议补货单，可手改补量（不得超缺口）并核销落库。
4. 在「满仓」「汇总」查看已满货道与补货合计。

## 失败与成功互斥契约

- **成功**：回包只含业务字段（补货单/货道），**禁止**出现 `code`/`subject`/`detail`，页面也不画失败条。
- **失败**：回包恒为三字段信封，字段集与顺序固定，**禁止**只回无码字符串：
  ```json
  { "code": "manual_over_gap", "subject": "C1（能量棒）", "detail": "手改超缺口：……" }
  ```
  接口回包、补货小票页、货道页错误条逐字段同一套（落库流水与回包同源）。
- 失败一律先校验、后落库：**不得**留下半成功补货单行或半改库存。
  - `generation_rejected` 生成被拒（存在缺口为负的超占货道）
  - `manual_over_gap` 手改补量超缺口或为负
  - `fulfill_conflict` 核销时库存/在途已相对生成快照变化（含重复核销）
  - `invalid_capacity` 容量非正整数或低于「库存+在途」
  - 框架层入参非法为 `bad_request`，路由不存在为 `not_found`，同样是三字段信封。
- **说明漂移**：说明全文真源在后端 `app/services/errors.py`（前端 `errors.ts` 仅只读镜像）。
  落库/回包的 `detail` 可能按长度上限截短；页面照显截短串，与全文不一致时标「说明漂移」，
  **禁止**前端补全或写回。

### 相关接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/refills/run?location_id=` | 生成补货单（超占则 `generation_rejected`） |
| GET | `/api/refills/latest?location_id=` | 最近一张单（无单返回 `null`，不自动补单） |
| POST | `/api/refills/{id}/adjust` | 手改补量，body `{"fills": {lane_id: qty}}` |
| POST | `/api/refills/{id}/fulfill` | 核销落库（冲突则 `fulfill_conflict`） |
| PUT | `/api/lanes/{id}` | 保存容量，body `{"capacity": n}` |
| GET | `/api/refills/last-failure?location_id=` | 最近失败三字段（无则 `null`） |
| GET | `/api/refills/failures?location_id=&action=` | 失败流水（仅回三字段） |

## 开发与测试

```bash
docker compose exec api pytest -q
```

本地（SQLite，无需 Postgres）：

```bash
cd backend
pytest -q                       # 含信封形状、截短/漂移、原子性、种子、前后端镜像一致性
```
