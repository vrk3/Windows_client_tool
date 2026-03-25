from core.events import (
    LOG_ERRORS_FOUND,
    AI_RECOMMENDATION_READY,
    AI_RECOMMENDATION_APPLIED,
    CONFIG_CHANGED,
    MODULE_ERROR,
    LogErrorsFoundData,
    RecommendationReadyData,
    ConfigChangedData,
)
from datetime import datetime


def test_event_constants_are_strings():
    assert isinstance(LOG_ERRORS_FOUND, str)
    assert isinstance(AI_RECOMMENDATION_READY, str)
    assert isinstance(AI_RECOMMENDATION_APPLIED, str)
    assert isinstance(CONFIG_CHANGED, str)
    assert isinstance(MODULE_ERROR, str)


def test_log_errors_found_data():
    data = LogErrorsFoundData(
        source="EventViewer",
        errors=[{"id": 1, "msg": "disk error"}],
        timestamp=datetime(2026, 3, 25, 12, 0, 0),
    )
    assert data.source == "EventViewer"
    assert len(data.errors) == 1
    assert data.timestamp.year == 2026


def test_config_changed_data():
    data = ConfigChangedData(key="app.theme", old_value="light", new_value="dark")
    assert data.key == "app.theme"
    assert data.old_value == "light"
    assert data.new_value == "dark"


def test_recommendation_ready_data():
    data = RecommendationReadyData(
        module="ai_learning", summary="Disable startup service X", details={"confidence": 0.9}
    )
    assert data.module == "ai_learning"
    assert data.summary == "Disable startup service X"
