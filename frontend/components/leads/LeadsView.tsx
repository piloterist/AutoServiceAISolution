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

// raw_payload fields already surfaced as their own columns (or never worth
// showing at all - `politic` is just the consent checkbox) - showing them
// again in the detail dump would be redundant/noise. `form_name` is a
// special case, handled separately below: redundant for every source that
// already has its own SOURCE_LABELS entry, but it's the ONLY thing telling
// apart otherwise-generic "other"-source leads (see _fieldEntries).
const DETAIL_HIDDEN_KEYS = new Set(["user_phone", "user_name", "files", "folder", "politic"]);

// Human labels for every raw_payload field the site's forms are known to
// send (reverse-engineered from real submissions, 2026-10-14 - the site
// forwards its whole $_POST as-is, see Pan-Motors_web.md, so new fields can
// appear any time a form changes; an unlabeled key still gets a readable
// fallback via _humanizeKey below rather than being hidden outright).
const FIELD_LABELS: Record<string, string> = {
  page_url: "Страница на сайте",
  adv_channel: "Источник перехода",
  form_name: "Форма",
  user_connection: "Удобный способ связи",
  auto_marka: "Автомобиль",
  auto_work: "Какая работа нужна",
  quiz_damage: "Повреждённые элементы",
  quiz_damage_photo_not: "Без фото повреждений",
  quiz_gift: "Акция",
  quiz_evacuator: "Нужен эвакуатор",
  quiz_budget: "Ориентир по бюджету",
  quiz_budget_sum: "Сумма бюджета",
  quiz_messenger: "Мессенджер",
};

// Reading order for the known fields above - context (where/what form)
// first, then the actual request details, contact preference last. Any
// key not listed here (a brand new form field) is appended after these, in
// whatever order raw_payload happened to have it.
const FIELD_ORDER = [
  "page_url",
  "adv_channel",
  "form_name",
  "auto_marka",
  "auto_work",
  "quiz_damage",
  "quiz_damage_photo_not",
  "quiz_budget",
  "quiz_budget_sum",
  "quiz_gift",
  "quiz_evacuator",
  "quiz_messenger",
  "user_connection",
];

function _humanizeKey(key: string): string {
  const words = key.replace(/^quiz_/, "").split("_");
  return words.map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w)).join(" ");
}

// `quiz_damage` arrives as {"5": "Дверь задняя", "9": "Крыло заднее"} - the
// numeric keys are the body-diagram's own internal element ids, meaningless
// to staff; only the Russian part names (the values) are worth showing.
// Every other non-string value is a format this page doesn't know about
// yet - falls back to a readable dump rather than raw JSON or a crash.
function _formatValue(value: unknown): string {
  if (typeof value === "string") {
    if (value === "on") return "Да";
    return value;
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.values(value as Record<string, unknown>)
      .map((v) => String(v))
      .join(", ");
  }
  if (Array.isArray(value)) return value.map((v) => String(v)).join(", ");
  return String(value);
}

function _fieldEntries(lead: WebsiteLead): { key: string; label: string; value: string }[] {
  const entries = Object.entries(lead.raw_payload).filter(([key, value]) => {
    if (DETAIL_HIDDEN_KEYS.has(key)) return false;
    // Redundant with the Источник column for every source that already has
    // its own SOURCE_LABELS entry - only "other" leans on form_name itself
    // to say anything more specific than "Заявка с сайта".
    if (key === "form_name" && lead.source !== "other") return false;
    if (value === "" || value === null || value === undefined) return false;
    return true;
  });

  entries.sort(([a], [b]) => {
    const ia = FIELD_ORDER.indexOf(a);
    const ib = FIELD_ORDER.indexOf(b);
    if (ia === -1 && ib === -1) return 0;
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });

  return entries.map(([key, value]) => ({
    key,
    label: FIELD_LABELS[key] ?? _humanizeKey(key),
    value: _formatValue(value),
  }));
}

function LeadDetail({ lead }: { lead: WebsiteLead }) {
  const entries = _fieldEntries(lead);
  const pageUrl = typeof lead.raw_payload.page_url === "string" ? lead.raw_payload.page_url : null;

  return (
    <tr className="leads-detail-row">
      <td colSpan={7}>
        <div className="leads-detail-card">
          {lead.photos && lead.photos.length > 0 && (
            <div className="leads-photo-grid">
              {lead.photos.map((url, i) => (
                <a key={url} href={url} target="_blank" rel="noreferrer" className="leads-photo-thumb">
                  {/* eslint-disable-next-line @next/next/no-img-element -- our own
                      server-side proxy, no next/image optimization benefit here. */}
                  <img src={url} alt={`Фото ${i + 1}`} />
                </a>
              ))}
            </div>
          )}
          {entries.length > 0 ? (
            <div className="leads-detail-grid">
              {entries.map(({ key, label, value }) => (
                <div className="leads-detail-field" key={key}>
                  <span className="detail-label">{label}</span>
                  {key === "page_url" && pageUrl ? (
                    <a href={`https://pan-motors.ru${pageUrl}`} target="_blank" rel="noreferrer">
                      {value}
                    </a>
                  ) : (
                    <span>{value}</span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="admin-hint">Дополнительных данных нет</p>
          )}
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
