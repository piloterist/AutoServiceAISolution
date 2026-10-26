"use client";

import { useState } from "react";

import type { BudgetYear, ReceivablesAging } from "@/lib/backend-api";

import { BudgetView } from "./BudgetView";
import { ExpensesView } from "./ExpensesView";
import { ReceivablesAgingView } from "./ReceivablesAgingView";

type TabKey = "budgets" | "expenses" | "receivables";

const TABS: { key: TabKey; label: string }[] = [
  { key: "budgets", label: "Бюджеты" },
  { key: "expenses", label: "Расходы" },
  { key: "receivables", label: "Дебиторская задолженность" },
];

export function FinanceView({
  initialBudget,
  initialReceivables,
  initialTab = "budgets",
}: {
  initialBudget: BudgetYear;
  initialReceivables: ReceivablesAging;
  initialTab?: TabKey;
}) {
  const [tab, setTab] = useState<TabKey>(initialTab);

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
      {tab === "expenses" && <ExpensesView />}
      {tab === "receivables" && <ReceivablesAgingView data={initialReceivables} />}
    </div>
  );
}
