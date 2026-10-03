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

1. 在「点位」「货道」查看售货机布局与库存，可就地保存货道容量。
2. 在「销量」了解近期出货。
3. 打开「补货单」按缺口生成建议补货量，可逐行手改补量并「核销落库」。
4. 在「满仓」「汇总」查看已满货道与补货合计。

## 失败契约（成功/失败严格互斥）

- 失败回包**且仅且**三字段：`error_code`（原因码）、`object_id`（对象标识）、`message`（说明全文）；
  接口回包、补货单页错误条、货道页错误条读同一条落库失败记录（`GET /api/failures/latest`），三口同字。
- 成功回包禁止出现上述任一字段；页面禁止把成功画成失败条。
- 失败一律走信封：生成被拒（存在超占货道 `GEN_OVERBOOKED`）、手改超缺口（`MANUAL_OVER_GAP`）、
  手改数量非法（`MANUAL_QTY_INVALID`）、重复核销（`REDEEM_ALREADY_REDEEMED`）、
  核销会超容量（`REDEEM_EXCEEDS_CAPACITY`）、非法容量保存（`INVALID_CAPACITY`）。
- 失败先整体回滚再落失败记录：不留半成功补货单行、不半改库存（核销前逐行预检，任一超容量则全部不改）。
- 说明超过 80 字落库即截短并追加「说明漂移」；页面逐字显示截短文本，不补全、不写回。

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/refills/run?location_id=` | POST | 生成补货单（超占则 422 信封） |
| `/api/refills/orders/{id}/manual-edit` | POST | `{"lines":[{"lane_id":1,"fill_qty":3}]}` |
| `/api/refills/orders/{id}/redeem` | POST | 核销落库存（重复 409，超容量 409） |
| `/api/lanes/{id}/capacity` | PATCH | `{"capacity":20}`（非法 422 信封） |
| `/api/failures/latest?location_id=` | GET | 最近一条失败落单，无则 `{"failure":null}` |

## 开发与测试

```bash
docker compose exec api pytest -q
```

测试可用内存 sqlite 直接运行：

```bash
DATABASE_URL='sqlite:///:memory:' SEED_ON_EMPTY=false pytest -q
```
