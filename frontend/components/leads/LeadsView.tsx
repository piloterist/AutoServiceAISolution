"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import { CallRecordingPlayer } from "@/components/telephony/CallRecordingPlayer";
import { LeadInfo, sourceLabel } from "@/components/leads/LeadInfo";
import { PutOnControlButton } from "@/components/telephony/PutOnControlButton";
import type { LeadCall, LeadStatus, WebsiteLead } from "@/lib/backend-api";

const CALL_TYPE_LABELS: Record<string, string> = {
  IN: "Входящий",
  OUT: "Исходящий",
  LOCAL: "Внутренний",
  TRANSIT: "Транзит",
};

function formatCallTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${day}.${month} ${hours}:${minutes}`;
}

// Звонки с номером заявки (product ask, 2026-10-21): находить вручную,
// звонил ли кто-то с/на этот номер, внутри всей Телефонии неудобно - этот
// блок показывает их прямо в карточке заявки, вместе с расшифровкой (как
// в Телефонии - "до"/"после" обработки YandexGPT) и кнопкой PLAY. Fetched
// lazily on expand, not preloaded with the rest of the leads list.
function LeadCallsSection({ leadId }: { leadId: string }) {
  const [state, setState] = useState<"loading" | "error" | "ready">("loading");
  const [calls, setCalls] = useState<LeadCall[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/leads/${leadId}/calls`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<{ calls: LeadCall[] }>;
      })
      .then((data) => {
        if (!cancelled) {
          setCalls(data.calls);
          setState("ready");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Не удалось загрузить звонки");
          setState("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [leadId]);

  if (state === "loading") return <p className="admin-hint">Загрузка звонков…</p>;
  if (state === "error") return <p className="admin-form-error">{error}</p>;
  if (calls.length === 0) return <p className="admin-hint">Звонков с этим номером не найдено</p>;

  return (
    <div className="leads-calls-list">
      {calls.map((call) => (
        <div key={call.call_id} className="leads-call-item">
          <div className="leads-call-item-header">
            <span className="leads-call-time">{formatCallTime(call.occurred_at)}</span>
            <span className="leads-call-direction">
              {CALL_TYPE_LABELS[call.call_type] ?? call.call_type}
            </span>
            {call.operator && <span className="leads-call-operator">доб. {call.operator}</span>}
            <span className="leads-call-duration">
              {call.answered ? `${call.talk_sec} с` : "без ответа"}
            </span>
            <CallRecordingPlayer callId={call.call_id} hasRecording={call.has_recording} />
          </div>
          {call.quality_score !== null && (
            <p className="leads-call-quality">
              Оценка: {call.quality_score}/10
              {call.quality_review ? ` — ${call.quality_review}` : ""}
            </p>
          )}
          {call.transcript_text && (
            <div className="leads-call-transcript">
              <p>{call.transcript_text}</p>
              {call.transcript_text_raw && call.transcript_text_raw !== call.transcript_text && (
                <details>
                  <summary>Исходная расшифровка (до обработки YandexGPT)</summary>
                  <p>{call.transcript_text_raw}</p>
                </details>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

const STATUS_LABELS: Record<LeadStatus, string> = {
  open: "Новая",
  resolved: "Обработана",
  stale: "Просрочена",
};

const STATUS_FILTERS: { key: LeadStatus | "all"; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "open", label: "Новые" },
  { key: "resolved", label: "Обработанные" },
  { key: "stale", label: "Просроченные" },
];

// "9991234567" -> "+7 999 123-45-67" - see components/planner/LeadsBadge.tsx.
function formatPhone(phone: string): string {
  if (phone.length === 10) {
    return `+7 ${phone.slice(0, 3)} ${phone.slice(3, 6)}-${phone.slice(6, 8)}-${phone.slice(8, 10)}`;
  }
  return phone;
}

function formatCreatedAt(createdAt: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return createdAt;
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = date.getFullYear();
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${day}.${month}.${year} ${hours}:${minutes}`;
}

function LeadDetail({ lead }: { lead: WebsiteLead }) {
  return (
    <tr className="leads-detail-row">
      <td colSpan={9}>
        <div className="leads-detail-card">
          <LeadInfo lead={lead} />
          <div className="leads-calls-section">
            <span className="detail-label">Звонки с этим номером</span>
            <LeadCallsSection leadId={lead.id} />
          </div>
        </div>
      </td>
    </tr>
  );
}

export function LeadsView({
  initialLeads,
  initialOpenId,
}: {
  initialLeads: WebsiteLead[];
  /** Set via the planner's envelope-icon lead list (LeadsBadge.tsx) ->
   * /leads?id=... deep link - opens and scrolls to this one lead on
   * arrival. Filter always starts at "all" in that case, since the lead
   * could be in any status (resolved/stale leads would otherwise be
   * hidden by a non-"all" default). */
  initialOpenId?: string;
}) {
  const [filter, setFilter] = useState<LeadStatus | "all">("all");
  const [expandedId, setExpandedId] = useState<string | null>(initialOpenId ?? null);
  const openedRowRef = useRef<HTMLTableRowElement | null>(null);

  useEffect(() => {
    openedRowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    // Runs once on mount only - a later click toggling expandedId shouldn't
    // re-trigger an auto-scroll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(
    () => (filter === "all" ? initialLeads : initialLeads.filter((lead) => lead.status === filter)),
    [initialLeads, filter],
  );

  return (
    <div className="card">
      <div className="admin-toolbar">
        <h2 className="chart-title">Заявки с сайта</h2>
        <div className="admin-tabs">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className={f.key === filter ? "admin-tab admin-tab--on" : "admin-tab"}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <table className="data-table admin-data-table leads-table">
        <thead>
          <tr>
            <th>Дата</th>
            <th>Телефон</th>
            <th>Имя</th>
            <th>Источник</th>
            <th>Сайт</th>
            <th>Статус</th>
            <th>Заказ-наряд</th>
            <th>Фото</th>
            <th>Задача</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((lead) => (
            <Fragment key={lead.id}>
              <tr
                ref={lead.id === initialOpenId ? openedRowRef : undefined}
                className="admin-row"
                onClick={() => setExpandedId((prev) => (prev === lead.id ? null : lead.id))}
              >
                <td className="num">{formatCreatedAt(lead.created_at)}</td>
                <td className="num">{formatPhone(lead.phone)}</td>
                <td>{lead.name ?? "—"}</td>
                <td>{sourceLabel(lead.source)}</td>
                <td>{lead.site ?? "—"}</td>
                <td>
                  <span className={`lead-status lead-status--${lead.status}`}>{STATUS_LABELS[lead.status]}</span>
                </td>
                <td>
                  {lead.matched_work_order_number ? (
                    <Link
                      href={`/work-orders/${lead.matched_work_order_id}`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {lead.matched_work_order_number}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="num">{lead.photos?.length ?? 0}</td>
                <td>
                  <span onClick={(event) => event.stopPropagation()}>
                    <PutOnControlButton leadId={lead.id} client={lead.phone} />
                  </span>
                </td>
              </tr>
              {expandedId === lead.id && <LeadDetail lead={lead} />}
            </Fragment>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={9} className="admin-empty-row">
                Заявок нет
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
