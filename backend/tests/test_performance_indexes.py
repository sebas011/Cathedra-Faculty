from app.models import ActivityEvent, FacultyWorkload


def test_common_history_filters_have_indexes(client) -> None:
    # The test database is created from the same model metadata used by the app.
    assert {index.name for index in FacultyWorkload.__table__.indexes} >= {
        "ix_faculty_workloads_period_faculty"
    }
    assert {index.name for index in ActivityEvent.__table__.indexes} >= {
        "ix_activity_events_created_id"
    }
