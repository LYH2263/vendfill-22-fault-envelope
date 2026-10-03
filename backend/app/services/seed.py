import json
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import FailureRecord, Lane, Location, RefillOrder, Sale
from app.services import reasons as R
from app.services.envelope import truncate_message
from app.services.fill_engine import build_fill_lines, summarize


def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(Location)) or 0) > 0:
        return
    loc = Location(code="VM-01", name="地铁口 A 点位", address="城东地铁 1 号口")
    db.add(loc)
    db.flush()
    # C2 库存 24 + 在途 2 > 容量 24：超占，生成补货单必须被拒
    lanes = [
        ("A1", "矿泉水", 20, 5, 0),
        ("A2", "可乐", 18, 18, 0),
        ("B1", "薯片", 12, 3, 2),
        ("B2", "巧克力", 15, 10, 5),
        ("C1", "能量棒", 10, 0, 0),
        ("C2", "口香糖", 24, 24, 2),
    ]
    lane_ids = []
    lane_rows = []
    for slot, sku, cap, stock, transit in lanes:
        lane = Lane(location_id=loc.id, slot_no=slot, sku_name=sku,
                    capacity=cap, stock=stock, in_transit=transit)
        db.add(lane)
        db.flush()
        lane_ids.append(lane.id)
        lane_rows.append({"id": lane.id, "slot_no": slot, "sku_name": sku,
                          "capacity": cap, "stock": stock, "in_transit": transit})
    now = datetime(2026, 9, 16, 12, 0, 0)
    for i, lid in enumerate(lane_ids):
        db.add(Sale(lane_id=lid, qty=2 + i, sold_at=now - timedelta(hours=i)))

    # 一张此前正常生成的历史补货单（完整落单，非半成功行）
    summary = summarize(build_fill_lines(lane_rows))
    order = RefillOrder(location_id=loc.id, created_at=datetime(2026, 9, 15, 9, 0, 0),
                        lines_json=json.dumps(summary, ensure_ascii=False))
    db.add(order)
    db.flush()

    # 生成失败一条：与 /refills/run 现场拒绝时逐字同模板同参数
    c2 = lane_rows[5]
    db.add(FailureRecord(
        location_id=loc.id, scene=R.SCENE_GENERATE, error_code=R.GEN_OVERBOOKED,
        object_id=f"lane:{c2['id']}",
        **_record_fields(R.gen_overbooked(c2["slot_no"], c2["sku_name"],
                                          c2["capacity"], c2["stock"], c2["in_transit"])),
        created_at=datetime(2026, 9, 16, 11, 0, 0),
    ))

    # 手改失败一条：与对该单 A1 提交 16 件（缺口仅 15）现场拒绝时同字
    a1 = lane_rows[0]
    db.add(FailureRecord(
        location_id=loc.id, scene=R.SCENE_MANUAL, error_code=R.MANUAL_OVER_GAP,
        object_id=f"lane:{a1['id']}",
        **_record_fields(R.manual_over_gap(order.id, a1["slot_no"], a1["sku_name"], 16,
                                           a1["capacity"] - a1["stock"] - a1["in_transit"])),
        created_at=datetime(2026, 9, 16, 11, 5, 0),
    ))
    db.commit()


def _record_fields(message: str) -> dict:
    from app.services.envelope import truncate_message
    text, drifted = truncate_message(message)
    return {"message": text, "drifted": drifted}
