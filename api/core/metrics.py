from prometheus_client import Counter, Gauge, Histogram

# Database Metrics
DB_QUERY_TOTAL = Counter(
    "db_query_total",
    "Total number of database queries",
    ["type"],  # e.g., 'read', 'write'
)

DB_QUERY_DURATION_SECONDS = Histogram(
    "db_query_duration_seconds",
    "Duration of database queries in seconds",
    ["type"],  # e.g., 'read', 'write'
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

DB_POOL_CONNECTIONS_IN_USE = Gauge(
    "db_pool_connections_in_use",
    "Number of database connections currently in use",
    ["pool_type", "region"],  # e.g., 'write', 'read', region name
)

DB_SLOW_QUERIES_TOTAL = Counter("db_slow_queries_total", "Total number of slow database queries (>1s)", ["type"])

# Cache / Redis Metrics
CACHE_REQUESTS_TOTAL = Counter(
    "cache_requests_total",
    "Total number of cache operations",
    ["operation"],  # e.g., 'get', 'set', 'invalidate'
)

CACHE_OPERATION_DURATION_SECONDS = Histogram(
    "cache_operation_duration_seconds",
    "Duration of cache operations in seconds",
    ["operation"],
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.5, 1.0],
)

REDIS_ERRORS_TOTAL = Counter("redis_errors_total", "Total number of Redis errors", ["operation"])

CACHE_HIT_MISS_TOTAL = Counter(
    "cache_hit_miss_total",
    "Total number of cache hits and misses",
    ["result"],  # 'hit', 'miss'
)
