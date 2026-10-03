import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SEED_ON_EMPTY", "false")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as db_module
from app.database import Base, get_db

# 单连接内存库：配合 get_db 依赖覆盖（请求复用测试会话），
# 既无多连接锁竞争，也保证测试写入对请求立即可见。
TestEngine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=TestEngine, autoflush=False, autocommit=False)
Base.metadata.create_all(TestEngine)

# 替换全局引擎/会话工厂。
db_module.engine = TestEngine
db_module.SessionLocal = TestSessionLocal

from app.main import app  # noqa: E402


@pytest.fixture
def db():
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    # 每个用例一份干净库（此时测试会话尚未检出连接，无事务冲突）。
    Base.metadata.drop_all(TestEngine)
    Base.metadata.create_all(TestEngine)
    # 请求处理直接复用测试会话：同一连接，数据即时可见，杜绝跨会话/跨连接不一致。
    app.dependency_overrides[get_db] = lambda: (yield db)
    c = TestClient(app)
    try:
        yield c
    finally:
        app.dependency_overrides.pop(get_db, None)
