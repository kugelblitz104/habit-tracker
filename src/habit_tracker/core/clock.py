"""The one server clock read. Every stored timestamp comes from here."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Naive UTC. Naive by contract (the front-end's parseServerDate reads a
    naive value as UTC), UTC by construction rather than by the host's zone."""
    return datetime.now(UTC).replace(tzinfo=None)
