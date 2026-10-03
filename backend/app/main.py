from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.envelope import AppError, envelope
from app.services.seed import seed_if_empty


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    if settings.seed_on_empty:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="VendFill", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError):
    # 失败回包：且仅且三字段
    return JSONResponse(status_code=exc.http_status,
                        content=envelope(exc.error_code, exc.object_id, exc.message))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    # 框架层校验失败也必须走信封，不许回 FastAPI 默认的无码 detail 串
    path = _request.url.path
    return JSONResponse(status_code=422,
                        content=envelope("BAD_REQUEST", path,
                                         f"请求不合法：{path} 参数校验未通过：{exc.errors()}; "
                                         f"系统状态保持失败前状态。"))


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_request: Request, exc: StarletteHTTPException):
    # 404 路由不存在等：同样不许退化成 {"detail": ...} 无码串
    code = "NOT_FOUND" if exc.status_code == 404 else f"HTTP_{exc.status_code}"
    return JSONResponse(status_code=exc.status_code,
                        content=envelope(code, _request.url.path,
                                         f"请求未被接受：{_request.url.path}（{exc.status_code}）；"
                                         f"系统状态保持失败前状态。"))


@app.exception_handler(Exception)
async def unhandled_error_handler(_request: Request, exc: Exception):
    # 兜底：任何意外也不许退化成无码字符串
    return JSONResponse(status_code=500,
                        content=envelope("INTERNAL_ERROR", _request.url.path,
                                         f"服务器内部错误：{type(exc).__name__}；系统状态保持失败前状态。"))


app.include_router(api_router, prefix="/api")
