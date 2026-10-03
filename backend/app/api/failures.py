from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import FailureRecord

router = APIRouter(prefix="/failures", tags=["failures"])


def to_dict(r: FailureRecord) -> dict:
    # error_code/object_id/message 与 4xx 信封逐字段同名同字；
    # 其余字段只标注来源场景与截短漂移，不参与错误条三字段渲染。
    return {
        "id": r.id,
        "location_id": r.location_id,
        "scene": r.scene,
        "error_code": r.error_code,
        "object_id": r.object_id,
        "message": r.message,
        "drifted": r.drifted,
        "created_at": r.created_at.isoformat(),
    }


@router.get("/latest")
def latest_failure(location_id: int | None = None,
                   scene: str | None = None,
                   scenes: str | None = None,
                   db: Session = Depends(get_db)):
    """最近一条失败落单。补货单页与货道页错误条都从这里取，保证三口同字。

    scene=单场景；scenes=逗号分隔多场景。
    """
    q = select(FailureRecord).order_by(FailureRecord.id.desc())
    if location_id is not None:
        q = q.where(FailureRecord.location_id == location_id)
    wanted = None
    if scenes:
        wanted = [s.strip() for s in scenes.split(",") if s.strip()]
    elif scene:
        wanted = [scene]
    if wanted:
        q = q.where(FailureRecord.scene.in_(wanted))
    rec = db.scalars(q).first()
    if rec is None:
        return {"failure": None}
    return {"failure": to_dict(rec)}
