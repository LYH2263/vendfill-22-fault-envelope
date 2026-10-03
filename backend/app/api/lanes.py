from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Lane
from app.services import refill_service as svc
from app.services.fill_engine import compute_gap

router = APIRouter(prefix="/lanes", tags=["lanes"])


class CapacityIn(BaseModel):
    capacity: int


def _lane_dto(r: Lane) -> dict:
    gap = compute_gap(r.capacity, r.stock, r.in_transit)
    return {"id": r.id, "location_id": r.location_id, "slot_no": r.slot_no,
            "sku_name": r.sku_name, "capacity": r.capacity, "stock": r.stock,
            "in_transit": r.in_transit, "gap": gap,
            "fill_pct": round(r.stock / r.capacity * 100, 1) if r.capacity else 0}


@router.get("")
def list_lanes(location_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Lane).order_by(Lane.slot_no)
    if location_id is not None:
        q = q.where(Lane.location_id == location_id)
    return [_lane_dto(r) for r in db.scalars(q).all()]


@router.put("/{lane_id}")
def update_lane(lane_id: int, body: CapacityIn, db: Session = Depends(get_db)):
    # 容量非法（<1 或低于库存+在途）由 service 判失败信封；类型非法由框架 bad_request 信封拦截。
    return svc.set_capacity(db, lane_id, body.capacity)
