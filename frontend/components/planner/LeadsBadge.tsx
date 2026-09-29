"use client";

import { useEffect, useState } from "react";

import { AdminModal } from "@/components/settings/AdminModal";
import type { WebsiteLead } from "@/lib/backend-api";
import { leadsApi } from "@/lib/leads-client";

const POLL_INTERVAL_MS = 60_000;

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

// "9991234567" -> "+7 999 123-45-67" - same convention as
// MissedCallsBadge.tsx's own formatClient (leads reuse the same
// last-10-digits phone normalization - see backend services/leads_service.py).
function formatPhone(phone: string): string {
  if (phone.length === 10) {
    return `+7 ${phone.slice(0, 3)} ${phone.slice(3, 6)}-${phone.slice(6, 8)}-${phone.slice(8, 10)}`;
  }
  return phone;
}

// "2026-09-29T10:00:00+00:00" -> "29.09 13:00" (browser-local, matches this
// app's DD.MM date convention elsewhere).
function formatCreatedAt(createdAt: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return createdAt;
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${day}.${month} ${hours}:${minutes}`;
}

/** Envelope-icon badge next to MissedCallsBadge in the Planner's top-right
 * corner - a mobile-app-style red count bubble for website leads that still
 * need a callback (see backend services/leads_service.get_open_leads for
 * the exact "still open" rules: not yet reached by a real, answered
 * OUTBOUND call, and not yet past the configurable stale_after_days
 * window). Company-wide, same scope as MissedCallsBadge. Nothing here can
 * be dismissed by hand - a lead only leaves this list via a real callback
 * or by aging out (per product spec), so the count always reflects
 * reality. The full history (open, resolved and stale) lives on the
 * separate /leads page. */
export function LeadsBadge() {
  const [leads, setLeads] = useState<WebsiteLead[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        const data = await leadsApi.open();
        if (cancelled) return;
        setLeads(data.leads);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Не удалось загрузить заявки");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <>
      <button
        type="button"
        className="leads-badge-btn"
        onClick={() => setOpen(true)}
        aria-label={leads.length > 0 ? `Новые заявки: ${leads.length}` : "Новых заявок нет"}
      >
        <svg viewBox="0 0 24 24" width={40} height={40} aria-hidden="true">
          <path
            d="M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm1 2.4V17h14V7.4l-6.4 4.8a1 1 0 0 1-1.2 0L5 7.4Zm.9-.4L12 11l6.1-4H5.9Z"
            fill="currentColor"
          />
        </svg>
        {leads.length > 0 && <span className="leads-badge-count">{leads.length}</span>}
      </button>

      <AdminModal open={open} title="Новые заявки с сайта" onClose={() => setOpen(false)} closeOnBackdropClick>
        {loading && leads.length === 0 && <p className="admin-hint">Загрузка…</p>}
        {error && <p className="admin-form-error">{error}</p>}
        {!loading && !error && leads.length === 0 && <p className="admin-hint">Новых заявок нет</p>}
        {leads.length > 0 && (
          <ul className="leads-badge-list">
            {leads.map((lead) => (
              <li key={lead.id} className="leads-badge-row">
                <span className="leads-badge-row-client">
                  {formatPhone(lead.phone)}
                  {lead.name && <span className="leads-badge-row-name"> — {lead.name}</span>}
                </span>
                <span className="leads-badge-row-label">{sourceLabel(lead.source)}</span>
                <span className="leads-badge-row-meta">{formatCreatedAt(lead.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </AdminModal>
    </>
  );
}
