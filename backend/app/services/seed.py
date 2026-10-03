import json
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import Lane, Location, RefillFailure, RefillOrder, Sale
from app.services import errors
from app.services.fill_engine import build_fill_lines, summarize

# (slot, sku, capacity, stock, in_transit)
LANES_LOCO1 = [
    ("A1", "矿泉水", 20, 5, 0),
    ("A2", "可乐", 18, 18, 0),
    ("B1", "薯片", 12, 3, 2),
    ("B2", "巧克力", 15, 10, 5),
    ("C1", "能量棒", 10, 0, 0),
    # 超占货道：库存 24 + 在途 2 > 容量 24，缺口 -2 → 生成必被整体拒单
    ("C2", "口香糖", 24, 24, 2),
]
LANES_LOCO2 = [
    ("D1", "苏打水", 16, 4, 2),
    ("D2", "坚果", 12, 12, 0),
    ("E1", "饼干", 20, 7, 3),
]

NOW = datetime(2026, 9, 16, 12, 0, 0)


def _add_lanes(db: Session, loc_id: int, lanes: list[tuple]) -> list[Lane]:
    out = []
    for slot, sku, cap, stock, transit in lanes:
        lane = Lane(location_id=loc_id, slot_no=slot, sku_name=sku,
                    capacity=cap, stock=stock, in_transit=transit)
        db.add(lane)
        db.flush()
        out.append(lane)
    return out


def _lane_payload(lanes: list[Lane]) -> list[dict]:
    return [{"id": l.id, "slot_no": l.slot_no, "sku_name": l.sku_name,
             "capacity": l.capacity, "stock": l.stock, "in_transit": l.in_transit}
            for l in lanes]


def _failure(db: Session, location_id: int, action: str, code: str,
             subject: str, created_at: datetime) -> None:
    # 与接口回包同源：detail 由全文真源渲染（此处两条均超上限被截短），
    # 页面重开只拿得到截短串，须照显截短并标「说明漂移」，禁止补全。
    db.add(RefillFailure(location_id=location_id, action=action, code=code,
                         subject=subject, detail=errors.render_detail(code, subject),
                         created_at=created_at))


def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(Location)) or 0) > 0:
        return

    loc1 = Location(code="VM-01", name="地铁口 A 点位", address="城东地铁 1 号口")
    db.add(loc1)
    db.flush()
    lanes1 = _add_lanes(db, loc1.id, LANES_LOCO1)

    # 销量流水
    for i, lane in enumerate(lanes1):
        db.add(Sale(lane_id=lane.id, qty=2 + i, sold_at=NOW - timedelta(hours=i)))

    # 一张过期草稿（其后 A1 货道库存已变），使重新核销必冲突。
    stale_payload = []
    for l in lanes1:
        row = {"id": l.id, "slot_no": l.slot_no, "sku_name": l.sku_name,
               "capacity": l.capacity, "stock": l.stock, "in_transit": l.in_transit}
        if l.slot_no == "A1":
            row["stock"] = l.stock - 1  # 快照旧于现状
        stale_payload.append(row)
    stale_summary = summarize(build_fill_lines(stale_payload))
    db.add(RefillOrder(location_id=loc1.id, created_at=NOW - timedelta(days=1),
                       status="draft",
                       lines_json=json.dumps(stale_summary, ensure_ascii=False)))

    # 种子两条失败：先一条手改失败，再一条生成失败（最近一条为生成被拒）。
    # subject 与三口显示的对象标识同一串；detail 均被截短。
    _failure(db, loc1.id, "manual_edit", errors.MANUAL_OVER_GAP,
             "C1（能量棒）", NOW - timedelta(hours=2))
    _failure(db, loc1.id, "generate", errors.GENERATION_REJECTED,
             "VM-01（地铁口 A 点位）", NOW - timedelta(hours=1))

    # 健康点位：可正常生成并核销，作为成功路径对照（成功不带原因码）。
    loc2 = Location(code="VM-02", name="商圈 B 点位", address="城西购物中心一层")
    db.add(loc2)
    db.flush()
    lanes2 = _add_lanes(db, loc2.id, LANES_LOCO2)
    for i, lane in enumerate(lanes2):
        db.add(Sale(lane_id=lane.id, qty=1 + i, sold_at=NOW - timedelta(hours=i + 1)))
    summary2 = summarize(build_fill_lines(_lane_payload(lanes2)))
    db.add(RefillOrder(location_id=loc2.id, created_at=NOW - timedelta(hours=3),
                       status="fulfilled",
                       lines_json=json.dumps(summary2, ensure_ascii=False)))

    db.commit()
