"""Prometheus KPI definitions and update logic for Ops Console support metrics.

Defines Counter/Gauge/Histogram metrics for support volume, escalation rate,
and resolution time (estimate), and provides a function to refresh them
from the read-only Session/EscalationTicket stores.
"""

from prometheus_client import Counter, Gauge, Histogram


support_sessions_total = Counter(
    "ops_support_sessions_total",
    "Total number of support sessions observed",
)

escalation_rate = Gauge(
    "ops_escalation_rate",
    "Fraction of sessions that resulted in an escalation ticket, for the last computed window",
)

resolution_time_seconds = Histogram(
    "ops_resolution_time_seconds",
    "Estimated resolution time per escalation ticket (approximation, see metrics.py docstring)",
    buckets=[60, 300, 900, 1800, 3600, 7200, 21600, 86400],
)

# NOTE: _last_known_total resets to 0 on process restart, which will
# cause one artificially large Counter increment on the first update
# after a restart (catching up to the real total). This is a known
# limitation — a durable fix would persist this value outside process
# memory (e.g. in the database). Deferred for this slice; see PR description.
_last_known_total = 0


def update_support_metrics(metrics: dict) -> None:
    """Refresh Prometheus KPIs from an already-computed support metrics dict.

    Increments support_sessions_total by only the delta since the last
    update (Counters can only increase), sets escalation_rate directly,
    and records each ticket's resolution-time estimate as a Histogram
    observation.
    """
    global _last_known_total

    current_total = sum(row["count"] for row in metrics["support_volume"])
    delta = current_total - _last_known_total
    if delta > 0:
        support_sessions_total.inc(delta)
    _last_known_total = current_total

    escalation_rate.set(metrics["escalation_rate"])

    for ticket in metrics["resolution_time"]:
        resolution_time_seconds.observe(ticket["estimated_resolution_seconds"])
