"""Просроченные заявки с 1 октября по всем цехам + истории звонков (JSON в stdout). Только чтение.
Просрочка считается без отсечки «устарела» (30 дней) - период шире."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.services import request_control_service as s
from app.services import telephony_settings_service, telephony_stats_service
from app.services.settings_service import get_app_settings

SINCE = "2026-10-01"
MIN_TALK = 10
MSK = ZoneInfo("Europe/Moscow")

now = datetime.now(UTC)
with SessionLocal() as db:
    c = get_app_settings(db)
    cfg = SimpleNamespace(
        request_control_enabled=True,
        request_first_call_days=c.request_first_call_days,
        request_second_call_days=c.request_second_call_days,
        request_min_talk_sec=MIN_TALK,
        request_auto_disqualify_days=10000,
    )
    reqs = list(
        db.execute(
            s._candidate_requests_query(cfg, now).order_by(s._created_expr()),
            execution_options={"include_repair_requests": True},
        ).scalars()
    )
    states = s._build_states(db, reqs, cfg, now)
    sources = telephony_settings_service.list_phone_sources(db)
    out = []
    for st in states.values():
        r = st.request
        created_local = st.created_at.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S")
        if not st.overdue or created_local[:10] < SINCE:
            continue
        events = {}
        for phone in s._phones(r.phone):
            found, _ = telephony_stats_service.list_client_calls(db, phone, sources)
            for e in found:
                if e.time >= created_local:
                    events[e.call_id] = e
        calls = sorted(events.values(), key=lambda e: e.time, reverse=True)
        out.append(
            {
                "number": r.external_number,
                "department": r.department,
                "created": created_local,
                "customer": r.customer_name,
                "phone": r.phone,
                "car": r.vehicle_description,
                "amount": float(r.amount) if r.amount is not None else None,
                "overdue": st.overdue,
                "attempts": st.attempts_count,
                "calls": [
                    {
                        "time": e.time,
                        "role": e.role,
                        "answered": bool(e.answered),
                        "direction": e.direction,
                        "talk": e.talk_sec,
                    }
                    for e in calls
                ],
            }
        )
out.sort(key=lambda x: x["created"])
print(json.dumps({"since": SINCE, "requests": out}, ensure_ascii=False))
