"use client";

import { useState } from "react";

import type { BudgetYear, ReceivablesAging } from "@/lib/backend-api";

import { BudgetView } from "./BudgetView";
import { ReceivablesAgingView } from "./ReceivablesAgingView";

type TabKey = "budgets" | "receivables";

const TABS: { key: TabKey; label: string }[] = [
  { key: "budgets", label: "Бюджеты" },
  { key: "receivables", label: "Дебиторская задолженность" },
];

export function FinanceView({
  initialBudget,
  initialReceivables,
}: {
  initialBudget: BudgetYear;
  initialReceivables: ReceivablesAging;
}) {
  const [tab, setTab] = useState<TabKey>("budgets");

  return (
    <div>
      <div className="admin-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={t.key === tab ? "admin-tab admin-tab--on" : "admin-tab"}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "budgets" && <BudgetView initialData={initialBudget} />}
      {tab === "receivables" && <ReceivablesAgingView data={initialReceivables} />}
    </div>
  );
}
