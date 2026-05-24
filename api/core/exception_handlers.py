import logging
import re
from typing import Any

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.status import HTTP_422_UNPROCESSABLE_CONTENT, HTTP_500_INTERNAL_SERVER_ERROR

# Get the configured logger
logger = logging.getLogger("fastapi")


def format_detail(detail: Any) -> str:
    """
    Format the detail of an exception for user-friendly output.
    Args:
        detail (Any): The detail information from an exception.
    Returns:
        str: Formatted detail string.
    """
    if isinstance(detail, list) and detail and isinstance(detail[0], dict) and "msg" in detail[0]:
        # User-friendly: Only show the last part of the field, capitalize it
        return "; ".join(f"{str(err['loc'][-1]).replace('_', ' ').capitalize()}: {err['msg']}" for err in detail)
    if isinstance(detail, str):
        return detail
    return str(detail)


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register exception handlers for FastAPI application.
    Args:
        app (FastAPI): The FastAPI application instance.
    Returns:
        None
    """

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.error("Validation error: %s", exc.errors())
        return JSONResponse(
            status_code=HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": format_detail(exc.errors())},
        )

    @app.exception_handler(asyncpg.UniqueViolationError)
    async def unique_violation_handler(_request: Request, exc: asyncpg.UniqueViolationError) -> JSONResponse:
        logger.error("Unique violation error: %s", exc)
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
        else:
            detail_msg = "A record with the same value already exists."
        return JSONResponse(
            status_code=400,
            content={
                "detail": detail_msg,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        logger.error("HTTP exception: %s - %s", exc.status_code, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": format_detail(exc.detail)},
        )

    @app.exception_handler(PermissionError)
    async def permission_error_handler(_request: Request, exc: PermissionError) -> JSONResponse:
        logger.error("Permission error: %s", exc)
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc) or "Permission denied."},
        )

    @app.exception_handler(NotImplementedError)
    async def not_implemented_error_handler(_request: Request, exc: NotImplementedError) -> JSONResponse:
        logger.error("Not implemented error: %s", exc)
        return JSONResponse(
            status_code=501,
            content={"detail": str(exc) or "Not implemented."},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )
