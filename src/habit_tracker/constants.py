"""Constants used across the application."""
from enum import Enum


class TrackerStatus(int, Enum):
    """Status of a tracker entry.

    0 = not completed
    1 = skipped
    2 = completed
    """

    NOT_COMPLETED = 0
    SKIPPED = 1
    COMPLETED = 2
