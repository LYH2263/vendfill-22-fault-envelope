"""测试数据小工厂。"""
from app.models.models import Lane, Location


def make_location(db, code="VM-01", name="地铁口 A 点位", address="城东地铁 1 号口") -> Location:
    loc = Location(code=code, name=name, address=address)
    db.add(loc)
    db.flush()
    return loc


def make_lane(db, location_id: int, slot="A1", sku="矿泉水",
              capacity=20, stock=5, in_transit=0) -> Lane:
    lane = Lane(location_id=location_id, slot_no=slot, sku_name=sku,
                capacity=capacity, stock=stock, in_transit=in_transit)
    db.add(lane)
    db.flush()
    return lane


def snapshot_stocks(db) -> dict[int, tuple[int, int, int]]:
    return {l.id: (l.capacity, l.stock, l.in_transit)
            for l in db.query(Lane).order_by(Lane.id).all()}
