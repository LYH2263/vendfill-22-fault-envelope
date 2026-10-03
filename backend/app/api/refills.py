import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Lane, Location, RefillOrder
from app.services import reasons as R
from app.services.failure_store import reject
from app.services.fill_engine import build_fill_lines, summarize

router = APIRouter(prefix="/refills", tags=["refills"])

# 成功回包允许出现的键；error_code/object_id/message 永远不许出现在成功路径
SUCCESS_KEYS = {"id", "location_id", "total_fill", "need_fill_count",
                "full_count", "overbooked_count", "lines", "redeemed_at"}


def _order_payload(order: RefillOrder) -> dict:
    data = json.loads(order.lines_json)
    payload = {"id": order.id, "location_id": order.location_id, **data,
               "redeemed_at": order.redeemed_at.isoformat() if order.redeemed_at else None}
    # 互斥红线：成功回包里不得混入任何失败字段
    assert set(payload).issubset(SUCCESS_KEYS)
    return payload


def _lanes_payload(lanes) -> list[dict]:
    return [{"id": l.id, "slot_no": l.slot_no, "sku_name": l.sku_name,
             "capacity": l.capacity, "stock": l.stock, "in_transit": l.in_transit} for l in lanes]


def _load_location(db: Session, location_id: int, scene: str):
    loc = db.get(Location, location_id)
    if not loc:
        reject(db, scene, R.LOCATION_NOT_FOUND, f"location:{location_id}",
               R.not_found("点位", location_id), location_id=location_id, http_status=404)
    return loc


@router.post("/run")
def run_refill(location_id: int = 1, db: Session = Depends(get_db)):
    _load_location(db, location_id, R.SCENE_GENERATE)
    lanes = db.scalars(select(Lane).where(Lane.location_id == location_id)
                       .order_by(Lane.slot_no)).all()
    payload = _lanes_payload(lanes)

    # 生成被拒：任一货道超占（gap<0）即整体拒绝，不生成补货单、不改库存
    over = next((p for p in payload if p["capacity"] - p["stock"] - p["in_transit"] < 0), None)
    if over is not None:
        reject(db, R.SCENE_GENERATE, R.GEN_OVERBOOKED, f"lane:{over['id']}",
               R.gen_overbooked(over["slot_no"], over["sku_name"],
                                over["capacity"], over["stock"], over["in_transit"]),
               location_id=location_id)

    summary = summarize(build_fill_lines(payload))
    order = RefillOrder(location_id=location_id, created_at=datetime.utcnow(),
                        lines_json=json.dumps(summary, ensure_ascii=False))
    db.add(order)
    db.commit()
    db.refresh(order)
    return _order_payload(order)


@router.post("/orders/{order_id}/manual-edit")
async def manual_edit(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = db.get(RefillOrder, order_id)
    if not order:
        reject(db, R.SCENE_MANUAL, R.ORDER_NOT_FOUND, f"order:{order_id}",
               R.not_found("补货单", order_id), http_status=404)

    try:
        body = json.loads(await request.body() or b"{}")
        edits = body["lines"]
        assert isinstance(edits, list)
        norm = [(int(item["lane_id"]), item["fill_qty"]) for item in edits]
    except Exception:
        reject(db, R.SCENE_MANUAL, R.BAD_REQUEST, f"order:{order_id}",
               R.bad_request(f"补货单{order_id}手改"), location_id=order.location_id)

    data = json.loads(order.lines_json)
    lines_by_lane = {l["lane_id"]: l for l in data["lines"]}
    lane_rows = {l.id: l for l in db.scalars(select(Lane)).all()}

    for lane_id, raw_qty in norm:
        line = lines_by_lane.get(lane_id)
        if line is None:
            reject(db, R.SCENE_MANUAL, R.LINE_NOT_IN_ORDER, f"lane:{lane_id}",
                   R.line_not_in_order(order_id, lane_id), location_id=order.location_id)
        # bool 是 int 的子类，必须显式挡掉
        if not isinstance(raw_qty, int) or isinstance(raw_qty, bool) or raw_qty < 0:
            reject(db, R.SCENE_MANUAL, R.MANUAL_QTY_INVALID, f"lane:{lane_id}",
                   R.manual_qty_invalid(order_id, line["slot_no"], raw_qty),
                   location_id=order.location_id)
        lane = lane_rows.get(lane_id)
        if lane is None:
            reject(db, R.SCENE_MANUAL, R.LANE_NOT_FOUND, f"lane:{lane_id}",
                   R.not_found("货道", lane_id), location_id=order.location_id)
        gap = lane.capacity - lane.stock - lane.in_transit
        if raw_qty > gap:
            # 手改超缺口：整单不落任何行、库存不动
            reject(db, R.SCENE_MANUAL, R.MANUAL_OVER_GAP, f"lane:{lane_id}",
                   R.manual_over_gap(order_id, line["slot_no"], line["sku_name"], raw_qty, gap),
                   location_id=order.location_id)
        line["fill_qty"] = raw_qty
        line["gap"] = gap
        line["capacity"] = lane.capacity
        line["stock"] = lane.stock
        line["in_transit"] = lane.in_transit
        line["status"] = "overbooked" if gap < 0 else ("full" if gap == 0 else "need_fill")

    data["total_fill"] = sum(l["fill_qty"] for l in data["lines"])
    data["need_fill_count"] = sum(1 for l in data["lines"] if l["status"] == "need_fill")
    data["full_count"] = sum(1 for l in data["lines"] if l["status"] == "full")
    data["overbooked_count"] = sum(1 for l in data["lines"] if l["status"] == "overbooked")
    order.lines_json = json.dumps(data, ensure_ascii=False)
    db.commit()
    db.refresh(order)
    return _order_payload(order)


@router.post("/orders/{order_id}/redeem")
def redeem_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(RefillOrder, order_id)
    if not order:
        reject(db, R.SCENE_REDEEM, R.ORDER_NOT_FOUND, f"order:{order_id}",
               R.not_found("补货单", order_id), http_status=404)
    if order.redeemed_at is not None:
        reject(db, R.SCENE_REDEEM, R.REDEEM_ALREADY, f"order:{order_id}",
               R.redeem_already(order_id), location_id=order.location_id, http_status=409)

    data = json.loads(order.lines_json)
    lanes = {l.id: l for l in db.scalars(select(Lane)).all()}
    # 先整体校验：任一行核销后超容量，则全部不改（不允许半核销）
    for line in data["lines"]:
        fill = int(line["fill_qty"])
        if fill <= 0:
            continue
        lane = lanes.get(line["lane_id"])
        if lane is None:
            reject(db, R.SCENE_REDEEM, R.LANE_NOT_FOUND, f"lane:{line['lane_id']}",
                   R.not_found("货道", line["lane_id"]),
                   location_id=order.location_id, http_status=404)
        if lane.stock + fill > lane.capacity:
            reject(db, R.SCENE_REDEEM, R.REDEEM_EXCEEDS, f"lane:{lane.id}",
                   R.redeem_exceeds(order_id, lane.slot_no, lane.sku_name,
                                    fill, lane.capacity, lane.stock),
                   location_id=order.location_id, http_status=409)
    # 全部通过才落库
    for line in data["lines"]:
        fill = int(line["fill_qty"])
        if fill > 0:
            lanes[line["lane_id"]].stock += fill
    order.redeemed_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return _order_payload(order)


@router.get("/latest")
def latest(location_id: int = 1, db: Session = Depends(get_db)):
    _load_location(db, location_id, R.SCENE_GENERATE)
    order = db.scalars(select(RefillOrder).where(RefillOrder.location_id == location_id)
                       .order_by(RefillOrder.id.desc())).first()
    if not order:
        return run_refill(location_id=location_id, db=db)
    return _order_payload(order)


@router.get("/full")
def full_lanes(location_id: int = 1, db: Session = Depends(get_db)):
    data = latest(location_id=location_id, db=db)
    return {"location_id": location_id, "lanes": [l for l in data["lines"] if l["status"] == "full"]}


@router.get("/summary")
def refill_summary(location_id: int = 1, db: Session = Depends(get_db)):
    data = latest(location_id=location_id, db=db)
    return {
        "location_id": location_id,
        "total_fill": data["total_fill"],
        "need_fill_count": data["need_fill_count"],
        "full_count": data["full_count"],
        "overbooked_count": data["overbooked_count"],
    }
