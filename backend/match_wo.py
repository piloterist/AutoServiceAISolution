import json
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.work_order import WorkOrder
from app.services import request_control_service as s
from app.services.settings_service import get_app_settings

MSK = ZoneInfo("Europe/Moscow")
SINCE = "2026-10-01"
now = datetime.now(UTC)


def dig(p):
    return "".join(ch for ch in (p or "") if ch.isdigit())[-10:]


with SessionLocal() as db:
    c = get_app_settings(db)
    cfg = SimpleNamespace(request_control_enabled=True, request_first_call_days=c.request_first_call_days,
        request_second_call_days=c.request_second_call_days, request_min_talk_sec=10, request_auto_disqualify_days=10000)
    reqs = list(db.execute(s._candidate_requests_query(cfg, now), execution_options={"include_repair_requests": True}).scalars())
    states = s._build_states(db, reqs, cfg, now)
    req_numbers = set(db.execute(select(WorkOrder.external_number).where(WorkOrder.doc_type == "repair_request"), execution_options={"include_repair_requests": True}).scalars())
    orders = [o for o in db.execute(select(WorkOrder).where(WorkOrder.doc_type != "repair_request")).scalars() if o.external_number not in req_numbers]
    out = []
    for st in states.values():
        r = st.request
        cl = st.created_at.astimezone(MSK).strftime("%Y-%m-%d %H:%M")
        if not st.overdue or cl[:10] < SINCE:
            continue
        rphones = {dig(p) for p in s._phones(r.phone) if dig(p)}
        hits = []
        for o in orders:
            if o.department != r.department or o.document_date < st.created_at:
                continue
            by_car = bool(r.car_key and o.car_key and r.car_key == o.car_key) or bool(r.vin and o.vin and r.vin == o.vin)
            ophones = {dig(p) for p in s._phones(o.phone) if dig(p)}
            by_phone = bool(rphones & ophones)
            if by_car or by_phone:
                hits.append({"wo": o.external_number, "date": o.document_date.astimezone(MSK).strftime("%Y-%m-%d"),
                    "status": o.status, "car": by_car, "phone": by_phone, "amount": float(o.amount), "ocar": o.vehicle_description})
        out.append({"n": r.external_number, "dep": r.department, "created": cl, "car": r.vehicle_description,
            "carkey": r.car_key, "phone": r.phone, "overdue": st.overdue, "hits": hits})
print(json.dumps(out, ensure_ascii=False))
