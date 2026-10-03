"""失败落单：先整体回滚业务改动，再只插入一条失败记录并提交。

保证失败不留下半成功补货单行、不留下半改库存；
接口回包读的三字段与落库记录逐字段同源。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.models import FailureRecord
from app.services.envelope import AppError, truncate_message


def reject(
    db: Session,
    scene: str,
    error_code: str,
    object_id: str | int,
    message: str,
    *,
    location_id: int | None = None,
    http_status: int = 422,
) -> None:
    # 先回滚本请求已经挂起的任何业务改动（半单行、半改库存一律不留）
    db.rollback()
    text, drifted = truncate_message(str(message))
    rec = FailureRecord(
        location_id=location_id,
        scene=scene,
        error_code=error_code,
        object_id=str(object_id),
        message=text,
        drifted=drifted,
    )
    db.add(rec)
    db.commit()
    # 抛出的三字段与落库内容逐字一致
    raise AppError(error_code, str(object_id), text, http_status=http_status)


def record_failure(
    db: Session,
    scene: str,
    error_code: str,
    object_id: str | int,
    message: str,
    *,
    location_id: int | None = None,
    commit: bool = True,
) -> FailureRecord:
    """直接落一条失败记录（种子/迁移用），返回已落库记录。"""
    text, drifted = truncate_message(str(message))
    rec = FailureRecord(
        location_id=location_id,
        scene=scene,
        error_code=error_code,
        object_id=str(object_id),
        message=text,
        drifted=drifted,
    )
    db.add(rec)
    if commit:
        db.commit()
    return rec
