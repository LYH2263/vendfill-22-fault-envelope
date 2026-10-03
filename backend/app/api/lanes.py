import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Lane
from app.services import reasons as R
from app.services.failure_store import reject
from app.services.fill_engine import compute_gap

router = APIRouter(prefix="/lanes", tags=["lanes"])


def _lane_dict(r: Lane) -> dict:
    gap = compute_gap(r.capacity, r.stock, r.in_transit)
    return {"id": r.id, "location_id": r.location_id, "slot_no": r.slot_no, "sku_name": r.sku_name,
            "capacity": r.capacity, "stock": r.stock, "in_transit": r.in_transit, "gap": gap,
            "fill_pct": round(r.stock / r.capacity * 100, 1) if r.capacity else 0}


@router.get("")
def list_lanes(location_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Lane).order_by(Lane.slot_no)
    if location_id is not None:
        q = q.where(Lane.location_id == location_id)
    return [_lane_dict(r) for r in db.scalars(q).all()]


@router.patch("/{lane_id}/capacity")
async def update_capacity(lane_id: int, request: Request, db: Session = Depends(get_db)):
    lane = db.get(Lane, lane_id)
    if not lane:
        reject(db, R.SCENE_CAPACITY, R.LANE_NOT_FOUND, f"lane:{lane_id}",
               R.not_found("货道", lane_id), http_status=404)

    raw: object = None
    try:
        body = json.loads(await request.body() or b"{}")
        raw = body["capacity"]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            raise ValueError
        cap = int(raw)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        reject(db, R.SCENE_CAPACITY, R.CAP_INVALID, f"lane:{lane_id}",
               R.cap_invalid(lane.slot_no, raw),
               location_id=lane.location_id)

    if cap < lane.stock + lane.in_transit:
        # 非法容量保存（低于库存+在途）：拒绝且不动库存
        reject(db, R.SCENE_CAPACITY, R.CAP_INVALID, f"lane:{lane_id}",
               R.cap_below_holdings(lane.slot_no, lane.sku_name, cap, lane.stock, lane.in_transit),
               location_id=lane.location_id)

    lane.capacity = cap
    db.commit()
    db.refresh(lane)
    return _lane_dict(lane)
