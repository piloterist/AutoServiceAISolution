"""Выгрузка просроченных заявок цеха + истории звонков в JSON (stdout). Только чтение."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.services import request_control_service as s
from app.services import telephony_settings_service, telephony_stats_service
from app.services.settings_service import get_app_settings

DEPARTMENT = "Кузовной цех (Каховка)"
MIN_TALK = 10
SINCE = "2026-10-01"
MSK = ZoneInfo("Europe/Moscow")
OUTCOMES = {
    "called_back_reached": "перезвонили, дозвонились",
    "called_back_not_reached": "перезвонили, не дозвонились",
    "client_called_back": "клиент перезвонил сам",
    "no_reaction": "без реакции",
}


def label(e) -> str:
    if e.role == "incoming":
        if e.answered:
            return "Входящий"
        return f"Входящий (пропущен) — {OUTCOMES[e.outcome]}" if e.outcome else "Входящий (пропущен)"
    if e.role == "outgoing":
        return "Исходящий" if e.answered else "Исходящий (не дозвонились)"
    if e.role == "callback":
        return "Наш перезвон" if e.answered else "Наш перезвон (не дозвонились)"
    return "Клиент перезвонил" if e.answered else "Клиент перезвонил (пропущен)"


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
        if not st.overdue or r.department != DEPARTMENT or created_local[:10] < SINCE:
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
                "created": created_local,
                "customer": r.customer_name,
                "phone": r.phone,
                "car": r.vehicle_description,
                "amount": float(r.amount) if r.amount is not None else None,
                "overdue": st.overdue,
                "deadline": (
                    st.first_deadline if st.overdue == "first" else st.second_deadline
                )
                .astimezone(MSK)
                .strftime("%Y-%m-%d"),
                "calls": [
                    {
                        "time": e.time,
                        "label": label(e),
                        "answered": bool(e.answered),
                        "direction": e.direction,
                        "role": e.role,
                        "client": e.client,
                        "operator": e.operator,
                        "source": getattr(e, "source_name", None),
                        "wait": e.wait_sec,
                        "talk": e.talk_sec,
                    }
                    for e in calls
                ],
            }
        )
out.sort(key=lambda x: x["created"])
print(
    json.dumps(
        {
            "department": DEPARTMENT,
            "min_talk": MIN_TALK,
            "since": SINCE,
            "generated": datetime.now(MSK).strftime("%Y-%m-%d %H:%M"),
            "requests": out,
        },
        ensure_ascii=False,
    )
)
