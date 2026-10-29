import type { ConversionGroup } from "@/lib/backend-api";

// Which numbers of Телефония -> "Конверсия" to show. Every donut and every
// figure beside it on Аналитика links to one of these, so a click shows
// exactly the numbers that went into that figure (the segment of each phone
// comes from the backend's conversion_service.classify_phones - the same
// code that produces the figures).
export type Cohort =
  | "all"
  | "target"
  | "new_all"
  | "new"
  | "new_converted"
  | "new_unanswered"
  | "existing_all"
  | "existing_counted"
  | "existing_converted"
  | "existing_unanswered";

export const COHORTS: { key: Cohort; label: string }[] = [
  { key: "all", label: "Все входящие звонки" },
  { key: "target", label: "Целевые звонки (тема определена или разговор дольше 20 секунд)" },
  { key: "new_all", label: "Новые клиенты — все номера" },
  { key: "new", label: "Новые клиенты — разговор по теме" },
  { key: "new_converted", label: "Новые клиенты — заявки + заказ-наряды" },
  { key: "new_unanswered", label: "Новые клиенты — остались без ответа" },
  { key: "existing_all", label: "Существующие клиенты — все номера" },
  { key: "existing_counted", label: "Существующие клиенты — разговор по теме" },
  { key: "existing_converted", label: "Существующие клиенты — заявки + заказ-наряды" },
  { key: "existing_unanswered", label: "Существующие клиенты — остались без ответа" },
];

const COHORT_KEYS = new Set<string>(COHORTS.map((c) => c.key));

export function parseCohort(value: string | undefined | null): Cohort {
  return value && COHORT_KEYS.has(value) ? (value as Cohort) : "all";
}

export function groupInCohort(group: ConversionGroup, cohort: Cohort): boolean {
  switch (cohort) {
    case "all":
      return true;
    case "target":
      return group.segment === "new" || group.segment === "existing_counted";
    case "new_all":
      return group.client_class === "new";
    case "new":
      return group.segment === "new";
    case "new_converted":
      return group.segment === "new" && group.conversion_row;
    case "new_unanswered":
      return group.client_class === "new" && group.phone_unanswered;
    case "existing_all":
      return group.client_class === "existing_counted";
    case "existing_counted":
      return group.segment === "existing_counted";
    case "existing_converted":
      return group.segment === "existing_counted" && group.conversion_row;
    case "existing_unanswered":
      return group.client_class === "existing_counted" && group.phone_unanswered;
  }
}

/** Link to the "Конверсия" tab for a period and a cohort. */
export function conversionHref(
  from: string,
  to: string,
  cohort: Cohort,
  departments: string[] = [],
  includeRequests = false,
): string {
  const query = new URLSearchParams({ tab: "conversion", from, to, cohort });
  if (includeRequests) query.set("requests", "1");
  if (departments.length > 0) query.set("departments", departments.join(","));
  return `/telephony?${query.toString()}`;
}

/** Which work orders a donut figure links to: those of new / existing clients, or (the
 * order-source donut) all / after a call / without a call. */
export type ConversionWorkOrdersKind =
  | "new"
  | "existing"
  | "new_requests"
  | "existing_requests"
  | "total"
  | "after_call"
  | "without_call";

/** Link to the work-order list narrowed to the work orders counted in a
 * donut's "Заказ-нарядов" figure. */
export function conversionWorkOrdersHref(
  kind: ConversionWorkOrdersKind,
  from: string,
  to: string,
  departments: string[] = [],
  includeRequests = false,
): string {
  const query = new URLSearchParams({ conv: kind, conv_from: from, conv_to: to });
  if (includeRequests) query.set("conv_requests", "1");
  if (departments.length > 0) query.set("conv_departments", departments.join(","));
  return `/work-orders?${query.toString()}`;
}
