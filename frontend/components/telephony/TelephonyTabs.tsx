"use client";

import { useState } from "react";

import { ConversionView } from "@/components/telephony/ConversionView";
import { TelephonyStatsView } from "@/components/telephony/TelephonyStatsView";
import type { SourceSummaryResponse } from "@/lib/backend-api";

type TabKey = "calls" | "conversion";

const TABS: { key: TabKey; label: string }[] = [
  { key: "calls", label: "Звонки" },
  { key: "conversion", label: "Конверсия" },
];

/** Телефония page tabs. Both views stay mounted (the inactive one is just
 * hidden) so switching back doesn't throw away a loaded period, an expanded
 * source or a phone-number search. */
export function TelephonyTabs({ initialSummary }: { initialSummary: SourceSummaryResponse }) {
  const [tab, setTab] = useState<TabKey>("calls");
  // "Конверсия" loads its (heavier) data only once it's first opened.
  const [conversionOpened, setConversionOpened] = useState(false);

  const selectTab = (key: TabKey) => {
    setTab(key);
    if (key === "conversion") setConversionOpened(true);
  };

  return (
    <div>
      <div className="admin-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={t.key === tab ? "admin-tab admin-tab--on" : "admin-tab"}
            onClick={() => selectTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div hidden={tab !== "calls"}>
        <TelephonyStatsView initialSummary={initialSummary} />
      </div>
      {conversionOpened && (
        <div hidden={tab !== "conversion"}>
          <ConversionView />
        </div>
      )}
    </div>
  );
}
