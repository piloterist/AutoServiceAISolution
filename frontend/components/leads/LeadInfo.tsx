"use client";

import type { WebsiteLead } from "@/lib/backend-api";

/** What of a website lead is shown to staff: photos, the form's fields and where it came from.
 * Shared by «Заявки с сайта» (the expanded row) and the CRM task window of a lead. */
export type LeadInfoData = Pick<WebsiteLead, "source" | "raw_payload" | "photos" | "site" | "request_meta">;

export const SOURCE_LABELS: Record<string, string> = {
  quiz_body: "Квиз: кузовной ремонт",
  quiz_mechanical: "Квиз: слесарный ремонт",
  consultation: "Получить консультацию",
  installment: "Рассрочка",
  other: "Заявка с сайта",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
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
  question: "Вопрос",
  evacuate_address: "Адрес эвакуации",
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

// A field box this long (product ask, 2026-10-22: "Повреждённые элементы"
// with several items selected, e.g. "Порог, Другое повреждение, Крыло
// переднее левое") wraps onto multiple lines in the grid's normal
// minmax(220px, 1fr) column - spanning two columns gives it roughly double
// the width instead, while short fields (most of them) stay as they are.
const WIDE_FIELD_VALUE_THRESHOLD = 30;

function _fieldEntries(
  lead: LeadInfoData,
): { key: string; label: string; value: string; wide: boolean }[] {
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

  return entries.map(([key, value]) => {
    const formatted = _formatValue(value);
    return {
      key,
      label: FIELD_LABELS[key] ?? _humanizeKey(key),
      value: formatted,
      wide: formatted.length > WIDE_FIELD_VALUE_THRESHOLD,
    };
  });
}

// What the intake request told us about the sender (backend leads_service.request_meta_from).
const META_LABELS: Record<string, string> = {
  site: "Сайт",
  origin: "Origin",
  referer: "Referer",
  ip: "IP отправителя",
  user_agent: "User-Agent",
};

export function LeadInfo({ lead }: { lead: LeadInfoData }) {
  const entries = _fieldEntries(lead);
  const pageUrl = typeof lead.raw_payload.page_url === "string" ? lead.raw_payload.page_url : null;

  return (
    <>
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
          {entries.map(({ key, label, value, wide }) => (
            <div className={wide ? "leads-detail-field leads-detail-field--wide" : "leads-detail-field"} key={key}>
              <span className="detail-label">{label}</span>
              {key === "page_url" && pageUrl ? (
                <a href={`https://${lead.site ?? "pan-motors.ru"}${pageUrl}`} target="_blank" rel="noreferrer">
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
      {lead.request_meta && (
        <div className="leads-detail-grid">
          {Object.entries(lead.request_meta).map(([key, value]) => (
            <div className="leads-detail-field" key={key}>
              <span className="detail-label">{META_LABELS[key] ?? key}</span>
              <span>{value}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
