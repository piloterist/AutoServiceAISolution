"use client";

import { useEffect, useState } from "react";

import { API_URL } from "@/lib/config";

type HealthState = "checking" | "ok" | "down";

export function HealthIndicator() {
  const [state, setState] = useState<HealthState>("checking");

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
        if (!cancelled) {
          setState(res.ok ? "ok" : "down");
        }
      } catch {
        if (!cancelled) setState("down");
      }
    }

    check();
    const interval = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const label =
    state === "checking" ? "Checking backend..." : state === "ok" ? "Backend: OK" : "Backend: unreachable";

  return (
    <div className={`health-indicator health-${state}`}>
      <span className="health-dot" aria-hidden="true" />
      {label}
    </div>
  );
}
