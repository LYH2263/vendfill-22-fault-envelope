"""失败/成功互斥、三字段信封、原子性、截短漂移、三口同字。"""
import json
import os

# 必须在导入 app.* 之前：让全局 engine/settings 也指向 sqlite（lifespan 才不会连 Postgres）
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SEED_ON_EMPTY", "false")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import Base, SessionLocal, get_db
from app.main import app
from app.models.models import FailureRecord, Lane, RefillOrder
from app.services import reasons as R
from app.services.envelope import ERROR_FIELDS
from app.services.fill_engine import build_fill_lines, compute_gap, summarize

# ---- 内存 sqlite（database.py 对 sqlite 自动启用 StaticPool）----
from app.database import Base, SessionLocal, engine as app_engine
TestingSessionLocal = SessionLocal


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=app_engine)
    Base.metadata.create_all(bind=app_engine)
    db = TestingSessionLocal()
    # 复刻种子数据（含超占 C2 与历史单、两条失败落单）
    from app.services.seed import seed_if_empty
    seed_if_empty(db)
    db.close()

    def override_get_db():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def snapshot(db):
    """失败前后的持久化状态：补货单数 + 各货道(stock,in_transit,capacity)。"""
    orders = db.scalars(select(RefillOrder).order_by(RefillOrder.id)).all()
    lanes = db.scalars(select(Lane).order_by(Lane.id)).all()
    return (
        [(o.id, o.redeemed_at) for o in orders],
        {l.id: (l.stock, l.in_transit, l.capacity) for l in lanes},
    )


def assert_envelope(body):
    assert set(body.keys()) == set(ERROR_FIELDS)
    assert isinstance(body["error_code"], str) and body["error_code"]
    assert isinstance(body["object_id"], str) and body["object_id"]
    assert isinstance(body["message"], str) and body["message"]
    # 成功字段绝不许混进失败信封
    for forbidden in ("lines", "total_fill", "id", "redeemed_at"):
        assert forbidden not in body
    return body


# ---------- 纯引擎既有行为不回归 ----------

def test_gap_basic():
    assert compute_gap(20, 5, 0) == 15
    assert compute_gap(20, 10, 5) == 5

def test_no_negative_fill():
    lines = build_fill_lines([{"id": 1, "slot_no": "A1", "sku_name": "水",
                               "capacity": 10, "stock": 12, "in_transit": 0}])
    assert lines[0].fill_qty == 0 and lines[0].status == "overbooked"

def test_cap_by_gap():
    lines = build_fill_lines([{"id": 1, "slot_no": "A1", "sku_name": "水",
                               "capacity": 20, "stock": 5, "in_transit": 0}], requested={1: 100})
    assert lines[0].fill_qty == 15

def test_full_zero_fill():
    s = summarize(build_fill_lines([{"id": 1, "slot_no": "A1", "sku_name": "水",
                                    "capacity": 10, "stock": 8, "in_transit": 2}]))
    assert s["full_count"] == 1 and s["total_fill"] == 0


# ---------- 生成被拒 ----------

def test_generate_rejected_three_fields(client):
    r = client.post("/api/refills/run?location_id=1")
    assert r.status_code == 422
    env = assert_envelope(r.json())
    assert env["error_code"] == R.GEN_OVERBOOKED
    assert env["object_id"] == "lane:6"          # C2
    assert env["message"].startswith("生成被拒")

def test_generate_rejection_is_atomic_and_persisted(client):
    db = TestingSessionLocal()
    before = snapshot(db)
    r = client.post("/api/refills/run?location_id=1")
    assert r.status_code == 422
    db.rollback()
    after = snapshot(db)
    # 补货单数与库存相对失败前不变（种子历史单仍在，无新单）
    assert after == before
    rec = db.scalars(select(FailureRecord).where(
        FailureRecord.scene == R.SCENE_GENERATE).order_by(FailureRecord.id.desc())).first()
    assert rec is not None
    body = r.json()
    # 回包与落库三字段逐字一致
    assert (rec.error_code, rec.object_id, rec.message) == (
        body["error_code"], body["object_id"], body["message"])
    db.close()

def test_seed_has_one_of_each_failure_and_three_mouths_same_text(client):
    db = TestingSessionLocal()
    gen = db.scalars(select(FailureRecord).where(
        FailureRecord.scene == R.SCENE_GENERATE)).all()
    man = db.scalars(select(FailureRecord).where(
        FailureRecord.scene == R.SCENE_MANUAL)).all()
    assert len(gen) == 1 and len(man) == 1
    # 种子生成失败与现场再生成被拒的回包同字
    r = client.post("/api/refills/run?location_id=1")
    body = r.json()
    assert body["message"] == gen[0].message
    assert body["error_code"] == gen[0].error_code
    # /failures/latest 与信封同字（三口同字：回包、补货单页取数、货道页取数）
    latest = client.get("/api/failures/latest?location_id=1").json()["failure"]
    assert (latest["error_code"], latest["object_id"], latest["message"]) == (
        body["error_code"], body["object_id"], body["message"])
    latest_any_scene = client.get(
        "/api/failures/latest?location_id=1&scenes=generate,capacity").json()["failure"]
    assert latest_any_scene["message"] == body["message"]
    db.close()


# ---------- 解除超占后的成功路径 ----------

def test_success_has_no_fake_error_code(client):
    db = TestingSessionLocal()
    c2 = db.scalars(select(Lane).where(Lane.slot_no == "C2")).one()
    c2.in_transit = 0          # 解除超占
    db.commit(); db.close()
    r = client.post("/api/refills/run?location_id=1")
    assert r.status_code == 200
    body = r.json()
    for f in ERROR_FIELDS:
        assert f not in body
    assert body["total_fill"] > 0
    assert all("error_code" not in l for l in body["lines"])


# ---------- 手改超缺口 ----------

def _seeded_order_id(db):
    return db.scalars(select(RefillOrder).order_by(RefillOrder.id)).first().id

def test_manual_over_gap_rejected_atomic(client):
    db = TestingSessionLocal()
    order_id = _seeded_order_id(db)
    a1 = db.scalars(select(Lane).where(Lane.slot_no == "A1")).one()
    before = snapshot(db)
    original_json = db.get(RefillOrder, order_id).lines_json
    # A1 缺口 15，手改 16
    r = client.post(f"/api/refills/orders/{order_id}/manual-edit",
                    json={"lines": [{"lane_id": a1.id, "fill_qty": 16}]})
    assert r.status_code == 422
    env = assert_envelope(r.json())
    assert env["error_code"] == R.MANUAL_OVER_GAP
    assert env["object_id"] == f"lane:{a1.id}"
    assert env["message"].startswith("手改失败")
    db.rollback()
    assert snapshot(db) == before
    # 单内容也未被半改
    db.expire_all()
    assert db.get(RefillOrder, order_id).lines_json == original_json
    db.close()

def test_manual_invalid_qty_envelope(client):
    db = TestingSessionLocal()
    order_id = _seeded_order_id(db)
    a1 = db.scalars(select(Lane).where(Lane.slot_no == "A1")).one()
    for bad in (-1, 1.5, "x", True, None):
        r = client.post(f"/api/refills/orders/{order_id}/manual-edit",
                        json={"lines": [{"lane_id": a1.id, "fill_qty": bad}]})
        assert r.status_code == 422
        env = assert_envelope(r.json())
        assert env["error_code"] in (R.MANUAL_QTY_INVALID, R.BAD_REQUEST)
    db.close()

def test_manual_success_within_gap(client):
    db = TestingSessionLocal()
    order_id = _seeded_order_id(db)
    a1 = db.scalars(select(Lane).where(Lane.slot_no == "A1")).one()
    r = client.post(f"/api/refills/orders/{order_id}/manual-edit",
                    json={"lines": [{"lane_id": a1.id, "fill_qty": 3}]})
    assert r.status_code == 200
    body = r.json()
    for f in ERROR_FIELDS:
        assert f not in body
    line = next(l for l in body["lines"] if l["lane_id"] == a1.id)
    assert line["fill_qty"] == 3
    # 手改不落库存
    db.expire_all()
    assert db.get(Lane, a1.id).stock == 5
    db.close()


# ---------- 核销 ----------

def test_redeem_success_then_conflict(client):
    db = TestingSessionLocal()
    c2 = db.scalars(select(Lane).where(Lane.slot_no == "C2")).one()
    c2.in_transit = 0
    db.commit()
    r = client.post("/api/refills/run?location_id=1")
    order_id = r.json()["id"]
    before_stock = {l.id: l.stock for l in db.scalars(select(Lane)).all()}
    db.close()

    ok = client.post(f"/api/refills/orders/{order_id}/redeem")
    assert ok.status_code == 200
    assert ok.json()["redeemed_at"] is not None

    # 重复核销冲突：三字段信封
    dup = client.post(f"/api/refills/orders/{order_id}/redeem")
    assert dup.status_code == 409
    env = assert_envelope(dup.json())
    assert env["error_code"] == R.REDEEM_ALREADY
    assert env["message"].startswith("核销冲突")

    # 重复核销没有二次加库存
    db = TestingSessionLocal()
    after = {l.id: l.stock for l in db.scalars(select(Lane)).all()}
    expected = {}
    first = json.loads(db.get(RefillOrder, order_id).lines_json)
    # 第一次核销的增加恰好一次
    for l in first["lines"]:
        expected[l["lane_id"]] = before_stock[l["lane_id"]] + l["fill_qty"]
    assert after == expected
    db.close()

def test_redeem_exceeds_capacity_rolls_back_all(client):
    db = TestingSessionLocal()
    order_id = _seeded_order_id(db)
    # 把历史单 A1 的 fill 改到必超容量，同时保证另一行也有补量：
    # 直接构造一个会超容量的单：A1 容量20 库存5，填 21 必超；B1 填 7（缺口7）正常
    order = db.get(RefillOrder, order_id)
    data = json.loads(order.lines_json)
    for l in data["lines"]:
        if l["slot_no"] == "A1":
            l["fill_qty"] = 21
        if l["slot_no"] == "B1":
            l["fill_qty"] = 7
    order.lines_json = json.dumps(data, ensure_ascii=False)
    db.commit()
    before = snapshot(db)
    db.close()

    r = client.post(f"/api/refills/orders/{order_id}/redeem")
    assert r.status_code == 409
    env = assert_envelope(r.json())
    assert env["error_code"] == R.REDEEM_EXCEEDS
    assert env["object_id"] == "lane:1"
    assert "整体回滚" in env["message"]

    db = TestingSessionLocal()
    # B1 也不许被半核销
    assert snapshot(db) == before
    assert db.get(RefillOrder, order_id).redeemed_at is None
    db.close()


# ---------- 非法容量 ----------

def test_invalid_capacity_types(client):
    db = TestingSessionLocal()
    a1 = db.scalars(select(Lane).where(Lane.slot_no == "A1")).one()
    before = snapshot(db)
    for bad in (0, -3, "abc", True, 1.5):
        r = client.patch(f"/api/lanes/{a1.id}/capacity", json={"capacity": bad})
        assert r.status_code == 422
        env = assert_envelope(r.json())
        assert env["error_code"] == R.CAP_INVALID
    db.rollback()
    assert snapshot(db) == before
    db.close()

def test_capacity_below_holdings_rejected(client):
    db = TestingSessionLocal()
    a1 = db.scalars(select(Lane).where(Lane.slot_no == "A1")).one()  # stock5
    before = snapshot(db)
    r = client.patch(f"/api/lanes/{a1.id}/capacity", json={"capacity": 4})
    assert r.status_code == 422
    env = assert_envelope(r.json())
    assert env["error_code"] == R.CAP_INVALID
    assert "低于库存" in env["message"]
    db.rollback()
    assert snapshot(db) == before
    db.close()

def test_capacity_valid_success_no_code(client):
    db = TestingSessionLocal()
    a1 = db.scalars(select(Lane).where(Lane.slot_no == "A1")).one()
    r = client.patch(f"/api/lanes/{a1.id}/capacity", json={"capacity": 30})
    assert r.status_code == 200
    body = r.json()
    for f in ERROR_FIELDS:
        assert f not in body
    assert body["capacity"] == 30
    db.close()


# ---------- 截短与说明漂移 ----------

def test_truncated_message_persists_and_reopens(client):
    db = TestingSessionLocal()
    order_id = _seeded_order_id(db)
    a1 = db.scalars(select(Lane).where(Lane.slot_no == "A1")).one()
    r = client.post(f"/api/refills/orders/{order_id}/manual-edit",
                    json={"lines": [{"lane_id": a1.id, "fill_qty": 16}]})
    body = assert_envelope(r.json())
    # 截短后仍带漂移标记，且就是落库/回包的最终文本
    assert body["message"].endswith("说明漂移")
    assert len(body["message"]) <= 80

    # 重新打开（latest 取数）：仍是截短文本、仍带漂移
    latest = client.get("/api/failures/latest?location_id=1").json()["failure"]
    assert latest["message"] == body["message"]
    assert latest["message"].endswith("说明漂移")
    assert latest["drifted"] is True

    rec = db.get(FailureRecord, latest["id"])
    assert rec.message == body["message"]
    assert rec.drifted is True
    db.close()

def test_seed_manual_failure_is_truncated_drift(client):
    db = TestingSessionLocal()
    rec = db.scalars(select(FailureRecord).where(
        FailureRecord.scene == R.SCENE_MANUAL)).one()
    assert rec.drifted is True
    assert rec.message.endswith("说明漂移")
    assert len(rec.message) <= 80
    db.close()


def test_seed_manual_failure_same_text_as_live_rejection(client):
    db = TestingSessionLocal()
    rec = db.scalars(select(FailureRecord).where(
        FailureRecord.scene == R.SCENE_MANUAL)).one()
    order_id = _seeded_order_id(db)
    a1 = db.scalars(select(Lane).where(Lane.slot_no == "A1")).one()
    db.close()
    r = client.post(f"/api/refills/orders/{order_id}/manual-edit",
                    json={"lines": [{"lane_id": a1.id, "fill_qty": 16}]})
    body = assert_envelope(r.json())
    # 种子手改失败、现场拒绝回包、/failures/latest 三处同字
    assert (body["error_code"], body["object_id"], body["message"]) == (
        rec.error_code, rec.object_id, rec.message)
    latest = client.get(
        "/api/failures/latest?location_id=1&scene=manual_edit").json()["failure"]
    assert latest["message"] == rec.message


# ---------- 404 也走信封，不允许无码串 ----------

def test_not_found_is_envelope(client):
    r = client.post("/api/refills/run?location_id=999")
    assert r.status_code == 404
    env = assert_envelope(r.json())
    assert env["error_code"] == R.LOCATION_NOT_FOUND

def test_validation_error_is_envelope(client):
    # 缺 body / 坏 JSON 也不许回 FastAPI 默认 detail 串
    db = TestingSessionLocal()
    order_id = _seeded_order_id(db)
    db.close()
    r = client.post(f"/api/refills/orders/{order_id}/manual-edit",
                    content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422
    env = assert_envelope(r.json())
    assert env["error_code"] == R.BAD_REQUEST
