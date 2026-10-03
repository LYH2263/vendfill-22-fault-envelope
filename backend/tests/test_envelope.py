"""失败信封：三字段、无码串禁止混用、截短与漂移、半成功禁止。"""
import pytest

from app.models.models import Lane, RefillFailure, RefillOrder
from app.services import errors
from app.services.errors import (
    FULFILL_CONFLICT,
    GENERATION_REJECTED,
    INVALID_CAPACITY,
    MANUAL_OVER_GAP,
)
from tests.factories import make_lane, make_location, snapshot_stocks


# ---------- 信封形状 ----------

def test_envelope_exactly_three_fields():
    env = errors.fail(GENERATION_REJECTED, "VM-01（地铁口 A 点位）").to_envelope()
    assert set(env.keys()) == {"code", "subject", "detail"}
    assert env["code"] == GENERATION_REJECTED
    assert env["subject"] == "VM-01（地铁口 A 点位）"
    assert isinstance(env["detail"], str) and env["detail"]


def test_detail_is_truncated_and_marked_by_full_mismatch():
    code = GENERATION_REJECTED
    subject = "VM-01（地铁口 A 点位）"
    short = errors.render_detail(code, subject)
    full = errors.DETAIL_FULL[code].format(subject=subject)
    assert len(short) == errors.DETAIL_MAXLEN
    assert short.endswith(errors.TRUNC_MARK)
    assert short != full  # 前端据此判「说明漂移」
    assert short == full[: errors.DETAIL_MAXLEN - 1] + "…"


def test_short_detail_not_truncated():
    # 不存在类说明较短，不应截短、不应漂移。
    short = errors.render_detail(errors.LANE_NOT_FOUND, "货道#7")
    full = errors.DETAIL_FULL[errors.LANE_NOT_FOUND].format(subject="货道#7")
    assert short == full
    assert not short.endswith("…")


# ---------- 生成被拒 ----------

def test_generate_rejected_on_overbook(db, client):
    loc = make_location(db)
    make_lane(db, loc.id, slot="C2", sku="口香糖", capacity=24, stock=24, in_transit=2)
    db.commit()
    before_orders = db.query(RefillOrder).count()
    before = snapshot_stocks(db)

    r = client.post("/api/refills/run", params={"location_id": loc.id})
    assert r.status_code == 422
    env = r.json()
    assert set(env.keys()) == {"code", "subject", "detail"}
    assert env["code"] == GENERATION_REJECTED
    assert env["subject"] == "VM-01（地铁口 A 点位）"
    assert env["detail"].endswith("…")  # 截短说明

    # 失败留痕一条，且与回包逐字段同源；不留下补货单行、库存不变。
    rows = db.query(RefillFailure).all()
    assert len(rows) == 1
    assert (rows[0].code, rows[0].subject, rows[0].detail) == (
        env["code"], env["subject"], env["detail"])
    assert db.query(RefillOrder).count() == before_orders
    assert snapshot_stocks(db) == before


def test_generate_success_has_no_code_fields(db, client):
    loc = make_location(db)
    make_lane(db, loc.id, capacity=20, stock=5, in_transit=0)
    db.commit()
    r = client.post("/api/refills/run", params={"location_id": loc.id})
    assert r.status_code == 200
    body = r.json()
    assert not ({ "code", "subject", "detail" } & set(body.keys()))
    assert body["status"] == "draft"
    assert body["lines"][0]["fill_qty"] == 15


# ---------- 手改超缺口 ----------

def test_manual_over_gap_rejected_atomically(db, client):
    loc = make_location(db)
    lane = make_lane(db, loc.id, slot="A1", capacity=20, stock=5, in_transit=0)
    db.commit()
    # 先生成一张草稿
    ok = client.post("/api/refills/run", params={"location_id": loc.id})
    order_id = ok.json()["id"]
    original_lines = db.get(RefillOrder, order_id).lines_json
    before = snapshot_stocks(db)
    before_failures = db.query(RefillFailure).count()

    r = client.post(f"/api/refills/{order_id}/adjust", json={"fills": {str(lane.id): 16}})
    assert r.status_code == 422
    env = r.json()
    assert set(env.keys()) == {"code", "subject", "detail"}
    assert env["code"] == MANUAL_OVER_GAP
    assert env["subject"] == "A1（矿泉水）"
    assert env["detail"].endswith("…")

    # 单行数（补货单行 JSON）不变、库存不变；只新增一条失败流水。
    db.expire_all()
    assert db.get(RefillOrder, order_id).lines_json == original_lines
    assert snapshot_stocks(db) == before
    assert db.query(RefillFailure).count() == before_failures + 1
    row = db.query(RefillFailure).filter(RefillFailure.action == "manual_edit").one()
    assert (row.code, row.subject, row.detail) == tuple(env[k] for k in ("code", "subject", "detail"))


def test_manual_negative_rejected(db, client):
    loc = make_location(db)
    lane = make_lane(db, loc.id, capacity=20, stock=5, in_transit=0)
    db.commit()
    order_id = client.post("/api/refills/run", params={"location_id": loc.id}).json()["id"]
    r = client.post(f"/api/refills/{order_id}/adjust", json={"fills": {str(lane.id): -1}})
    assert r.status_code == 422
    assert r.json()["code"] == MANUAL_OVER_GAP


def test_manual_within_gap_succeeds_without_code(db, client):
    loc = make_location(db)
    lane = make_lane(db, loc.id, capacity=20, stock=5, in_transit=0)
    db.commit()
    order_id = client.post("/api/refills/run", params={"location_id": loc.id}).json()["id"]
    r = client.post(f"/api/refills/{order_id}/adjust", json={"fills": {str(lane.id): 3}})
    assert r.status_code == 200
    body = r.json()
    assert not ({ "code", "subject", "detail" } & set(body.keys()))
    line = next(l for l in body["lines"] if l["lane_id"] == lane.id)
    assert line["fill_qty"] == 3


# ---------- 核销冲突 ----------

def test_fulfill_conflict_changes_nothing(db, client):
    loc = make_location(db)
    lane = make_lane(db, loc.id, capacity=20, stock=5, in_transit=0)
    db.commit()
    order_id = client.post("/api/refills/run", params={"location_id": loc.id}).json()["id"]
    # 生成后、核销前改动库存 → 快照失效
    lane.stock = 6
    db.commit()
    before = snapshot_stocks(db)

    r = client.post(f"/api/refills/{order_id}/fulfill")
    assert r.status_code == 422
    env = r.json()
    assert set(env.keys()) == {"code", "subject", "detail"}
    assert env["code"] == FULFILL_CONFLICT

    # 无半改库存、单据仍是 draft。
    db.expire_all()
    assert db.get(RefillOrder, order_id).status == "draft"
    assert snapshot_stocks(db) == before


def test_fulfill_double_conflict(db, client):
    loc = make_location(db)
    make_lane(db, loc.id, capacity=20, stock=5, in_transit=0)
    db.commit()
    order_id = client.post("/api/refills/run", params={"location_id": loc.id}).json()["id"]
    first = client.post(f"/api/refills/{order_id}/fulfill")
    assert first.status_code == 200
    again = client.post(f"/api/refills/{order_id}/fulfill")
    assert again.status_code == 422
    assert again.json()["code"] == FULFILL_CONFLICT


def test_fulfill_success_updates_stock_once(db, client):
    loc = make_location(db)
    make_lane(db, loc.id, capacity=20, stock=5, in_transit=0)
    db.commit()
    order_id = client.post("/api/refills/run", params={"location_id": loc.id}).json()["id"]
    r = client.post(f"/api/refills/{order_id}/fulfill")
    assert r.status_code == 200
    assert r.json()["status"] == "fulfilled"
    db.expire_all()
    lane = db.query(Lane).one()
    assert lane.stock == 20  # 5 + 补 15


# ---------- 非法容量 ----------

def test_invalid_capacity_zero_rejected(db, client):
    loc = make_location(db)
    lane = make_lane(db, loc.id, capacity=20, stock=5, in_transit=0)
    db.commit()
    before = snapshot_stocks(db)
    r = client.put(f"/api/lanes/{lane.id}", json={"capacity": 0})
    assert r.status_code == 422
    env = r.json()
    assert set(env.keys()) == {"code", "subject", "detail"}
    assert env["code"] == INVALID_CAPACITY
    assert env["subject"] == "A1（矿泉水）"
    db.expire_all()
    assert snapshot_stocks(db) == before


def test_capacity_below_stock_plus_transit_rejected(db, client):
    loc = make_location(db)
    lane = make_lane(db, loc.id, capacity=20, stock=15, in_transit=4)
    db.commit()
    r = client.put(f"/api/lanes/{lane.id}", json={"capacity": 18})  # < 19
    assert r.status_code == 422
    assert r.json()["code"] == INVALID_CAPACITY


def test_capacity_wrong_type_is_coded_envelope(db, client):
    # 框架层入参非法也必须是有码信封，禁止 FastAPI 默认无码 422。
    loc = make_location(db)
    lane = make_lane(db, loc.id)
    db.commit()
    r = client.put(f"/api/lanes/{lane.id}", json={"capacity": "abc"})
    assert r.status_code == 400
    env = r.json()
    assert set(env.keys()) == {"code", "subject", "detail"}
    assert env["code"] == "bad_request"


def test_capacity_valid_succeeds(db, client):
    loc = make_location(db)
    lane = make_lane(db, loc.id, capacity=20, stock=5, in_transit=0)
    db.commit()
    r = client.put(f"/api/lanes/{lane.id}", json={"capacity": 30})
    assert r.status_code == 200
    assert r.json()["capacity"] == 30
    assert not ({ "code", "subject", "detail" } & set(r.json().keys()))


# ---------- 三口同字：回包 == 流水 == last-failure ----------

def test_three_surfaces_identical_triple(db, client):
    loc = make_location(db)
    make_lane(db, loc.id, slot="C2", capacity=24, stock=24, in_transit=2)
    db.commit()
    env = client.post("/api/refills/run", params={"location_id": loc.id}).json()
    last = client.get("/api/refills/last-failure", params={"location_id": loc.id}).json()
    assert last == {"code": env["code"], "subject": env["subject"], "detail": env["detail"]}
    listed = client.get("/api/refills/failures", params={"location_id": loc.id}).json()["failures"]
    assert listed[0] == last


def test_not_found_envelope_coded(db, client):
    r = client.post("/api/refills/run", params={"location_id": 999})
    assert r.status_code == 404
    env = r.json()
    assert set(env.keys()) == {"code", "subject", "detail"}
    assert env["code"] == "location_not_found"


def test_unknown_route_is_coded_envelope(db, client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert set(r.json().keys()) == {"code", "subject", "detail"}
    assert r.json()["code"] == "not_found"
