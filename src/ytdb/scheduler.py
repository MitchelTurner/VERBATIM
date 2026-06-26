from __future__ import annotations

from datetime import datetime, timedelta, timezone

FREQUENCY_OPTIONS: dict[str, int | None] = {
    "manual": None,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "6h": 360,
    "12h": 720,
    "24h": 1440,
    "168h": 10080,
}


def frequency_label(frequency: str) -> str:
    labels = {
        "manual": "Manual only",
        "15m": "Every 15 minutes",
        "30m": "Every 30 minutes",
        "1h": "Every hour",
        "6h": "Every 6 hours",
        "12h": "Every 12 hours",
        "24h": "Daily",
        "168h": "Weekly",
    }
    return labels.get(frequency, frequency)


def compute_next_run(frequency: str, from_time: datetime | None = None) -> datetime | None:
    minutes = FREQUENCY_OPTIONS.get(frequency)
    if minutes is None:
        return None
    base = from_time or datetime.now(timezone.utc)
    return base + timedelta(minutes=minutes)
