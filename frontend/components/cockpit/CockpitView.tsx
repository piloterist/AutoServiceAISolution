"use client";

import { useEffect, useRef, useState } from "react";

import { InstrumentCluster } from "@/components/cockpit/InstrumentCluster";
import { NzpToggle } from "@/components/cockpit/NzpToggle";
import type { CockpitSnapshot, WorkshopOption } from "@/lib/backend-api";

const NZP_STORAGE_KEY_PREFIX = "cockpit-nzp-";

// Both period_start/period_end are UTC instants representing Moscow-local
// calendar points (see backend cockpit_service.period_bounds) - formatting
// them without an explicit timeZone lets the *runtime's own* local zone
// decide the calendar date, which differs between the Node server
// (typically UTC in this project's containers) and the operator's browser
// (typically Europe/Moscow) and produces exactly one date's worth of
// mismatch - a real hydration error, not a cosmetic one (seen live: server
// rendered "31.08" for a UTC-midnight instant the browser rendered as
// "01.09" MSK-local). Pinning timeZone here keeps server and client
// agreeing regardless of either one's own local zone.
function formatPeriod(snapshot: CockpitSnapshot): string {
  const fmt = (iso: string) =>
    new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", timeZone: "Europe/Moscow" });
  return `${fmt(snapshot.period_start)} – ${fmt(snapshot.period_end)}`;
}

function formatUpdatedAt(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Moscow",
  });
}

/** Cockpit's top bar + instrument cluster - see components/cockpit/
 * InstrumentCluster.tsx for the SVG itself. Owns: the цех filter, the one-
 * shot startup animation stage (never replayed on filter/data changes -
 * see product spec section 10), the НЗП toggle (persisted per-user via
 * localStorage - no DB-backed per-user preference exists yet, same
 * fallback the spec explicitly allows), and race-safe refetching (a slow
 * response for a filter the operator already changed away from must never
 * overwrite newer data). */
export function CockpitView({
  initialSnapshot,
  workshops,
  userId,
}: {
  initialSnapshot: CockpitSnapshot;
  workshops: WorkshopOption[];
  userId: string;
}) {
  const [workshopId, setWorkshopId] = useState("");
  const [nzpActive, setNzpActive] = useState(false);
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One-shot reveal: the whole cluster (gauges + side panels together, as
  // one unit - see .cockpit-cluster's opacity transition in globals.css)
  // fades in from fully transparent to fully opaque exactly once on
  // mount, never replayed on filter/data changes. Replaces an earlier
  // multi-stage (dark/body/glow/ready) version that faded pieces in on
  // separate staggered timers and had to freeze the needle's rotation
  // during the early stages to stop it animating into view early - that
  // freeze/unfreeze handoff was the source of a real bug (the needle
  // visibly jumping right as the reveal finished). Rendering the needle at
  // its real angle from the very first frame and only ever fading its
  // *container's* opacity sidesteps that whole class of bug.
  const [revealed, setRevealed] = useState(false);

  const requestId = useRef(0);
  const storageKey = `${NZP_STORAGE_KEY_PREFIX}${userId}`;

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setRevealed(true);
      return;
    }
    // A short delay before flipping the class, not 0 - the browser needs
    // to paint the initial opacity:0 frame first, or there is no "before"
    // state for the CSS transition to animate from.
    const timer = setTimeout(() => setRevealed(true), 50);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    let savedNzp = false;
    try {
      savedNzp = window.localStorage.getItem(storageKey) === "1";
    } catch {
      // private browsing / blocked storage - fall back to the default (off)
    }
    if (savedNzp) {
      setNzpActive(true);
      void load(workshopId, true);
    }
    // Only on mount - a later storageKey change (a different logged-in
    // user) isn't a case this page needs to handle live.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = async (nextWorkshopId: string, nextNzp: boolean) => {
    const myRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (nextWorkshopId) params.set("workshop_id", nextWorkshopId);
      if (nextNzp) params.set("include_nzp", "true");
      const res = await fetch(`/api/cockpit?${params.toString()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      const data = (await res.json()) as CockpitSnapshot;
      if (myRequest !== requestId.current) return; // a newer request already landed
      setSnapshot(data);
    } catch (err) {
      if (myRequest !== requestId.current) return;
      setError(err instanceof Error ? err.message : "Не удалось обновить данные");
    } finally {
      if (myRequest === requestId.current) setLoading(false);
    }
  };

  const handleWorkshopChange = (value: string) => {
    setWorkshopId(value);
    void load(value, nzpActive);
  };

  const handleNzpToggle = () => {
    const next = !nzpActive;
    setNzpActive(next);
    try {
      window.localStorage.setItem(storageKey, next ? "1" : "0");
    } catch {
      // ignore - per-viewer convenience only
    }
    void load(workshopId, next);
  };

  const handleRefresh = () => {
    void load(workshopId, nzpActive);
  };

  return (
    <div className="cockpit-page">
      <div className="cockpit-topbar">
        <h1>Cockpit</h1>
        <label className="cockpit-topbar-field">
          <span className="sr-only">Цех</span>
          <select value={workshopId} onChange={(e) => handleWorkshopChange(e.target.value)}>
            <option value="">Вся компания</option>
            {workshops.map((w) => (
              <option key={w.id} value={w.id}>
                {w.department_name} — {w.workshop_type}
              </option>
            ))}
          </select>
        </label>
        <span className="cockpit-period">С начала месяца по сейчас ({formatPeriod(snapshot)})</span>
        <NzpToggle active={nzpActive} onToggle={handleNzpToggle} />
        <button
          type="button"
          className="cockpit-refresh"
          onClick={handleRefresh}
          data-loading={loading}
          aria-label="Обновить"
        >
          <svg viewBox="0 0 24 24" width={16} height={16} aria-hidden="true">
            <path
              d="M4 12a8 8 0 0 1 14-5.3L21 4v6h-6l2.6-2.6A6 6 0 0 0 6 12Z M20 12a8 8 0 0 1-14 5.3L3 20v-6h6l-2.6 2.6A6 6 0 0 0 18 12Z"
              fill="currentColor"
            />
          </svg>
          <span className="cockpit-refresh-tooltip">Данные на {formatUpdatedAt(snapshot.period_end)}</span>
        </button>
      </div>

      {error && <p className="admin-form-error">{error}</p>}

      <div className="cockpit-cluster" data-revealed={revealed}>
        <InstrumentCluster
          revenue={Number(snapshot.revenue_rub)}
          effectiveRevenue={Number(snapshot.effective_revenue_rub)}
          payments={Number(snapshot.payments_rub)}
          revenueGauge={snapshot.revenue_gauge}
          paymentsGauge={snapshot.payments_gauge}
          nzpActive={nzpActive}
          planUnusable={!snapshot.plan.usable}
          hasUnattributedRevenue={snapshot.has_unattributed_revenue && workshopId === ""}
        />
      </div>
    </div>
  );
}
