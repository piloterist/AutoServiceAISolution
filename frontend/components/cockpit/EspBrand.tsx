"use client";

import { useEffect, useState } from "react";

const TAGLINE_EN = "Enterprise Stability Platform";
const TAGLINE_RU = "Платформа Стабилизации Предприятия";
const TYPING_START_DELAY_MS = 1200;
const TYPE_INTERVAL_MS = 22;
// Timed so the flicker (.cockpit-esp-indicator--flicker's own 2300ms
// animation, see globals.css) finishes at roughly the same moment the
// MainGauge needle settles on its real reading (~4.7s after mount) - per
// product feedback, 2026-09-30: "они должны примерно одинаково
// завершиться - стрелка встала на место, а логотип загорелся стабильно".
const ICON_DELAY_AFTER_TYPING_MS = 400;

/** ESP branding row, top-left of Cockpit (per product feedback,
 * 2026-09-30, with a reference photo of a real ESP dash light) - fades in
 * together with the rest of the cluster (see CockpitView's shared
 * `revealed`/data-revealed), then runs its own one-shot sequence once
 * mounted: the EN/RU tagline types itself out left-to-right, and once
 * that finishes the ESP indicator (icon + "ON") flickers on like a
 * fluorescent tube. */
export function EspBrand({ revealed }: { revealed: boolean }) {
  const [typedChars, setTypedChars] = useState(0);
  const [showIcon, setShowIcon] = useState(false);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const maxLen = Math.max(TAGLINE_EN.length, TAGLINE_RU.length);
    if (reduce) {
      setTypedChars(maxLen);
      setShowIcon(true);
      return;
    }

    let typeTimer: ReturnType<typeof setInterval> | null = null;
    let iconTimer: ReturnType<typeof setTimeout> | null = null;
    const startTimer = setTimeout(() => {
      let n = 0;
      typeTimer = setInterval(() => {
        n += 1;
        setTypedChars(n);
        if (n >= maxLen) {
          if (typeTimer) clearInterval(typeTimer);
          iconTimer = setTimeout(() => setShowIcon(true), ICON_DELAY_AFTER_TYPING_MS);
        }
      }, TYPE_INTERVAL_MS);
    }, TYPING_START_DELAY_MS);

    return () => {
      clearTimeout(startTimer);
      if (typeTimer) clearInterval(typeTimer);
      if (iconTimer) clearTimeout(iconTimer);
    };
  }, []);

  return (
    <div className="cockpit-brand-row" data-revealed={revealed}>
      <span className="cockpit-esp-letters">ESP</span>
      <span className="cockpit-esp-tagline">
        <span className="cockpit-esp-tagline-en">{TAGLINE_EN.slice(0, typedChars)}</span>
        <span className="cockpit-esp-tagline-ru">{TAGLINE_RU.slice(0, typedChars)}</span>
      </span>
      {showIcon && (
        <span className="cockpit-esp-indicator cockpit-esp-indicator--flicker" role="img" aria-label="ESP включён">
          {/* eslint-disable-next-line @next/next/no-img-element -- a tiny
              static icon in a client component; next/image's extra
              machinery buys nothing here. */}
          <img src="/esp-icon.jpg" alt="" aria-hidden="true" className="cockpit-esp-indicator-icon" />
          <span className="cockpit-esp-indicator-on">ON</span>
        </span>
      )}
    </div>
  );
}
