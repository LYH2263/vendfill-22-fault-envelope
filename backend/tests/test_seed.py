"""种子：各打一条生成失败与手改失败，三口同字；截短说明重开仍截短带漂移；
失败后单行数与库存相对失败前不变。"""
import pytest

from app.database import Base
from app.models.models import Lane, Location, RefillFailure, RefillOrder
from app.services import errors
from app.services.seed import seed_if_empty
from tests.conftest import TestEngine


@pytest.fixture(autouse=True)
def _clean_slate():
    # 每个种子测试前清空全库，避免依赖测试执行顺序。
    Base.metadata.drop_all(TestEngine)
    Base.metadata.create_all(TestEngine)


def test_seed_has_two_failures_one_each_kind(db):
    seed_if_empty(db)
    by_action = {r.action: r for r in db.query(RefillFailure).all()}
    assert set(by_action) == {"generate", "manual_edit"}
    gen = by_action["generate"]
    man = by_action["manual_edit"]
    assert gen.code == errors.GENERATION_REJECTED
    assert man.code == errors.MANUAL_OVER_GAP
    # 两条说明都被截短
    assert gen.detail.endswith("…")
    assert man.detail.endswith("…")


def test_seed_triple_matches_canonical_truncation(db):
    seed_if_empty(db)
    for row in db.query(RefillFailure).all():
        assert row.detail == errors.render_detail(row.code, row.subject)
        full = errors.DETAIL_FULL[row.code].format(subject=row.subject)
        assert row.detail != full  # 截短 → 前端判「说明漂移」


def test_seed_failures_persist_identically_on_reopen():
    # StaticPool 单连接内存库：用两个独立会话模拟「关掉再重开」，
    # 截短串与漂移标记必须原样还在。
    from sqlalchemy.orm import sessionmaker
    from tests.conftest import TestSessionLocal

    s1 = TestSessionLocal()
    seed_if_empty(s1)
    before = {r.id: (r.code, r.subject, r.detail)
              for r in s1.query(RefillFailure).all()}
    s1.close()

    s2 = TestSessionLocal()
    after = {r.id: (r.code, r.subject, r.detail)
             for r in s2.query(RefillFailure).order_by(RefillFailure.id).all()}
    assert after == before
    for code, subject, detail in after.values():
        full = errors.DETAIL_FULL[code].format(subject=subject)
        assert detail != full and detail.endswith("…")
    s2.close()


def test_seed_failure_left_no_order_or_stock_change(db):
    # loc1 生成失败：没有因失败产生新补货单，超占货道库存维持种子值。
    seed_if_empty(db)
    loc1 = db.query(Location).filter_by(code="VM-01").one()
    c2 = db.query(Lane).filter_by(location_id=loc1.id, slot_no="C2").one()
    assert (c2.capacity, c2.stock, c2.in_transit) == (24, 24, 2)
    # loc1 只有那张过期草稿一张单（失败不补单）
    assert db.query(RefillOrder).filter_by(location_id=loc1.id).count() == 1
    assert db.query(RefillOrder).filter_by(location_id=loc1.id).one().status == "draft"


def test_seed_idempotent(db):
    seed_if_empty(db)
    n1 = db.query(RefillFailure).count()
    seed_if_empty(db)
    assert db.query(RefillFailure).count() == n1
