"""Контроль выгрузки из 1С: ошибка на листе «Ошибки», если пакета нет больше 2 часов (в часы
с 6:00 до 23:00 по Москве) - см. app/services/import_monitor.py."""

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bay import ISSUE_IMPORT_STALE, BayIssue
from app.models.import_batch import ImportBatch
from app.services import bay_planner, import_monitor

MSK = timezone(timedelta(hours=3))


def _batch(db: Session, received: datetime, status: str = "success") -> None:
    db.add(
        ImportBatch(
            batch_id=f"t-{received.isoformat()}-{status}",
            source="alpha-auto",
            entity="work_orders",
            exported_at=received,
            received_at=received,
            records_received=1,
            status=status,
        )
    )
    db.commit()


def _issues(db: Session) -> list[BayIssue]:
    db.expire_all()
    return list(db.scalars(select(BayIssue).where(BayIssue.kind == ISSUE_IMPORT_STALE)))


def test_no_batches_at_all_gives_no_error(db_session: Session) -> None:
    assert import_monitor.check(db_session, datetime(2026, 11, 20, 12, 0, tzinfo=MSK)) is None


def test_silence_over_two_hours_in_working_hours_opens_one_error_and_a_batch_closes_it(
    db_session: Session,
) -> None:
    _batch(db_session, datetime(2026, 11, 20, 10, 0, tzinfo=MSK))

    assert import_monitor.check(db_session, datetime(2026, 11, 20, 11, 59, tzinfo=MSK)) is None
    assert import_monitor.check(db_session, datetime(2026, 11, 20, 12, 5, tzinfo=MSK)) == "opened"
    assert import_monitor.check(db_session, datetime(2026, 11, 20, 13, 0, tzinfo=MSK)) is None
    [issue] = _issues(db_session)
    assert "20.11 10:00" in issue.message and issue.bay_id is None
    assert issue.resolved_at is None

    _batch(db_session, datetime(2026, 11, 20, 13, 10, tzinfo=MSK))
    assert (
        import_monitor.check(db_session, datetime(2026, 11, 20, 13, 15, tzinfo=MSK)) == "resolved"
    )
    [issue] = _issues(db_session)
    assert issue.resolution == "auto" and issue.resolved_at is not None


def test_the_night_does_not_count_as_silence(db_session: Session) -> None:
    _batch(db_session, datetime(2026, 11, 20, 22, 30, tzinfo=MSK))

    # Ночью (после 23:00 и до 6:00) выгрузки нет по расписанию.
    assert import_monitor.check(db_session, datetime(2026, 11, 21, 3, 0, tzinfo=MSK)) is None
    assert import_monitor.check(db_session, datetime(2026, 11, 21, 7, 0, tzinfo=MSK)) is None
    # 30 минут вечером + 90 минут с 6:00 = 2 часа; ошибка - сразу после.
    assert import_monitor.check(db_session, datetime(2026, 11, 21, 7, 40, tzinfo=MSK)) == "opened"


def test_failed_batches_do_not_count_as_data(db_session: Session) -> None:
    _batch(db_session, datetime(2026, 11, 20, 10, 0, tzinfo=MSK))
    _batch(db_session, datetime(2026, 11, 20, 12, 0, tzinfo=MSK), status="error")

    assert import_monitor.check(db_session, datetime(2026, 11, 20, 12, 30, tzinfo=MSK)) == "opened"


def test_the_error_is_listed_on_the_errors_sheet_without_a_bay(db_session: Session) -> None:
    _batch(db_session, datetime(2026, 11, 20, 10, 0, tzinfo=MSK))
    import_monitor.check(db_session, datetime(2026, 11, 20, 13, 0, tzinfo=MSK).astimezone(UTC))

    items = [
        i for i in bay_planner.list_issues(db_session, status="open") if i["kind"] == "import_stale"
    ]

    assert len(items) >= 1
    assert items[0]["bay_id"] is None and items[0]["bay_name"] == "Импорт из 1С"
