"use client";

import { useEffect, useState } from "react";

import { AdminModal } from "@/components/settings/AdminModal";
import type { OpenMissedCall } from "@/lib/backend-api";

const POLL_INTERVAL_MS = 60_000;

function directionLabel(call: OpenMissedCall): string {
  return call.direction === "in" ? "Звонил, не дозвонился" : "Перезвонили, не дозвонились";
}

/** What was actually dialed to reach us (for an inbound miss: the
 * line/DID number, plus which internal extension(s) it rang on) or, for
 * our own failed callback, which of our extensions placed it - per product
 * feedback: "на какой телефон и добавочный звонили" wasn't visible before,
 * only the source label. Null when there's nothing to show (e.g. the call
 * never got routed to any extension at all). */
function calledToLabel(call: OpenMissedCall): string | null {
  if (call.direction === "in") {
    const parts: string[] = [];
    if (call.line) {
      parts.push(
        call.source_label && call.source_label !== call.line
          ? `${call.line} (${call.source_label})`
          : call.line,
      );
    }
    if (call.rang_not_answered.length > 0) parts.push(`доб. ${call.rang_not_answered.join(", ")}`);
    return parts.length > 0 ? `Звонили на: ${parts.join(", ")}` : null;
  }
  return call.operator ? `Перезвонили с доб. ${call.operator}` : null;
}

// "9991234567" -> "+7 999 123-45-67" - same formatting/precedent as
// TelephonyStatsView.tsx's own formatClient (Zeon's numbers are always
// normalized to exactly 10 digits - see backend services/zeon_client.py).
function formatClient(client: string): string {
  if (client.length === 10) {
    return `+7 ${client.slice(0, 3)} ${client.slice(3, 6)}-${client.slice(6, 8)}-${client.slice(8, 10)}`;
  }
  return client;
}

/** "2026-09-28 14:05:21" (Moscow-local, see backend OpenMissedCallOut.time)
 * -> "28.09 14:05" - matches this app's DD.MM date convention elsewhere. */
function formatCallTime(time: string): string {
  const [datePart, timePart] = time.split(" ");
  const [, month, day] = datePart.split("-");
  return `${day}.${month} ${timePart?.slice(0, 5) ?? ""}`;
}

type GroupedMissedCall = {
  client: string;
  count: number;
  last: OpenMissedCall;
};

/** One row per number, not per call - a number that missed 3 times reads
 * as one line "+7 999 ... (3)" with the most recent attempt's own
 * time/direction/source, per product feedback, instead of 3 near-identical
 * rows. `calls` already arrives newest-first from the backend, so the
 * first call encountered for a given client while grouping is its most
 * recent one - no extra sort needed within a group. */
function groupByClient(calls: OpenMissedCall[]): GroupedMissedCall[] {
  const order: string[] = [];
  const byClient = new Map<string, OpenMissedCall[]>();
  for (const call of calls) {
    const bucket = byClient.get(call.client);
    if (bucket) {
      bucket.push(call);
    } else {
      byClient.set(call.client, [call]);
      order.push(call.client);
    }
  }
  return order.map((client) => {
    const bucket = byClient.get(client)!;
    return { client, count: bucket.length, last: bucket[0] };
  });
}

/** Phone-icon badge in the Planner's top-right corner - a mobile-app-style
 * red count bubble for missed calls that still need a callback (see
 * backend telephony_stats_service.get_open_missed_calls for the exact
 * "still open" rules: last 2 Moscow-calendar days, >=5s real talk to count
 * as reached, one real contact clears every earlier miss from that
 * number). Company-wide - phone lines aren't tied to a цех in this data
 * model, so this isn't scoped to whichever цех the Planner board is
 * currently showing. Nothing here can be dismissed/deleted by hand - a row
 * only leaves this list by a real callback or by aging out of the
 * 2-day window (per product spec), so the count always reflects reality,
 * never a manually-cleared notification. */
export function MissedCallsBadge() {
  const [calls, setCalls] = useState<OpenMissedCall[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        const res = await fetch("/api/telephony/missed-calls", { cache: "no-store" });
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        const data = (await res.json()) as { count: number; calls: OpenMissedCall[] };
        if (cancelled) return;
        setCalls(data.calls);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Не удалось загрузить пропущенные");
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
        className="missed-calls-badge-btn"
        onClick={() => setOpen(true)}
        aria-label={calls.length > 0 ? `Пропущенные звонки: ${calls.length}` : "Пропущенных звонков нет"}
      >
        <svg viewBox="0 0 24 24" width={40} height={40} aria-hidden="true">
          <path
            d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1C10.9 21 3 13.1 3 3.6 3 3 3.4 2.6 4 2.6h3.4c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8Z"
            fill="currentColor"
          />
        </svg>
        {calls.length > 0 && <span className="missed-calls-badge-count">{calls.length}</span>}
      </button>

      <AdminModal
        open={open}
        title="Пропущенные (сегодня и вчера)"
        onClose={() => setOpen(false)}
        closeOnBackdropClick
      >
        {loading && calls.length === 0 && <p className="admin-hint">Загрузка…</p>}
        {error && <p className="admin-form-error">{error}</p>}
        {!loading && !error && calls.length === 0 && <p className="admin-hint">Пропущенных нет</p>}
        {calls.length > 0 && (
          <ul className="missed-calls-list">
            {groupByClient(calls).map((group) => {
              const calledTo = calledToLabel(group.last);
              return (
                <li key={group.client} className="missed-calls-row">
                  <span className="missed-calls-row-client">
                    {formatClient(group.client)}
                    {group.count > 1 && <span className="missed-calls-row-count"> ({group.count})</span>}
                  </span>
                  {calledTo && <span className="missed-calls-row-called-to">{calledTo}</span>}
                  <span className="missed-calls-row-label">{directionLabel(group.last)}</span>
                  <span className="missed-calls-row-meta">{formatCallTime(group.last.time)}</span>
                </li>
              );
            })}
          </ul>
        )}
      </AdminModal>
    </>
  );
}
