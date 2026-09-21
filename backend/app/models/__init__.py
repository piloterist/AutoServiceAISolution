"""Import all ORM models here so Base.metadata is fully populated for Alembic
autogenerate and for `Base.metadata.create_all()` in tests.
"""

from app.models.app_settings import AppSettings
from app.models.department import Department
from app.models.import_batch import ImportBatch
from app.models.schedule_audit_log import ScheduleAuditLog
from app.models.slesarka_status import SlesarkaStatus
from app.models.user import User
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLaborLine, WorkOrderPartLine
from app.models.work_order_payment_event import WorkOrderPaymentEvent
from app.models.work_order_payment_history import WorkOrderPaymentHistory
from app.models.work_order_status_history import WorkOrderStatusHistory
from app.models.workshop import Workshop

__all__ = [
    "WorkOrder",
    "ImportBatch",
    "WorkOrderLaborLine",
    "WorkOrderPartLine",
    "WorkOrderStatusHistory",
    "WorkOrderPaymentHistory",
    "WorkOrderPaymentEvent",
    "AppSettings",
    "Department",
    "Workshop",
    "User",
    "SlesarkaStatus",
    "ScheduleAuditLog",
]
