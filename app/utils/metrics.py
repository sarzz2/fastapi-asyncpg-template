import asyncio

import psutil
from fastapi import APIRouter
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    Summary,
    generate_latest,
)
from starlette.responses import Response

router = APIRouter()

REQUEST_COUNT = Counter("http_requests_total", "Total HTTP Requests", ["method", "endpoint", "status_code"])
REQUEST_LATENCY = Summary("http_request_latency_seconds", "Request latency in seconds")
REQUEST_HISTOGRAM = Histogram("http_request_duration_seconds", "Histogram for request duration", ["endpoint"])
REQUEST_IN_PROGRESS = Gauge("http_requests_in_progress", "Number of requests in progress")
CPU_USAGE = Gauge("system_cpu_usage", "Current CPU usage percentage")
MEMORY_USAGE = Gauge("system_memory_usage", "Current memory usage percentage")


@router.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def update_system_metrics():
    loop = asyncio.get_event_loop()
    while True:
        cpu_usage = await loop.run_in_executor(None, psutil.cpu_percent, 1)
        CPU_USAGE.set(cpu_usage)
        MEMORY_USAGE.set(psutil.virtual_memory().percent)
        await asyncio.sleep(5)  # Asynchronously sleep for 5 seconds
