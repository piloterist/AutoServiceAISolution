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

export type WorkOrderDetail = WorkOrderListItem & {
  labor: WorkOrderLaborLineItem[];
  parts: WorkOrderPartLineItem[];
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

export function getWorkOrders(
  params?: PeriodAndDepartmentParams & { limit?: number; offset?: number },
): Promise<WorkOrderListResponse> {
  return backendGet<WorkOrderListResponse>("/api/v1/work-orders", {
    date_from: params?.dateFrom ?? "",
    date_to: params?.dateTo ?? "",
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
    date_to: params?.dateTo ?? "",
    departments: departmentsParam(params?.departments),
  });
}

export function getDepartmentSummary(
  params?: PeriodAndDepartmentParams,
): Promise<DepartmentSummaryResponse> {
  return backendGet<DepartmentSummaryResponse>("/api/v1/work-orders/summary/by-department", {
    date_from: params?.dateFrom ?? "",
    date_to: params?.dateTo ?? "",
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
    date_to: params?.dateTo ?? "",
    departments: departmentsParam(params?.departments),
  });
}

export function getWorkOrder(id: string): Promise<WorkOrderDetail> {
  return backendGet<WorkOrderDetail>(`/api/v1/work-orders/${id}`);
}
