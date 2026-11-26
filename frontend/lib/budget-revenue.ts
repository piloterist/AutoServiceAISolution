// Какие заказ-наряды Бюджета открывает клик по значению (Финансы -> Бюджеты -> лист ЗН):
// insurance / main - «Выручка факт страховые / основные», all - «Выручка общая»,
// unpaid - «Без оплат» (заказ-наряды выручки, оплаченные не полностью).
export type BudgetRevenueKind =
  | "insurance"
  | "main"
  | "all"
  | "unpaid"
  | "overdue"
  | "not_due";

export const BUDGET_REVENUE_TITLES: Record<BudgetRevenueKind, string> = {
  insurance: "Выручка факт страховые",
  main: "Выручка факт основные",
  all: "Выручка общая",
  unpaid: "Без оплат",
  overdue: "Просрочено",
  not_due: "Ожидание",
};

export function isBudgetRevenueKind(value: unknown): value is BudgetRevenueKind {
  return typeof value === "string" && value in BUDGET_REVENUE_TITLES;
}
