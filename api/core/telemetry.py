import os
from typing import Any, Callable

import fastapi.routing
from fastapi import FastAPI, Request, Response
from fastapi.routing import APIRoute
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from api.core.config import settings


def instrument_fastapi_validation() -> None:
    """
    Monkey-patch fastapi.routing.serialize_response to capture Pydantic validation time.
    """
    original_serialize_response = fastapi.routing.serialize_response

    async def patched_serialize_response(*args: Any, **kwargs: Any) -> Any:
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("response_model_validation"):
            return await original_serialize_response(*args, **kwargs)

    fastapi.routing.serialize_response = patched_serialize_response


class TelemetryRoute(APIRoute):
    """
    Custom APIRoute to add OpenTelemetry spans for detailed tracing.
    """

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()
        tracer = trace.get_tracer(__name__)

        async def custom_route_handler(request: Request) -> Response:
            with tracer.start_as_current_span(f"{request.scope['route'].name}_handler"):
                response: Response = await original_route_handler(request)
                return response

        return custom_route_handler


def setup_telemetry(app: FastAPI) -> None:
    """
    Setup OpenTelemetry for the FastAPI application.
    """
    if (
        not settings.OTEL_ENABLED
        or settings.ENV == "test"
        or os.getenv("ENV") == "test"
        or os.getenv("OTEL_SDK_DISABLED") == "true"
    ):
        return

    resource = Resource.create(
        attributes={
            "service.name": settings.PROJECT_NAME,
            "service.version": settings.PROJECT_VERSION,
            "deployment.environment": settings.ENV,
        }
    )

    utils = TracerProvider(resource=resource)
    trace.set_tracer_provider(utils)

    otlp_exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)

    span_processor = BatchSpanProcessor(otlp_exporter)
    utils.add_span_processor(span_processor)

    # Instrument Pydantic Validation (Monkey Patch)
    instrument_fastapi_validation()

    # Instrument FastAPI (exclude noisy internal endpoints from traces)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=utils,
        excluded_urls="health,metrics,openapi.json,docs,redoc,trace-test",
    )

    # Instrument AsyncPG
    AsyncPGInstrumentor().instrument(tracer_provider=utils)

    # Instrument Redis
    RedisInstrumentor().instrument(tracer_provider=utils)
