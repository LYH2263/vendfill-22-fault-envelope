import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.errors import (
    BAD_REQUEST,
    INTERNAL_ERROR,
    METHOD_NOT_ALLOWED,
    NOT_FOUND,
    FailError,
    envelope,
    render_detail,
)
from app.services.seed import seed_if_empty

logger = logging.getLogger("vendfill")


def _subject_of_request(request: Request) -> str:
    return f"{request.method} {request.url.path}"


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


@app.exception_handler(FailError)
async def fail_error_handler(_request: Request, exc: FailError) -> JSONResponse:
    # 业务失败：三字段信封，字段集与错误条/失败流水逐字段同一套。
    return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request,
                                   exc: RequestValidationError) -> JSONResponse:
    # 框架层入参非法同样走有码信封，禁止回 FastAPI 默认无码 422 串。
    if exc.errors():
        err = exc.errors()[0]
        loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query"))
        subject = f"字段 {loc}" if loc else _subject_of_request(request)
    else:
        subject = _subject_of_request(request)
    return JSONResponse(
        status_code=400,
        content=envelope(BAD_REQUEST, subject, render_detail(BAD_REQUEST, subject)),
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request,
                             exc: StarletteHTTPException) -> JSONResponse:
    # 路由级 404/405 等也统一成有码信封，不放出 {"detail": "..."} 无码串。
    if exc.status_code == 404:
        code = NOT_FOUND
    elif exc.status_code == 405:
        code = METHOD_NOT_ALLOWED
    else:
        code = BAD_REQUEST
    subject = _subject_of_request(request)
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(code, subject, render_detail(code, subject)),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error: %s", exc)
    subject = _subject_of_request(request)
    return JSONResponse(
        status_code=500,
        content=envelope(INTERNAL_ERROR, subject, render_detail(INTERNAL_ERROR, subject)),
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
