"""Explicit node lifecycle states."""

from enum import StrEnum


class LifecycleState(StrEnum):
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"