import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import RefillFailure, RefillOrder
from app.services import refill_service as svc

router = APIRouter(prefix="/refills", tags=["refills"])


class AdjustIn(BaseModel):
    # 手工补量：lane_id -> 件数；超缺口/负数由 service 校验并整体拒收
    fills: dict[int, int] = Field(default_factory=dict)


@router.post("/run")
def run_refill(location_id: int = 1, db: Session = Depends(get_db)):
    # 成功回包只有补货单字段；失败由 FailError 处理器落成三字段信封。
    return svc.generate(db, location_id)


@router.get("/latest")
def latest(location_id: int = 1, db: Session = Depends(get_db)):
    order = db.scalars(select(RefillOrder).where(RefillOrder.location_id == location_id)
                       .order_by(RefillOrder.id.desc())).first()
    # 无单不自动补单：返回 null，由页面提示；绝不伪装成失败信封或成功信封。
    return svc.order_to_dto(order) if order else None


@router.post("/{order_id}/adjust")
def adjust_order(order_id: int, body: AdjustIn, db: Session = Depends(get_db)):
    return svc.adjust(db, order_id, body.fills)


@router.post("/{order_id}/fulfill")
def fulfill_order(order_id: int, db: Session = Depends(get_db)):
    return svc.fulfill(db, order_id)


def _failure_triple(row: RefillFailure) -> dict[str, str]:
    # 只回三字段，与错误条、失败流水逐字段同一套。
    return {"code": row.code, "subject": row.subject, "detail": row.detail}


@router.get("/last-failure")
def last_failure(location_id: int = 1, db: Session = Depends(get_db)):
    row = svc.latest_failure(db, location_id)
    return _failure_triple(row) if row else None


@router.get("/failures")
def list_failures(location_id: int = 1, action: str | None = None,
                  db: Session = Depends(get_db)):
    q = select(RefillFailure).where(RefillFailure.location_id == location_id)
    if action is not None:
        q = q.where(RefillFailure.action == action)
    rows = db.scalars(q.order_by(RefillFailure.id.desc())).all()
    return {"location_id": location_id, "failures": [_failure_triple(r) for r in rows]}


@router.get("/full")
def full_lanes(location_id: int = 1, db: Session = Depends(get_db)):
    order = db.scalars(select(RefillOrder).where(RefillOrder.location_id == location_id)
                       .order_by(RefillOrder.id.desc())).first()
    if not order:
        return {"location_id": location_id, "lanes": []}
    data = json.loads(order.lines_json)
    return {"location_id": location_id,
            "lanes": [l for l in data["lines"] if l["status"] == "full"]}


@router.get("/summary")
def refill_summary(location_id: int = 1, db: Session = Depends(get_db)):
    order = db.scalars(select(RefillOrder).where(RefillOrder.location_id == location_id)
                       .order_by(RefillOrder.id.desc())).first()
    if not order:
        return {"location_id": location_id, "total_fill": 0,
                "need_fill_count": 0, "full_count": 0, "overbooked_count": 0}
    data = json.loads(order.lines_json)
    return {
        "location_id": location_id,
        "total_fill": data["total_fill"],
        "need_fill_count": data["need_fill_count"],
        "full_count": data["full_count"],
        "overbooked_count": data["overbooked_count"],
    }
