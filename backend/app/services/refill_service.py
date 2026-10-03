"""补货落单/手改/核销与容量保存。

铁律：
- 失败先于任何业务写入判定：全部校验通过后才一次性落库，
  失败时不得留下半成功补货单行或半改库存；
- 失败只通过 errors.fail(...) 抛出三字段信封，并写一条 RefillFailure 流水，
  流水内容与接口回包逐字段同一份；
- 成功回包不含 code/subject/detail。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Lane, Location, RefillFailure, RefillOrder
from app.services import errors
from app.services.fill_engine import build_fill_lines, summarize

ACTION_GENERATE = "generate"
ACTION_MANUAL_EDIT = "manual_edit"
ACTION_FULFILL = "fulfill"
ACTION_CAPACITY = "capacity"


def loc_subject(loc: Location) -> str:
    return f"{loc.code}（{loc.name}）"


def lane_subject(lane: Lane) -> str:
    return f"{lane.slot_no}（{lane.sku_name}）"


def order_subject(order: RefillOrder) -> str:
    return f"补货单#{order.id}"


def _lane_payload(lanes: list[Lane]) -> list[dict]:
    return [
        {"id": l.id, "slot_no": l.slot_no, "sku_name": l.sku_name,
         "capacity": l.capacity, "stock": l.stock, "in_transit": l.in_transit}
        for l in lanes
    ]


def _raise(db: Session, action: str, code: str, subject: object,
           location_id: int | None, *, status_code: int = 422) -> NoReturn:
    """构造三字段信封、写失败流水，再抛出；任何失败路径只允许走这里。"""
    err = errors.fail(code, subject, status_code=status_code)
    db.add(RefillFailure(location_id=location_id, action=action,
                         code=err.code, subject=err.subject, detail=err.detail))
    db.commit()
    raise err


def order_to_dto(order: RefillOrder) -> dict:
    data = json.loads(order.lines_json)
    return {"id": order.id, "location_id": order.location_id,
            "status": order.status, **data}


def _get_order(db: Session, order_id: int, action: str) -> RefillOrder:
    order = db.get(RefillOrder, order_id)
    if not order:
        _raise(db, action, errors.REFILL_NOT_FOUND,
               f"补货单#{order_id}", None, status_code=404)
    return order


def _lanes_by_id(db: Session, location_id: int) -> dict[int, Lane]:
    return {l.id: l for l in db.scalars(
        select(Lane).where(Lane.location_id == location_id)).all()}


# ---------- 生成 ----------

def generate(db: Session, location_id: int) -> dict:
    loc = db.get(Location, location_id)
    if not loc:
        _raise(db, ACTION_GENERATE, errors.LOCATION_NOT_FOUND,
               f"点位#{location_id}", None, status_code=404)
    lanes = list(db.scalars(
        select(Lane).where(Lane.location_id == location_id).order_by(Lane.slot_no)).all())

    # 校验先于写入：任何货道超占（缺口为负）即整体拒单，不落补货单、不动库存。
    overbooked = [l for l in lanes if l.capacity - l.stock - l.in_transit < 0]
    if overbooked:
        _raise(db, ACTION_GENERATE, errors.GENERATION_REJECTED,
               loc_subject(loc), location_id)

    summary = summarize(build_fill_lines(_lane_payload(lanes)))
    order = RefillOrder(location_id=location_id, created_at=datetime.utcnow(),
                        status="draft", lines_json=json.dumps(summary, ensure_ascii=False))
    db.add(order)
    db.commit()
    db.refresh(order)
    return order_to_dto(order)


# ---------- 手改 ----------

def adjust(db: Session, order_id: int, fills: dict[int, int]) -> dict:
    order = _get_order(db, order_id, ACTION_MANUAL_EDIT)
    if order.status == "fulfilled":
        _raise(db, ACTION_MANUAL_EDIT, errors.FULFILL_CONFLICT,
               order_subject(order), order.location_id)

    lanes = _lanes_by_id(db, order.location_id)

    # 先把所有行校验完，任一行非法即整体拒绝：不写 lines_json、不动库存。
    requested: dict[int, int] = {}
    for raw_lane_id, qty in fills.items():
        lane_id = int(raw_lane_id)
        lane = lanes.get(lane_id)
        if lane is None:
            _raise(db, ACTION_MANUAL_EDIT, errors.LANE_NOT_FOUND,
                   f"货道#{lane_id}", order.location_id, status_code=404)
        gap = lane.capacity - lane.stock - lane.in_transit
        if not isinstance(qty, int) or qty < 0 or qty > gap:
            _raise(db, ACTION_MANUAL_EDIT, errors.MANUAL_OVER_GAP,
                   lane_subject(lane), order.location_id)
        requested[lane_id] = qty

    summary = summarize(build_fill_lines(_lane_payload(list(lanes.values())), requested))
    order.lines_json = json.dumps(summary, ensure_ascii=False)
    db.commit()
    db.refresh(order)
    return order_to_dto(order)


# ---------- 核销 ----------

def fulfill(db: Session, order_id: int) -> dict:
    order = _get_order(db, order_id, ACTION_FULFILL)
    if order.status == "fulfilled":
        _raise(db, ACTION_FULFILL, errors.FULFILL_CONFLICT,
               order_subject(order), order.location_id)

    data = json.loads(order.lines_json)
    current = _lanes_by_id(db, order.location_id)

    # 冲突先于写入：快照与现状不一致即整体作废，任何一行库存都不改。
    for line in data["lines"]:
        lane = current.get(line["lane_id"])
        if lane is None or lane.stock != line["stock"] or lane.in_transit != line["in_transit"]:
            subject = lane_subject(lane) if lane else f"货道#{line['lane_id']}"
            _raise(db, ACTION_FULFILL, errors.FULFILL_CONFLICT,
                   f"{order_subject(order)} / {subject}", order.location_id)

    for line in data["lines"]:
        current[line["lane_id"]].stock += line["fill_qty"]
    order.status = "fulfilled"
    db.commit()
    db.refresh(order)
    return order_to_dto(order)


# ---------- 容量保存 ----------

def set_capacity(db: Session, lane_id: int, value: int) -> dict:
    lane = db.get(Lane, lane_id)
    if not lane:
        _raise(db, ACTION_CAPACITY, errors.LANE_NOT_FOUND,
               f"货道#{lane_id}", None, status_code=404)
    # 校验先于保存：非法容量一律拒绝，不留半截容量值。
    if not isinstance(value, int) or value < 1 or value < lane.stock + lane.in_transit:
        _raise(db, ACTION_CAPACITY, errors.INVALID_CAPACITY,
               lane_subject(lane), lane.location_id)
    lane.capacity = value
    db.commit()
    db.refresh(lane)
    return {"id": lane.id, "location_id": lane.location_id, "slot_no": lane.slot_no,
            "sku_name": lane.sku_name, "capacity": lane.capacity,
            "stock": lane.stock, "in_transit": lane.in_transit}


# ---------- 最近失败流水（三口同字的取同源） ----------

def latest_failure(db: Session, location_id: int) -> RefillFailure | None:
    return db.scalars(
        select(RefillFailure).where(RefillFailure.location_id == location_id)
        .order_by(RefillFailure.id.desc())).first()
