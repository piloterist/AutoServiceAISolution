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
  customer_name: string | null;
  payer_name: string | null;
  vehicle_description: string | null;
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

export function getWorkOrders(params?: {
  dateFrom?: string;
  dateTo?: string;
  limit?: number;
  offset?: number;
}): Promise<WorkOrderListResponse> {
  return backendGet<WorkOrderListResponse>("/api/v1/work-orders", {
    date_from: params?.dateFrom ?? "",
    date_to: params?.dateTo ?? "",
    limit: params?.limit ? String(params.limit) : "",
    offset: params?.offset ? String(params.offset) : "",
  });
}

export function getMonthlySummary(params?: {
  dateFrom?: string;
  dateTo?: string;
}): Promise<MonthlySummaryResponse> {
  return backendGet<MonthlySummaryResponse>("/api/v1/work-orders/summary/monthly", {
    date_from: params?.dateFrom ?? "",
    date_to: params?.dateTo ?? "",
  });
}
