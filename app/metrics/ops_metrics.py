from prometheus_client import Counter, Histogram, Gauge


SUPPORT_TICKETS_TOTAL = Counter(
    "ops_support_tickets_total",
    "Total support tickets",
    ["status", "priority"]
)


SUPPORT_ESCALATIONS_TOTAL = Counter(
    "ops_support_escalations_total",
    "Total escalated support issues"
)


SUPPORT_RESOLUTION_TIME_SECONDS = Histogram(
    "ops_support_resolution_time_seconds",
    "Time taken to resolve support tickets in seconds",
    buckets=[60, 300, 900, 1800, 3600, 7200, 86400]
)


ATRISK_LEARNERS_COUNT = Gauge(
    "ops_atrisk_learners_count",
    "Current count of at-risk learners",
    ["risk_level"]
)