"use client";

import { useEffect, useRef, useState } from "react";

import { InstrumentCluster } from "@/components/cockpit/InstrumentCluster";
import type { CockpitSnapshot, WorkshopOption } from "@/lib/backend-api";

const NZP_STORAGE_KEY_PREFIX = "cockpit-nzp-";
const COUNTS_POLL_INTERVAL_MS = 60_000;

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
//
// "Месяц ГГГГ" (per product feedback, 2026-09-29: replaces the old
// dd.mm-dd.mm range shown in the now-removed topbar) - period_start's own
// month, since this is always a "month to date" window.
function formatMonthYear(snapshot: CockpitSnapshot): string {
  const raw = new Date(snapshot.period_start).toLocaleDateString("ru-RU", {
    month: "long",
    year: "numeric",
    timeZone: "Europe/Moscow",
  });
  return raw.charAt(0).toUpperCase() + raw.slice(1);
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
  // Feeds the phone/envelope "lamps" in InstrumentCluster's warning grid -
  // same counts and same polling cadence as MissedCallsBadge/LeadsBadge in
  // the Planner (see product feedback, 2026-09-29: these should light up
  // red on Cockpit exactly when those badges would show a count).
  const [missedCallsCount, setMissedCallsCount] = useState(0);
  const [openLeadsCount, setOpenLeadsCount] = useState(0);
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

  useEffect(() => {
    let cancelled = false;

    const loadCounts = async () => {
      try {
        const [missedRes, leadsRes] = await Promise.all([
          fetch("/api/telephony/missed-calls", { cache: "no-store" }),
          fetch("/api/leads/open", { cache: "no-store" }),
        ]);
        if (cancelled) return;
        if (missedRes.ok) {
          const data = (await missedRes.json()) as { count: number };
          setMissedCallsCount(data.count);
        }
        if (leadsRes.ok) {
          const data = (await leadsRes.json()) as { count: number };
          setOpenLeadsCount(data.count);
        }
      } catch {
        // Best-effort - the lamps just stay at their last known state.
      }
    };

    void loadCounts();
    const timer = setInterval(() => void loadCounts(), COUNTS_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
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
      {error && <p className="admin-form-error">{error}</p>}

      <div className="cockpit-cluster" data-revealed={revealed}>
        <InstrumentCluster
          revenue={Number(snapshot.revenue_rub)}
          effectiveRevenue={Number(snapshot.effective_revenue_rub)}
          payments={Number(snapshot.payments_rub)}
          revenueGauge={snapshot.revenue_gauge}
          paymentsGauge={snapshot.payments_gauge}
          nzpActive={nzpActive}
          onNzpToggle={handleNzpToggle}
          planUnusable={!snapshot.plan.usable}
          hasUnattributedRevenue={snapshot.has_unattributed_revenue && workshopId === ""}
          workshops={workshops}
          workshopId={workshopId}
          onWorkshopChange={handleWorkshopChange}
          periodLabel={formatMonthYear(snapshot)}
          missedCallsCount={missedCallsCount}
          openLeadsCount={openLeadsCount}
          onRefresh={handleRefresh}
          refreshing={loading}
        />
      </div>
    </div>
  );
}
