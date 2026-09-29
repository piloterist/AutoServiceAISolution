"""Provider-agnostic call statistics, computed from our own telephony_calls
table (models.call_record.CallRecord) rather than from a live provider
connection - the point of the "universal stats page" the operator asked
for: this module doesn't know or care that today's only provider is Zeon
(see services/zeon_client.py, which is where any provider-specific shape
gets normalized away before a row ever reaches this module).

The missed-call outcome analysis (`_analyze_missed`) and the day summary
(`compute_day_stats`) are a faithful port of Zeon_AI/stats.py's
`analyze_missed()`/`build_stats()` - same field names, same thresholds
(SHORT_ABANDON_SEC, SLA_ANSWER_SEC, CALLBACK_WINDOW), same outcome
categories - just reading from our DB instead of calling Zeon's API and
writing a Статистика.json file directly. Recording/transcript fields that
existed in that script (has_record, audio_file, transcript_file,
with_recording) have no source in telephony_calls yet, since that pipeline
is a separate, later piece of this feature (call export + Yandex
SpeechKit), so they're left at their empty/False defaults here.

compute_source_summary() is new: a per-source (models.phone_source.PhoneSource)
rollup across a date range, built from the same analyze_missed() outcome
categories, for Settings -> IP-телефония's "Итог по каждому источнику"
table.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.call_record import CALL_TYPE_IN, CALL_TYPE_OUT, CallRecord
from app.models.phone_source import GROUP_OTHER, SOURCE_GROUPS, PhoneSource

CALLBACK_WINDOW = timedelta(hours=24)
SHORT_ABANDON_SEC = 5
SLA_ANSWER_SEC = 20

# Same reasoning as zeon_client._MSK: Russia has used a flat UTC+3 with no
# DST since 2014, so this is a plain fixed-offset round trip, not a real
# timezone lookup.
_MSK = timezone(timedelta(hours=3))


def _msk_naive_to_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=_MSK).astimezone(UTC)


def _utc_to_msk_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_MSK).replace(tzinfo=None)


@dataclass
class _Rec:
    """Mirrors Zeon_AI/stats.py's `Rec` - a normalized call as seen by the
    stats calculations - but built from a CallRecord row instead of a raw
    Zeon API dict."""

    id: str
    time: datetime  # naive Moscow-local, like stats.py's Rec.time
    type: str
    client: str
    operator: str
    line: str  # stats.py's Rec.dst
    lost: list[str]
    wait: int
    talk: int

    @property
    def answered(self) -> bool:
        return self.talk > 0


def _row_to_rec(row: CallRecord) -> _Rec:
    return _Rec(
        id=row.external_id,
        time=_utc_to_msk_naive(row.occurred_at),
        type=row.call_type,
        client=row.client or "",
        operator=row.operator or "",
        line=row.line or "",
        lost=list(row.rang_not_answered or []),
        wait=row.wait_sec,
        talk=row.talk_sec,
    )


def _num_stats(values: list[int | float]) -> dict:
    if not values:
        return {"count": 0}
    vs = sorted(values)
    p90 = vs[min(len(vs) - 1, int(round(0.9 * (len(vs) - 1))))]
    return {
        "count": len(vs),
        "sum": round(sum(vs), 1),
        "avg": round(statistics.mean(vs), 1),
        "median": round(statistics.median(vs), 1),
        "p90": round(p90, 1),
        "max": round(vs[-1], 1),
    }


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


@dataclass
class MissedClient:
    client: str
    first_missed: datetime
    missed_attempts: list[_Rec] = field(default_factory=list)
    outcome: str = "no_reaction"
    first_callback: _Rec | None = None
    reached_callback: _Rec | None = None
    client_recall: _Rec | None = None
    had_answered_before: bool = False


def _analyze_missed(period_recs: list[_Rec], later_recs: list[_Rec]) -> list[MissedClient]:
    """Unique missed clients within `period_recs` and their outcome within
    CALLBACK_WINDOW of their first miss - `later_recs` extends the lookup
    window past the end of the reporting period so a miss near the edge
    still gets its real outcome. Ported from stats.py::analyze_missed."""
    all_recs = sorted(period_recs + later_recs, key=lambda r: r.time)
    by_client: dict[str, list[_Rec]] = defaultdict(list)
    for r in all_recs:
        if r.client:
            by_client[r.client].append(r)

    result: dict[str, MissedClient] = {}
    for r in sorted(period_recs, key=lambda r: r.time):
        if r.type == "IN" and not r.answered and r.client:
            mc = result.get(r.client)
            if mc is None:
                mc = result[r.client] = MissedClient(r.client, r.time)
                mc.had_answered_before = any(
                    x.type == "IN"
                    and x.answered
                    and x.time < r.time
                    and x.time.date() == r.time.date()
                    for x in by_client[r.client]
                )
            mc.missed_attempts.append(r)

    for mc in result.values():
        window_end = mc.first_missed + CALLBACK_WINDOW
        after = [x for x in by_client[mc.client] if mc.first_missed < x.time <= window_end]
        outs = [x for x in after if x.type == "OUT"]
        recalls = [x for x in after if x.type == "IN" and x.answered]
        mc.first_callback = outs[0] if outs else None
        mc.reached_callback = next((x for x in outs if x.answered), None)
        mc.client_recall = recalls[0] if recalls else None
        if mc.reached_callback:
            mc.outcome = "called_back_reached"
        elif outs:
            mc.outcome = "called_back_not_reached"
        elif recalls:
            mc.outcome = "client_called_back"
    return sorted(result.values(), key=lambda m: m.first_missed)


def parse_operator_names(value: str | None) -> dict[str, str]:
    """ "302:Алексей,303:Мария" -> {"302": "Алексей", "303": "Мария"} - the
    format TelephonySettings.operator_names is stored in."""
    names: dict[str, str] = {}
    for part in (value or "").split(","):
        if ":" in part:
            ext, name = part.split(":", 1)
            if ext.strip() and name.strip():
                names[ext.strip()] = name.strip()
    return names


def _fetch_recs(db: Session, start_utc: datetime, end_utc: datetime) -> list[_Rec]:
    rows = db.scalars(
        select(CallRecord).where(
            CallRecord.occurred_at >= start_utc, CallRecord.occurred_at < end_utc
        )
    ).all()
    return [_row_to_rec(r) for r in rows]


def _period_and_tail_recs(
    db: Session, start_day: date, end_day: date
) -> tuple[list[_Rec], list[_Rec]]:
    period_start_utc = _msk_naive_to_utc(datetime.combine(start_day, time.min))
    period_end_utc = _msk_naive_to_utc(datetime.combine(end_day + timedelta(days=1), time.min))
    now_utc = datetime.now(UTC)

    period_recs = _fetch_recs(db, period_start_utc, period_end_utc)
    tail_end_utc = min(period_end_utc + CALLBACK_WINDOW, now_utc)
    later_recs = (
        _fetch_recs(db, period_end_utc, tail_end_utc) if tail_end_utc > period_end_utc else []
    )
    return period_recs, later_recs


def _build_by_operator(
    period_recs: list[_Rec],
    outbound: list[_Rec],
    inbound: list[_Rec],
    ans_in: list[_Rec],
    callback_ids: dict[str, MissedClient],
    known_operators: Iterable[str],
    operator_names: Mapping[str, str],
) -> list[dict]:
    ops: set[str] = set(known_operators)
    for r in period_recs:
        if r.operator and r.type in ("IN", "OUT"):
            ops.add(r.operator)
        ops.update(r.lost)
    ops.discard("")

    by_operator = []
    for op in sorted(ops, key=lambda x: (not x.isdigit(), x.zfill(6))):
        o_in = [r for r in ans_in if r.operator == op]
        o_out = [r for r in outbound if r.operator == op]
        rang = [r for r in inbound if op in r.lost]
        rang_lost = [r for r in rang if not r.answered]
        o_cb = [r for r in o_out if r.id in callback_ids]
        activity = sorted(r.time for r in o_in + o_out)
        by_operator.append(
            {
                "operator": op,
                "name": operator_names.get(op),
                "inbound_answered": len(o_in),
                "inbound_answered_share_pct": _pct(len(o_in), len(ans_in)),
                "inbound_talk_sec": _num_stats([r.talk for r in o_in]),
                "inbound_wait_before_answer_sec": _num_stats([r.wait for r in o_in]),
                "rang_not_answered": len(rang),
                "rang_not_answered_answered_by_colleague": len(rang) - len(rang_lost),
                "rang_not_answered_lost": len(rang_lost),
                "pickup_rate_pct": _pct(len(o_in), len(o_in) + len(rang)),
                "outbound_total": len(o_out),
                "outbound_answered": sum(1 for r in o_out if r.answered),
                "outbound_talk_sec": _num_stats([r.talk for r in o_out if r.answered]),
                "callbacks_to_missed": len(o_cb),
                "callbacks_to_missed_reached": sum(1 for r in o_cb if r.answered),
                "total_talk_sec": sum(r.talk for r in o_in) + sum(r.talk for r in o_out),
                "first_call": activity[0].strftime("%H:%M:%S") if activity else None,
                "last_call": activity[-1].strftime("%H:%M:%S") if activity else None,
                "in_points_list": op in set(known_operators),
            }
        )
    return by_operator


def compute_day_stats(
    db: Session,
    day: date,
    *,
    operator_names: Mapping[str, str] | None = None,
    known_operators: Iterable[str] = (),
) -> dict:
    """One day's stats, same shape as Zeon_AI/stats.py's build_stats()
    output (minus the audio/transcript-derived fields - see module
    docstring)."""
    operator_names = operator_names or {}
    now = datetime.now(_MSK).replace(tzinfo=None)
    day_recs, later_recs = _period_and_tail_recs(db, day, day)

    inbound = [r for r in day_recs if r.type == "IN"]
    outbound = [r for r in day_recs if r.type == "OUT"]
    local = [r for r in day_recs if r.type not in ("IN", "OUT")]
    ans_in = [r for r in inbound if r.answered]
    miss_in = [r for r in inbound if not r.answered]
    short = [r for r in miss_in if r.wait < SHORT_ABANDON_SEC]
    missed = _analyze_missed(day_recs, later_recs)
    outcomes = Counter(m.outcome for m in missed)
    delays = [
        (m.first_callback.time - m.first_missed).total_seconds() / 60
        for m in missed
        if m.first_callback
    ]
    window_complete = now >= datetime.combine(day, datetime.max.time()) + CALLBACK_WINDOW

    callback_ids: dict[str, MissedClient] = {
        m.first_callback.id: m for m in missed if m.first_callback
    }
    callback_ids.update({m.reached_callback.id: m for m in missed if m.reached_callback})

    summary = {
        "records_total": len(day_recs),
        "by_type": dict(Counter(r.type for r in day_recs)),
        "inbound": {
            "total": len(inbound),
            "answered": len(ans_in),
            "missed": len(miss_in),
            "missed_pct": _pct(len(miss_in), len(inbound)),
            "missed_short_abandon": len(short),
            "missed_excluding_short_abandon": len(miss_in) - len(short),
            "unique_callers": len({r.client for r in inbound if r.client}),
            "unique_missed_callers": len(missed),
            "unique_missed_never_answered_that_day": sum(
                1 for m in missed if not m.had_answered_before
            ),
            "sla_share_pct": _pct(sum(1 for r in ans_in if r.wait <= SLA_ANSWER_SEC), len(inbound)),
            "wait_answered_sec": _num_stats([r.wait for r in ans_in]),
            "wait_missed_sec": _num_stats([r.wait for r in miss_in]),
            "talk_sec": _num_stats([r.talk for r in ans_in]),
        },
        "missed_clients_outcome": {
            "called_back_reached": outcomes["called_back_reached"],
            "called_back_not_reached": outcomes["called_back_not_reached"],
            "client_called_back": outcomes["client_called_back"],
            "no_reaction": outcomes["no_reaction"],
            "no_reaction_pct": _pct(outcomes["no_reaction"], len(missed)),
            "callback_delay_min": _num_stats(delays),
        },
        "outbound": {
            "total": len(outbound),
            "answered": sum(1 for r in outbound if r.answered),
            "not_answered": sum(1 for r in outbound if not r.answered),
            "answered_pct": _pct(sum(1 for r in outbound if r.answered), len(outbound)),
            "unique_clients": len({r.client for r in outbound if r.client}),
            "callbacks_to_missed": len({r.id for r in outbound if r.id in callback_ids}),
            "talk_sec": _num_stats([r.talk for r in outbound if r.answered]),
        },
        "internal": {"total": len(local), "answered": sum(1 for r in local if r.answered)},
    }

    by_operator = _build_by_operator(
        day_recs, outbound, inbound, ans_in, callback_ids, known_operators, operator_names
    )

    by_hour = []
    for h in range(24):
        hin = [r for r in inbound if r.time.hour == h]
        hout = [r for r in outbound if r.time.hour == h]
        if not hin and not hout:
            continue
        hans = [r for r in hin if r.answered]
        by_hour.append(
            {
                "hour": h,
                "inbound": len(hin),
                "answered": len(hans),
                "missed": len(hin) - len(hans),
                "missed_short_abandon": sum(
                    1 for r in hin if not r.answered and r.wait < SHORT_ABANDON_SEC
                ),
                "outbound": len(hout),
                "avg_wait_answered_sec": round(statistics.mean(r.wait for r in hans), 1)
                if hans
                else None,
                "operators_active": len({r.operator for r in hans + hout if r.operator}),
            }
        )

    by_line = []
    missed_by_client = {m.client: m for m in missed}
    for line in sorted({r.line for r in inbound}):
        lin = [r for r in inbound if r.line == line]
        lans = [r for r in lin if r.answered]
        lclients = {r.client for r in lin if r.client}
        lmissed = [
            missed_by_client[c]
            for c in lclients
            if c in missed_by_client
            and any(a.line == line for a in missed_by_client[c].missed_attempts)
        ]
        by_line.append(
            {
                "line": line,
                "inbound": len(lin),
                "answered": len(lans),
                "missed": len(lin) - len(lans),
                "missed_pct": _pct(len(lin) - len(lans), len(lin)),
                "unique_callers": len(lclients),
                "unique_missed_callers": len(lmissed),
                "no_reaction": sum(1 for m in lmissed if m.outcome == "no_reaction"),
                "avg_wait_answered_sec": round(statistics.mean(r.wait for r in lans), 1)
                if lans
                else None,
                "talk_sec_total": sum(r.talk for r in lans),
            }
        )
    by_line.sort(key=lambda x: -x["inbound"])

    def ts(dt: datetime | None) -> str | None:
        return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None

    missed_list = [
        {
            "client": m.client,
            "first_missed_at": ts(m.first_missed),
            "missed_attempts": len(m.missed_attempts),
            "lines": sorted({a.line for a in m.missed_attempts}),
            "rang_operators": sorted({op for a in m.missed_attempts for op in a.lost}),
            "wait_sec": [a.wait for a in m.missed_attempts],
            "short_abandon_only": all(a.wait < SHORT_ABANDON_SEC for a in m.missed_attempts),
            "had_answered_call_earlier_that_day": m.had_answered_before,
            "outcome": m.outcome,
            "first_callback_at": ts(m.first_callback.time) if m.first_callback else None,
            "callback_delay_min": round(
                (m.first_callback.time - m.first_missed).total_seconds() / 60, 1
            )
            if m.first_callback
            else None,
            "callback_operator": m.first_callback.operator if m.first_callback else None,
            "reached_at": ts(m.reached_callback.time) if m.reached_callback else None,
            "reached_by_operator": m.reached_callback.operator if m.reached_callback else None,
            "client_recall_answered_at": ts(m.client_recall.time) if m.client_recall else None,
            "client_recall_operator": m.client_recall.operator if m.client_recall else None,
        }
        for m in missed
    ]

    calls = [
        {
            "id": r.id,
            "time": r.time.strftime("%H:%M:%S"),
            "type": r.type,
            "client": r.client or None,
            "line": r.line if r.type == "IN" else None,
            "operator": r.operator or None,
            "rang_not_answered": r.lost or None,
            "wait_sec": r.wait,
            "talk_sec": r.talk,
            "answered": r.answered,
            "is_callback_to_missed": r.id in callback_ids,
        }
        for r in sorted(day_recs, key=lambda r: r.time)
    ]

    return {
        "meta": {
            "date": day.isoformat(),
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": "Europe/Moscow",
            "callback_window_hours": int(CALLBACK_WINDOW.total_seconds() // 3600),
            "callback_window_complete": window_complete,
            "short_abandon_sec": SHORT_ABANDON_SEC,
            "sla_answer_sec": SLA_ANSWER_SEC,
            "operators_known": sorted(known_operators),
            "operator_names": dict(operator_names),
        },
        "summary": summary,
        "by_operator": by_operator,
        "by_hour": by_hour,
        "by_line": by_line,
        "missed_clients": missed_list,
        "calls": calls,
    }


@dataclass
class SourceSummaryRow:
    line_code: str
    name: str
    caption: str | None
    group_name: str
    sort_order: int
    inbound_total: int
    answered: int
    missed: int
    missed_pct: float | None
    unique_callers: int
    unique_missed_callers: int
    outcome_called_back_reached: int
    outcome_called_back_not_reached: int
    outcome_client_called_back: int
    outcome_no_reaction: int
    reached_pct: float | None  # доля уникальных пропущенных БЕЗ исхода no_reaction


def _unknown_source(line: str) -> PhoneSource:
    src = PhoneSource(
        line_code=line,
        name=f"Неизвестная линия {line}" if line else "Без линии",
        group_name=GROUP_OTHER,
    )
    src.sort_order = 9999
    return src


def compute_source_summary(
    db: Session, start_day: date, end_day: date, phone_sources: Iterable[PhoneSource]
) -> list[SourceSummaryRow]:
    """ "Итог по каждому источнику" - one row per PhoneSource (falling back
    to a synthetic "unknown line" row for any line seen in calls with no
    matching phone_sources entry), aggregated over [start_day, end_day].

    Reuses the exact same missed-call outcome analysis as compute_day_stats
    (_analyze_missed), just run once over the whole range instead of per
    day, with the 24h callback-window tail extending past end_day so misses
    near the end of the range still get their real outcome."""
    period_recs, later_recs = _period_and_tail_recs(db, start_day, end_day)
    inbound = [r for r in period_recs if r.type == "IN"]
    missed = _analyze_missed(period_recs, later_recs)
    missed_by_client = {m.client: m for m in missed}

    sources_by_line = {s.line_code: s for s in phone_sources}
    lines_seen = {r.line for r in inbound if r.line}
    for line in lines_seen:
        sources_by_line.setdefault(line, _unknown_source(line))

    rows: list[SourceSummaryRow] = []
    for line, source in sources_by_line.items():
        lin = [r for r in inbound if r.line == line]
        lans = [r for r in lin if r.answered]
        lclients = {r.client for r in lin if r.client}
        lmissed = [
            missed_by_client[c]
            for c in lclients
            if c in missed_by_client
            and any(a.line == line for a in missed_by_client[c].missed_attempts)
        ]
        outcome_counts = Counter(m.outcome for m in lmissed)
        unique_missed = len(lmissed)
        no_reaction = outcome_counts["no_reaction"]
        rows.append(
            SourceSummaryRow(
                line_code=line,
                name=source.name,
                caption=source.caption,
                group_name=source.group_name,
                sort_order=source.sort_order,
                inbound_total=len(lin),
                answered=len(lans),
                missed=len(lin) - len(lans),
                missed_pct=_pct(len(lin) - len(lans), len(lin)),
                unique_callers=len(lclients),
                unique_missed_callers=unique_missed,
                outcome_called_back_reached=outcome_counts["called_back_reached"],
                outcome_called_back_not_reached=outcome_counts["called_back_not_reached"],
                outcome_client_called_back=outcome_counts["client_called_back"],
                outcome_no_reaction=no_reaction,
                reached_pct=_pct(unique_missed - no_reaction, unique_missed),
            )
        )
    group_order = {g: i for i, g in enumerate(SOURCE_GROUPS)}
    rows.sort(
        key=lambda r: (group_order.get(r.group_name, len(SOURCE_GROUPS)), r.sort_order, r.name)
    )
    return rows


@dataclass
class LineCallEvent:
    time: str  # "YYYY-MM-DD HH:MM:SS", Moscow-local
    direction: str  # "in" | "out"
    role: str  # "incoming" | "callback" | "client_recall"
    client: str | None
    operator: str | None
    # Extensions that also rang but didn't pick up (Zeon's `lost`, minus
    # whichever extension ended up as `operator`) - together, `operator`
    # (if answered) and this field are every extension the call rang on;
    # both empty means the call never got routed to any extension at all
    # (e.g. abandoned in an IVR before ringing anyone).
    rang_not_answered: list[str]
    answered: bool
    wait_sec: int
    talk_sec: int


def list_line_calls(
    db: Session, start_day: date, end_day: date, line_code: str
) -> list[LineCallEvent]:
    """Chronological drill-down for one source row on the "Итог по каждому
    источнику" page (expand-a-row): every inbound call on `line_code`
    within [start_day, end_day], and - for each one that was missed -
    every subsequent call involving that same client within the 24h
    callback window (our own callback attempts, and/or the client calling
    back themselves), wherever that follow-up call landed.

    Deliberately not reusing `_analyze_missed`'s MissedClient objects (which
    only keep the *first* callback/recall): the operator asked to see every
    attempt in order, not just the first one."""
    period_recs, later_recs = _period_and_tail_recs(db, start_day, end_day)
    all_recs = period_recs + later_recs
    by_client: dict[str, list[_Rec]] = defaultdict(list)
    for r in all_recs:
        if r.client:
            by_client[r.client].append(r)

    line_in_recs = [r for r in period_recs if r.type == "IN" and r.line == line_code]

    seen_ids: set[str] = set()
    events: list[LineCallEvent] = []

    def add(rec: _Rec, role: str) -> None:
        if rec.id in seen_ids:
            return
        seen_ids.add(rec.id)
        events.append(
            LineCallEvent(
                time=rec.time.strftime("%Y-%m-%d %H:%M:%S"),
                direction="in" if rec.type == "IN" else "out",
                role=role,
                client=rec.client or None,
                operator=rec.operator or None,
                rang_not_answered=list(rec.lost),
                answered=rec.answered,
                wait_sec=rec.wait,
                talk_sec=rec.talk,
            )
        )

    for r in sorted(line_in_recs, key=lambda r: r.time):
        add(r, "incoming")
        if not r.answered and r.client:
            window_end = r.time + CALLBACK_WINDOW
            for x in sorted(by_client[r.client], key=lambda x: x.time):
                if r.time < x.time <= window_end:
                    add(x, "callback" if x.type == "OUT" else "client_recall")

    events.sort(key=lambda e: e.time)
    return events


# ---- Открытые пропущенные (значок на Планировщике) -------------------------

# A real conversation, not just Zeon's own answered=talk_sec>0 - a call that
# connects and is hung up in 1-2s isn't a resolved contact (per product
# feedback: "важно, чтобы именно дозвонились... хотя бы 5 секунд"). Distinct
# from SHORT_ABANDON_SEC above, which is about how long an *unanswered* call
# rang before the caller gave up, not about a real answered one.
MIN_REAL_TALK_SEC = 5


@dataclass
class OpenMissedCall:
    id: str
    client: str
    line: str | None
    source_label: str | None  # only set for an inbound miss - see below
    direction: str  # "in" | "callback"
    time: str  # "YYYY-MM-DD HH:MM:SS", Moscow-local - same convention as LineCallEvent
    operator: str | None
    # Every row here is unanswered by construction (that's what "open
    # missed" means), so this is always the FULL set of extensions that
    # rang for an inbound miss (Zeon never puts the eventual answerer in
    # `lost`, and there is none here) - empty means the call never got
    # routed to any extension at all. Not meaningful for an outbound
    # callback attempt (direction="callback"), so always [] there -
    # `operator` already says which of our own extensions placed it.
    rang_not_answered: list[str]


def _missed_badge_window_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(UTC)
    today_msk = now.astimezone(_MSK).date()
    start_msk = datetime.combine(today_msk - timedelta(days=1), time.min)
    end_msk = datetime.combine(today_msk + timedelta(days=1), time.min)
    return _msk_naive_to_utc(start_msk), _msk_naive_to_utc(end_msk)


def get_open_missed_calls(db: Session, *, now: datetime | None = None) -> list[OpenMissedCall]:
    """Missed calls from the last 2 Moscow-calendar days (today + yesterday)
    that still have no real callback - feeds the Planner's phone-icon badge
    (see components/planner/PlannerShell.tsx). Deliberately different rules
    from `_analyze_missed` above, which answers a different question (a
    day's missed-caller outcomes for reporting, 24h rolling callback
    window, "answered" = any talk_sec > 0):

    - A rolling 2-day *calendar* window, not a 24h rolling one - a miss
      simply stops appearing once its own day is no longer "today" or
      "yesterday" in Moscow time, regardless of whether it was ever
      resolved (confirmed product decision: "они уйдут по старости").
    - "Reached" requires >= MIN_REAL_TALK_SEC of real talk time, not just
      answered=talk_sec>0.
    - One real contact (either direction, whichever operator) clears EVERY
      still-open miss from that same number in the window, not just the
      one immediately before it (confirmed product decision).
    - A number only appears here at all if THEY called us and we missed it
      at least once in the window - a purely outbound thread (we called a
      number that never called us, and never reached them) is not shown,
      no matter how many attempts (confirmed product decision, 2026-09-29:
      showing that as an alarm is "тупо" - the badge answers "who called us
      and we still haven't reached", not "who did we fail to reach").

    Processes each client's calls in this window in chronological order: a
    real (>=5s) contact clears everything queued so far for that number; an
    unanswered IN call queues as "звонил, не дозвонился"; an unanswered OUT
    call queues as "перезвонили, не дозвонились" - but only for a client
    that has at least one unanswered IN call somewhere in the window (their
    outbound attempts are then shown alongside it as "still trying", not as
    a stand-alone alarm). A briefly-answered call under 5s resolves nothing
    but isn't queued as a fresh miss either, since the provider does
    consider it answered.
    """
    start_utc, end_utc = _missed_badge_window_utc(now)

    rows = (
        db.execute(
            select(CallRecord)
            .where(
                CallRecord.occurred_at >= start_utc,
                CallRecord.occurred_at < end_utc,
                CallRecord.call_type.in_((CALL_TYPE_IN, CALL_TYPE_OUT)),
                CallRecord.client.is_not(None),
                CallRecord.client != "",
            )
            .order_by(CallRecord.client, CallRecord.occurred_at)
        )
        .scalars()
        .all()
    )

    sources_by_line = {s.line_code: s for s in db.execute(select(PhoneSource)).scalars().all()}

    def source_label(line: str | None) -> str | None:
        if not line:
            return None
        source = sources_by_line.get(line)
        return source.name if source else f"Неизвестная линия {line}"

    clients_with_inbound_miss = {
        row.client for row in rows if row.call_type == CALL_TYPE_IN and not row.answered
    }

    open_by_client: dict[str, list[CallRecord]] = {}
    for row in rows:
        if row.client not in clients_with_inbound_miss:
            continue  # never called us - not the badge's concern, see docstring
        bucket = open_by_client.setdefault(row.client, [])
        if row.talk_sec >= MIN_REAL_TALK_SEC:
            bucket.clear()
        elif not row.answered:
            bucket.append(row)
        # answered but talk_sec in [1, MIN_REAL_TALK_SEC) - too short to
        # count as reached or as a fresh miss; simply ignored.

    open_calls = [
        OpenMissedCall(
            id=row.external_id,
            client=row.client or "",
            line=row.line,
            source_label=source_label(row.line) if row.call_type == CALL_TYPE_IN else None,
            direction="in" if row.call_type == CALL_TYPE_IN else "callback",
            time=_utc_to_msk_naive(row.occurred_at).strftime("%Y-%m-%d %H:%M:%S"),
            operator=row.operator or None,
            rang_not_answered=(
                list(row.rang_not_answered or []) if row.call_type == CALL_TYPE_IN else []
            ),
        )
        for pending in open_by_client.values()
        for row in pending
    ]
    open_calls.sort(key=lambda c: c.time, reverse=True)
    return open_calls
