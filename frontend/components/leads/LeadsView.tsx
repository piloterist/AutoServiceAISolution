"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import type { LeadStatus, WebsiteLead } from "@/lib/backend-api";

const SOURCE_LABELS: Record<string, string> = {
  quiz_body: "Квиз: кузовной ремонт",
  quiz_mechanical: "Квиз: слесарный ремонт",
  consultation: "Получить консультацию",
  installment: "Рассрочка",
  other: "Заявка с сайта",
};

function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
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

// raw_payload fields already surfaced as their own columns/photo links -
// showing them again in the detail dump would be redundant.
const DETAIL_HIDDEN_KEYS = new Set(["user_phone", "user_name", "files", "folder"]);

function LeadDetail({ lead }: { lead: WebsiteLead }) {
  const entries = Object.entries(lead.raw_payload).filter(([key]) => !DETAIL_HIDDEN_KEYS.has(key));

  return (
    <tr className="leads-detail-row">
      <td colSpan={7}>
        {lead.photos && lead.photos.length > 0 && (
          <div className="leads-photo-links" style={{ marginBottom: "0.6rem" }}>
            {lead.photos.map((url) => (
              <a key={url} href={url} target="_blank" rel="noreferrer" className="admin-btn">
                Фото {lead.photos!.indexOf(url) + 1}
              </a>
            ))}
          </div>
        )}
        {entries.length > 0 ? (
          <dl className="leads-detail-grid">
            {entries.map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="admin-hint">Дополнительных данных нет</p>
        )}
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

      <table className="data-table admin-data-table">
        <thead>
          <tr>
            <th>Дата</th>
            <th>Телефон</th>
            <th>Имя</th>
            <th>Источник</th>
            <th>Статус</th>
            <th>Заказ-наряд</th>
            <th>Фото</th>
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
              </tr>
              {expandedId === lead.id && <LeadDetail lead={lead} />}
            </Fragment>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={7} className="admin-empty-row">
                Заявок нет
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
