from dataclasses import dataclass
from datetime import datetime
from typing import Any, List

# Event name constants
LOG_ERRORS_FOUND = "log.errors_found"
AI_RECOMMENDATION_READY = "ai.recommendation_ready"
AI_RECOMMENDATION_APPLIED = "ai.recommendation_applied"
CONFIG_CHANGED = "config.changed"
MODULE_ERROR = "module.error"

# Typed payloads


@dataclass
class LogErrorsFoundData:
    source: str
    errors: List[dict]
    timestamp: datetime


@dataclass
class RecommendationReadyData:
    module: str
    summary: str
    details: dict


@dataclass
class ConfigChangedData:
    key: str
    old_value: Any
    new_value: Any
