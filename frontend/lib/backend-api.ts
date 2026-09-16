// Server-only helper for calling the backend's protected read API
// (GET /api/v1/work-orders, /api/v1/work-orders/summary/monthly).
//
// Deliberately NOT called from client components: BACKEND_API_TOKEN must
// never reach the browser. Only Server Components / route handlers may
// import this file. There is no per-user auth system yet (see
// ARCHITECTURE.md) - this reuses the same bearer token the 1C integration
// uses, which is why it has to stay server-side only.
import "server-only";

import { API_URL } from "@/lib/config";

export type WorkOrderListItem = {
  id: string;
  external_number: string;
  document_date: string;
  // Alpha-Auto's own document requisites (ДатаСоздания/ДатаНачала/
  // ДатаОкончания/ДатаЗакрытия) - distinct from document_date above.
  created_date: string | null;
  start_date: string | null;
  end_date: string | null;
  closed_date: string | null;
  customer_name: string | null;
  payer_name: string | null;
  vehicle_description: string | null;
  status: string | null;
  department: string | null;
  amount: string;
  // Settlement state as of the last import - 5S AUTO's own
  // ВзаиморасчетыКомпании calculation (see 1c/TestExportOrders.bsl), not
  // recomputed here. null just means the source export didn't send
  // payment data for this work order yet.
  deal_amount: string | null;
  debt_amount: string | null;
  paid_amount: string | null;
  payment_percent: string | null;
};

export type WorkOrderListResponse = {
  items: WorkOrderListItem[];
  total: number;
  limit: number;
  offset: number;
};

export type MonthlySummaryItem = {
  month: string; // "YYYY-MM"
  work_order_count: number;
  total_amount: string;
};

export type MonthlySummaryResponse = {
  items: MonthlySummaryItem[];
};

export type DepartmentSummaryItem = {
  department: string;
  work_order_count: number;
  total_amount: string;
};

export type DepartmentSummaryResponse = {
  items: DepartmentSummaryItem[];
};

export type DepartmentListResponse = {
  departments: string[];
};

export type StatusSummaryItem = {
  status: string;
  work_order_count: number;
  total_amount: string;
};

export type StatusSummaryResponse = {
  items: StatusSummaryItem[];
};

export type TrendSummaryItem = {
  period: string; // "YYYY-MM-DD" - start of the bucket (day/week/month)
  work_order_count: number;
  total_amount: string;
};

export type TrendSummaryResponse = {
  items: TrendSummaryItem[];
  granularity: "day" | "week" | "month";
};

export type PaymentTrendItem = {
  period: string; // "YYYY-MM-DD" - start of the bucket (day/week/month)
  // Net change in paid_amount observed in this bucket - there is no real
  // payment date available (see getPaymentTrendSummary below).
  total_amount: string;
};

export type PaymentTrendResponse = {
  items: PaymentTrendItem[];
  granularity: "day" | "week" | "month";
};

export type WorkOrderLaborLineItem = {
  operation_name: string | null;
  price: string | null;
  amount: string | null;
};

export type WorkOrderPartLineItem = {
  item_name: string | null;
  quantity: string | null;
  price: string | null;
  amount: string | null;
};

export type StatusHistoryItem = {
  status: string;
  first_seen_at: string;
  // null = the currently-open segment (still the work order's status as of
  // the most recent import).
  last_seen_at: string | null;
};

export type PaymentHistoryItem = {
  observed_at: string;
  deal_amount: string | null;
  debt_amount: string | null;
  paid_amount: string | null;
  payment_percent: string | null;
};

export type WorkOrderDetail = WorkOrderListItem & {
  labor: WorkOrderLaborLineItem[];
  parts: WorkOrderPartLineItem[];
  status_history: StatusHistoryItem[];
  payment_history: PaymentHistoryItem[];
};

function backendToken(): string {
  const token = process.env.BACKEND_API_TOKEN;
  if (!token) {
    throw new Error(
      "BACKEND_API_TOKEN is not set - required for the frontend's server-side backend calls (see .env.example).",
    );
  }
  return token;
}

async function backendGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, API_URL);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value) url.searchParams.set(key, value);
    }
  }

  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${backendToken()}` },
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Backend request failed: ${res.status} ${await res.text()}`);
  }

  return res.json() as Promise<T>;
}

type PeriodAndDepartmentParams = {
  dateFrom?: string;
  dateTo?: string;
  departments?: string[];
};

function departmentsParam(departments?: string[]): string {
  return departments && departments.length > 0 ? departments.join(",") : "";
}

/** The date pickers feeding `dateTo` are date-only (no time component), but
 * the backend treats `date_to` as an EXCLUSIVE upper bound
 * (`closed_date < date_to` / `document_date < date_to`) - sending a bare
 * "YYYY-MM-DD" as-is would exclude everything on that day, when picking
 * "по 13.09" obviously should include all of the 13th. Push it to the
 * start of the next day before sending, computed in UTC (matching how the
 * date-only string itself parses as UTC midnight) so this doesn't depend on
 * the server container's local timezone. */
function dateToParam(dateTo?: string): string {
  if (!dateTo) return "";
  const parsed = new Date(dateTo);
  if (Number.isNaN(parsed.getTime())) return dateTo;
  parsed.setUTCDate(parsed.getUTCDate() + 1);
  return parsed.toISOString().slice(0, 10);
}

export function getWorkOrders(
  params?: PeriodAndDepartmentParams & { limit?: number; offset?: number },
): Promise<WorkOrderListResponse> {
  return backendGet<WorkOrderListResponse>("/api/v1/work-orders", {
    date_from: params?.dateFrom ?? "",
    date_to: dateToParam(params?.dateTo),
    departments: departmentsParam(params?.departments),
    limit: params?.limit ? String(params.limit) : "",
    offset: params?.offset ? String(params.offset) : "",
  });
}

export function getMonthlySummary(
  params?: PeriodAndDepartmentParams,
): Promise<MonthlySummaryResponse> {
  return backendGet<MonthlySummaryResponse>("/api/v1/work-orders/summary/monthly", {
    date_from: params?.dateFrom ?? "",
    date_to: dateToParam(params?.dateTo),
    departments: departmentsParam(params?.departments),
  });
}

export function getDepartmentSummary(
  params?: PeriodAndDepartmentParams,
): Promise<DepartmentSummaryResponse> {
  return backendGet<DepartmentSummaryResponse>("/api/v1/work-orders/summary/by-department", {
    date_from: params?.dateFrom ?? "",
    date_to: dateToParam(params?.dateTo),
    departments: departmentsParam(params?.departments),
  });
}

export function getDepartments(): Promise<DepartmentListResponse> {
  return backendGet<DepartmentListResponse>("/api/v1/work-orders/departments");
}

export function getStatusSummary(
  params?: PeriodAndDepartmentParams,
): Promise<StatusSummaryResponse> {
  return backendGet<StatusSummaryResponse>("/api/v1/work-orders/summary/by-status", {
    date_from: params?.dateFrom ?? "",
    date_to: dateToParam(params?.dateTo),
    departments: departmentsParam(params?.departments),
  });
}

/** `date_from`/`date_to` are required here (unlike the other summary
 * endpoints) - the backend auto-detects bucket size (day/week/month) from
 * the span between them, so an open-ended range has nothing to detect from.
 * The dashboard always resolves a concrete range before calling this (see
 * app/dashboard/page.tsx and lib/period.ts). */
export function getTrendSummary(params: {
  dateFrom: string;
  dateTo: string;
  departments?: string[];
  granularity?: "day" | "week" | "month";
}): Promise<TrendSummaryResponse> {
  return backendGet<TrendSummaryResponse>("/api/v1/work-orders/summary/trend", {
    date_from: params.dateFrom,
    date_to: dateToParam(params.dateTo),
    departments: departmentsParam(params.departments),
    granularity: params.granularity ?? "",
  });
}

/** `granularity` should normally be the value the matching `getTrendSummary`
 * call resolved to (its response's `granularity` field) - passing it
 * explicitly here keeps both series bucketed identically so they overlay
 * on the same x-axis. There is no real payment date in this integration -
 * see work_order_query_service.payment_trend_summary on the backend for
 * exactly what "period" means here (when a payment change was *observed*,
 * not when 1C recorded it). */
export function getPaymentTrendSummary(params: {
  dateFrom: string;
  dateTo: string;
  departments?: string[];
  granularity?: "day" | "week" | "month";
}): Promise<PaymentTrendResponse> {
  return backendGet<PaymentTrendResponse>("/api/v1/work-orders/summary/payment-trend", {
    date_from: params.dateFrom,
    date_to: dateToParam(params.dateTo),
    departments: departmentsParam(params.departments),
    granularity: params.granularity ?? "",
  });
}

export function getWorkOrder(id: string): Promise<WorkOrderDetail> {
  return backendGet<WorkOrderDetail>(`/api/v1/work-orders/${id}`);
}
