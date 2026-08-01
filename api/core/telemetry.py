from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from api.constants import Environments
from api.core.config import settings


def setup_telemetry(app: FastAPI) -> None:
    """
    Setup OpenTelemetry for the FastAPI application.
    Instruments FastAPI, AsyncPG, Redis, HTTPX, Botocore (AWS/S3), and Logging.
    """
    if not settings.OTEL_ENABLED or settings.ENV == Environments.TEST.value:
        return

    resource = Resource.create(
        attributes={
            "service.name": settings.PROJECT_NAME,
            "service.version": settings.PROJECT_VERSION,
            "deployment.environment": settings.ENV,
        }
    )

    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    otlp_exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
    span_processor = BatchSpanProcessor(otlp_exporter)
    provider.add_span_processor(span_processor)

    # 1. Instrument FastAPI (HTTP requests)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="health,metrics,openapi.json,docs,redoc",
    )

    # 2. Instrument Database (AsyncPG SQL queries)
    AsyncPGInstrumentor().instrument(tracer_provider=provider)

    # 3. Instrument Cache (Redis commands)
    RedisInstrumentor().instrument(tracer_provider=provider)

    # 4. Instrument Outbound HTTP (HTTPX calls)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)

    # 5. Instrument AWS S3 & Cloud Services (Botocore calls)
    BotocoreInstrumentor().instrument(tracer_provider=provider)

    # 6. Instrument Logging (attaches trace_id and span_id to log records)
    LoggingInstrumentor().instrument(set_logging_format=True)
