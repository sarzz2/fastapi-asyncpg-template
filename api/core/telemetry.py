import logging

from fastapi import FastAPI
from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from api.constants import Environments
from api.core.config import settings


def setup_telemetry(app: FastAPI) -> None:
    """Setup OpenTelemetry for the FastAPI application.

    Instruments FastAPI, AsyncPG, Redis, HTTPX, Botocore (AWS/S3), and Logging.
    Exports traces, application metrics, and application logs via OTLP gRPC.
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

    # 1. Traces
    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)

    otlp_span_exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
    span_processor = BatchSpanProcessor(otlp_span_exporter)
    tracer_provider.add_span_processor(span_processor)

    # 2. Metrics (OTLP gRPC)
    otlp_metric_exporter = OTLPMetricExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
    metric_reader = PeriodicExportingMetricReader(
        otlp_metric_exporter,
        export_interval_millis=settings.OTEL_METRIC_EXPORT_INTERVAL_MS,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # 3. Logs (OTLP gRPC)
    logger_provider = LoggerProvider(resource=resource)
    _logs.set_logger_provider(logger_provider)
    otlp_log_exporter = OTLPLogExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_log_exporter))

    # Attach OTLP LoggingHandler to root, fastapi, and uvicorn loggers
    otel_log_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    for log_name in (None, "fastapi", "uvicorn", "uvicorn.access", "uvicorn.error"):
        target_logger = logging.getLogger(log_name) if log_name else logging.getLogger()
        if not any(isinstance(h, LoggingHandler) for h in target_logger.handlers):
            target_logger.addHandler(otel_log_handler)

    # 4. Instrument FastAPI (HTTP requests & HTTP metrics)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls="health,metrics,openapi.json,docs,redoc",
    )

    # 5. Instrument Database (AsyncPG SQL queries)
    AsyncPGInstrumentor().instrument(tracer_provider=tracer_provider)

    # 6. Instrument Cache (Redis commands)
    RedisInstrumentor().instrument(tracer_provider=tracer_provider)

    # 7. Instrument Outbound HTTP (HTTPX calls)
    HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider)

    # 8. Instrument AWS S3 & Cloud Services (Botocore calls)
    BotocoreInstrumentor().instrument(tracer_provider=tracer_provider)

    # 9. Instrument Logging (attaches trace_id and span_id to log records)
    LoggingInstrumentor().instrument(set_logging_format=True)
