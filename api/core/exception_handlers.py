import logging
import re

import asyncpg
from fastapi import HTTPException, Request
from fastapi.exception_handlers import RequestValidationError
from fastapi.exceptions import ResponseValidationError
from fastapi.responses import JSONResponse
from starlette.status import (
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

# Get the configured logger
logger = logging.getLogger("fastapi")


def format_detail(detail):
    if isinstance(detail, list) and detail and isinstance(detail[0], dict) and "msg" in detail[0]:
        # User-friendly: Only show the last part of the field, capitalize it
        return "; ".join(f"{str(err['loc'][-1]).replace('_', ' ').capitalize()}: {err['msg']}" for err in detail)
    if isinstance(detail, str):
        return detail
    return str(detail)


def register_exception_handlers(app):
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.error(f"Validation error: {exc.errors()}")
        return JSONResponse(
            status_code=HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": format_detail(exc.errors())},
        )

    @app.exception_handler(asyncpg.UniqueViolationError)
    async def unique_violation_handler(request: Request, exc: asyncpg.UniqueViolationError):
        logger.error(f"Unique violation error: {exc}")
        # extract the key(s) and value(s) from exc.detail
        fields = None
        values = None
        if hasattr(exc, "detail") and exc.detail:
            match = re.search(r"Key \((.*?)\)=\((.*?)\)", exc.detail)
            if match:
                fields = [f.strip() for f in match.group(1).split(",")]
                values = [v.strip() for v in match.group(2).split(",")]
        if fields and values:
            field_value_pairs = ", ".join(f"{f}='{v}'" for f, v in zip(fields, values))
            detail_msg = f"A record with {field_value_pairs} already exists."
        elif fields:
            detail_msg = f"A record with {', '.join(fields)} value already exists."
        else:
            detail_msg = "A record with the same value already exists."
        return JSONResponse(
            status_code=400,
            content={
                "detail": detail_msg,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger.error(f"HTTP exception: {exc.status_code} - {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": format_detail(exc.detail)},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        logger.error(f"Value error: {exc}")
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc) or "Invalid value provided."},
        )

    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError):
        logger.error(f"Key error: {exc}")
        return JSONResponse(
            status_code=400,
            content={"detail": f"Missing key: {exc.args[0]}" if exc.args else "Missing key."},
        )

    @app.exception_handler(PermissionError)
    async def permission_error_handler(request: Request, exc: PermissionError):
        logger.error(f"Permission error: {exc}")
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc) or "Permission denied."},
        )

    @app.exception_handler(NotImplementedError)
    async def not_implemented_error_handler(request: Request, exc: NotImplementedError):
        logger.error(f"Not implemented error: {exc}")
        return JSONResponse(
            status_code=501,
            content={"detail": str(exc) or "Not implemented."},
        )

    @app.exception_handler(TypeError)
    async def type_error_handler(request: Request, exc: TypeError):
        logger.error(f"Type error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc) or "Type error."},
        )

    @app.exception_handler(ResponseValidationError)
    async def response_validation_exception_handler(request: Request, exc: ResponseValidationError):
        logger.error(f"Response validation error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": format_detail(exc.errors())},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )
