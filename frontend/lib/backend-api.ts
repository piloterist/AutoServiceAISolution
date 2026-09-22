// Server-only helper for calling the backend's protected API.
//
// Deliberately NOT called from client components: BACKEND_API_TOKEN must
// never reach the browser. Only Server Components / route handlers may
// import this file - the browser talks to same-origin /api/* proxy routes
// instead (see app/api/admin/*, app/api/planner/*), which hold this token
// server-side and forward the caller's own session identity (for Planner
// writes' audit logging) via X-Actor-* headers instead.
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
  // ЗаказНаряд.ВидРемонта - accident repair, scheduled maintenance,
  // warranty, etc; exact values are per-client 1C data.
  repair_type: string | null;
  // ЗаказНаряд.Организация - which of the client's own legal entities the
  // work order was raised under.
  organization: string | null;
  // Computed at import time from the car's VIN + org/payer rules (see
  // backend services/internal_order_rules.py) - "Специфика PanMotors".
  // Shown and filterable on the list; AppSettings.exclude_internal_orders
  // can additionally exclude these from dashboard aggregates entirely.
  is_internal: boolean;
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

export type RevenuePaidSummaryResponse = {
  // Of the work orders making up the revenue figure for this period, how
  // much of their amount is actually paid - the small badge on the
  // "Выручка за период" tile.
  total_amount: string;
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

export type RepairTypeListResponse = {
  repair_types: string[];
};

export type AppSettings = {
  // ЗаказНаряд.ВидРемонта value that identifies an insurance-company
  // repair - one of the values from getRepairTypes(), or null if not
  // configured yet. Older, separate feature - not related to is_internal
  // below (see "Специфика PanMotors" fields).
  insurance_repair_type: string | null;
  exclude_internal_insurance: boolean;
  // "Специфика PanMotors" group - gates WorkOrderListItem.is_internal on
  // the dashboard only (see backend services/internal_order_rules.py).
  exclude_internal_orders: boolean;
  // Not wired to any filtering logic yet - deliberately inert (see
  // SettingsForm.tsx).
  hide_internal_orders: boolean;
  // Runtime on/off switch for the Planner's "Получить ЗН" live 5Systems
  // plate lookup - see backend/app/models/app_settings.py for how this
  // differs from ENABLE_FIVESYSTEMS_LOOKUP (the env var).
  fivesystems_api_enabled: boolean;
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
  // Sum of real payment amounts whose actual 1C payment date falls in this
  // bucket (see getPaymentTrendSummary below).
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
  // A real status change, sourced from 1C's own
  // РегистрСведений.пп_ВерсииОбъектов version log (see
  // models/work_order_status_history.py on the backend) - changed_at is
  // 1C's own ДатаВерсии, never an import/observation timestamp.
  status: string;
  changed_at: string;
  author: string | null;
  // Technical/traceability fields - not shown in the UI.
  version_number: number;
  status_uuid: string | null;
};

export type PaymentHistoryItem = {
  observed_at: string;
  deal_amount: string | null;
  debt_amount: string | null;
  paid_amount: string | null;
  payment_percent: string | null;
};

export type PaymentEventItem = {
  // The real 1C payment date - not when we happened to import/observe it.
  paid_at: string;
  amount: string;
  source_document_type: string | null;
  source_document_number: string | null;
};

export type WorkOrderDetail = WorkOrderListItem & {
  // ЗаказНаряд.Автомобиль.VIN - shown on the detail card only, never on
  // the list or dashboard (see backend services/internal_order_rules.py).
  vin: string | null;
  labor: WorkOrderLaborLineItem[];
  parts: WorkOrderPartLineItem[];
  status_history: StatusHistoryItem[];
  payment_history: PaymentHistoryItem[];
  payment_events: PaymentEventItem[];
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

async function backendPut<T>(
  path: string,
  body: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const res = await fetch(new URL(path, API_URL), {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${backendToken()}`,
      "Content-Type": "application/json",
      ...extraHeaders,
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Backend request failed: ${res.status} ${await res.text()}`);
  }

  return res.json() as Promise<T>;
}

async function backendPost<T>(
  path: string,
  body: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const res = await fetch(new URL(path, API_URL), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${backendToken()}`,
      "Content-Type": "application/json",
      ...extraHeaders,
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Backend request failed: ${res.status} ${await res.text()}`);
  }

  return res.json() as Promise<T>;
}

async function backendDelete(path: string, extraHeaders?: Record<string, string>): Promise<void> {
  const res = await fetch(new URL(path, API_URL), {
    method: "DELETE",
    headers: { Authorization: `Bearer ${backendToken()}`, ...extraHeaders },
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Backend request failed: ${res.status} ${await res.text()}`);
  }
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
  params?: PeriodAndDepartmentParams & {
    /** Restricts to work orders with a real payment (paid_at) in this
     * range - what the dashboard's "Оплаты за период" tile links to (see
     * work_order_query_service.list_work_orders on the backend). Distinct
     * from dateFrom/dateTo, which filter by document_date. */
    paidFrom?: string;
    paidTo?: string;
    limit?: number;
    offset?: number;
  },
): Promise<WorkOrderListResponse> {
  return backendGet<WorkOrderListResponse>("/api/v1/work-orders", {
    date_from: params?.dateFrom ?? "",
    date_to: dateToParam(params?.dateTo),
    departments: departmentsParam(params?.departments),
    paid_from: params?.paidFrom ?? "",
    paid_to: dateToParam(params?.paidTo),
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

export function getRevenuePaidSummary(
  params?: PeriodAndDepartmentParams,
): Promise<RevenuePaidSummaryResponse> {
  return backendGet<RevenuePaidSummaryResponse>("/api/v1/work-orders/summary/revenue-paid", {
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

/** Same shape as getDepartmentSummary, but grouped/filtered by the real
 * payment date (paid_at on work_order_payment_events) instead of
 * closed_date - the "Оплаты по подразделениям" sidebar card. */
export function getPaymentDepartmentSummary(
  params?: PeriodAndDepartmentParams,
): Promise<DepartmentSummaryResponse> {
  return backendGet<DepartmentSummaryResponse>(
    "/api/v1/work-orders/summary/payment-by-department",
    {
      date_from: params?.dateFrom ?? "",
      date_to: dateToParam(params?.dateTo),
      departments: departmentsParam(params?.departments),
    },
  );
}

export function getDepartments(): Promise<DepartmentListResponse> {
  return backendGet<DepartmentListResponse>("/api/v1/work-orders/departments");
}

export function getRepairTypes(): Promise<RepairTypeListResponse> {
  return backendGet<RepairTypeListResponse>("/api/v1/work-orders/repair-types");
}

export function getAppSettings(): Promise<AppSettings> {
  return backendGet<AppSettings>("/api/v1/settings");
}

export function updateAppSettings(settings: AppSettings): Promise<AppSettings> {
  return backendPut<AppSettings>("/api/v1/settings", settings);
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
 * on the same x-axis. "period" here is the real 1C payment date (paid_at on
 * work_order_payment_events), not an import/observation timestamp - see
 * work_order_query_service.payment_trend_summary on the backend. */
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

// ============================================================================
// Per-user auth + Settings admin tables (Пользователи/Подразделения/Цеха/
// Статусы слесарки/аудит-лог). "Admin"/"Org" prefixes below avoid colliding
// with getDepartments()/DepartmentListResponse above, which is a completely
// different thing (distinct WorkOrder.department free-text values from 1C,
// used for filter dropdowns) - not the structural Department/Workshop
// entities this product now has for RBAC and the Planner.
// ============================================================================

export type AuthenticatedUser = {
  id: string;
  full_name: string;
  login: string;
  role: string;
  department_id: string | null;
  department_name: string | null;
  workshop_id: string | null;
};

/** Throws with a message the login form can show as-is on 401; any other
 * failure (network, 5xx) throws the generic backendPost error. */
export function loginUser(login: string, password: string): Promise<AuthenticatedUser> {
  return backendPost<AuthenticatedUser>("/api/v1/auth/login", { login, password });
}

export type OrgDepartment = {
  id: string;
  name: string;
};

export function getOrgDepartments(): Promise<OrgDepartment[]> {
  return backendGet<OrgDepartment[]>("/api/v1/settings/departments");
}

export function createOrgDepartment(name: string): Promise<OrgDepartment> {
  return backendPost<OrgDepartment>("/api/v1/settings/departments", { name });
}

export function updateOrgDepartment(id: string, name: string): Promise<OrgDepartment> {
  return backendPut<OrgDepartment>(`/api/v1/settings/departments/${id}`, { name });
}

export function deleteOrgDepartment(id: string): Promise<void> {
  return backendDelete(`/api/v1/settings/departments/${id}`);
}

export type Workshop = {
  id: string;
  department_id: string;
  department_name: string;
  workshop_type: string;
  area: string | null;
  posts_count: number;
  is_default: boolean;
  start_time: string; // "HH:MM:SS"
  end_time: string;
  working_days: number[]; // 0=Monday..6=Sunday
};

export type WorkshopWrite = {
  department_id: string;
  workshop_type: string;
  area?: string | null;
  posts_count: number;
  is_default: boolean;
  start_time: string;
  end_time: string;
  working_days: number[];
};

export function getWorkshops(): Promise<Workshop[]> {
  return backendGet<Workshop[]>("/api/v1/settings/workshops");
}

export function createWorkshop(payload: WorkshopWrite): Promise<Workshop> {
  return backendPost<Workshop>("/api/v1/settings/workshops", payload);
}

export function updateWorkshop(id: string, payload: WorkshopWrite): Promise<Workshop> {
  return backendPut<Workshop>(`/api/v1/settings/workshops/${id}`, payload);
}

export function deleteWorkshop(id: string): Promise<void> {
  return backendDelete(`/api/v1/settings/workshops/${id}`);
}

export type OrgUser = {
  id: string;
  full_name: string;
  login: string;
  role: string;
  department_id: string | null;
  department_name: string | null;
  workshop_id: string | null;
};

export type OrgUserCreate = {
  full_name: string;
  login: string;
  password: string;
  role: string;
  department_id: string | null;
  workshop_id: string | null;
};

export type OrgUserUpdate = {
  full_name: string;
  login: string;
  password?: string | null; // empty/omitted keeps the existing password
  role: string;
  department_id: string | null;
  workshop_id: string | null;
};

export function getOrgUsers(): Promise<OrgUser[]> {
  return backendGet<OrgUser[]>("/api/v1/settings/users");
}

export function createOrgUser(payload: OrgUserCreate): Promise<OrgUser> {
  return backendPost<OrgUser>("/api/v1/settings/users", payload);
}

export function updateOrgUser(id: string, payload: OrgUserUpdate): Promise<OrgUser> {
  return backendPut<OrgUser>(`/api/v1/settings/users/${id}`, payload);
}

export function deleteOrgUser(id: string): Promise<void> {
  return backendDelete(`/api/v1/settings/users/${id}`);
}

export type SlesarkaStatus = {
  id: string;
  name: string;
  color: string; // "#rrggbb"
};

export function getSlesarkaStatuses(): Promise<SlesarkaStatus[]> {
  return backendGet<SlesarkaStatus[]>("/api/v1/settings/slesarka-statuses");
}

export function createSlesarkaStatus(name: string, color: string): Promise<SlesarkaStatus> {
  return backendPost<SlesarkaStatus>("/api/v1/settings/slesarka-statuses", { name, color });
}

export function updateSlesarkaStatus(id: string, name: string, color: string): Promise<SlesarkaStatus> {
  return backendPut<SlesarkaStatus>(`/api/v1/settings/slesarka-statuses/${id}`, { name, color });
}

export function deleteSlesarkaStatus(id: string): Promise<void> {
  return backendDelete(`/api/v1/settings/slesarka-statuses/${id}`);
}

export type AuditLogEntry = {
  id: string;
  entity_type: string;
  entity_id: string;
  action: string;
  changes: Record<string, { old: unknown; new: unknown }>;
  actor_name: string;
  created_at: string;
};

export function getAuditLog(): Promise<AuditLogEntry[]> {
  return backendGet<AuditLogEntry[]>("/api/v1/settings/audit-log");
}

// ============================================================================
// Planner (Слесарный/Кузовной цех) - see backend app/services/planner_service.py.
// Writes carry the acting user's identity for audit logging (see
// schedule_audit_log) via X-Actor-* headers - the header VALUE must be
// percent-encoded (encodeURIComponent) since HTTP header values are
// ASCII/Latin-1-only and actor names are routinely Cyrillic; the backend's
// actor() dependency unquotes it back.
// ============================================================================

export function actorHeaders(actor: { id: string; fullName: string }): Record<string, string> {
  return {
    "X-Actor-User-Id": actor.id,
    "X-Actor-Name": encodeURIComponent(actor.fullName),
  };
}

export type PlannerWorkOrder = {
  id: string;
  external_number: string;
  vehicle_description: string | null;
  vin: string | null;
  customer_name: string | null;
  amount: string;
};

export function searchPlannerWorkOrders(q: string): Promise<PlannerWorkOrder[]> {
  return backendGet<PlannerWorkOrder[]>("/api/v1/planner/work-orders/search", { q });
}

/** Live 5Systems lookup for a work order not yet reached by the (now
 * once-daily) 1C export - see backend/app/services/fivesystems_client.py's
 * module docstring for the full why/how. Throws on any backend error,
 * including the expected "not found" (404) and "feature disabled" (503)
 * cases - the caller distinguishes them by the thrown message/status, same
 * pattern as every other backend-api.ts function here. */
export function lookupPlannerWorkOrderByPlate(plate: string): Promise<PlannerWorkOrder> {
  return backendGet<PlannerWorkOrder>("/api/v1/planner/work-orders/lookup-by-plate", { plate });
}

export type WorkshopJob = {
  id: string;
  workshop_id: string;
  work_order_id: string | null;
  work_order_number: string | null;
  work_order_status: string | null; // ЗН.Статус (1C) - "Факт" totals use "Закрыт"
  amount: string | null;
  car_description: string | null;
  vin: string | null;
  plate: string | null;
  client_name: string | null;
  work_description: string | null;
  job_date: string; // "YYYY-MM-DD"
  post_number: number;
  start_time: string; // "HH:MM:SS"
  end_time: string;
  norm_hours: string | null;
  status_id: string | null;
  status_name: string | null;
  status_color: string | null;
};

export type WorkshopJobWrite = {
  work_order_id: string | null;
  car_description: string | null;
  vin: string | null;
  plate: string | null;
  client_name: string | null;
  work_description: string | null;
  job_date: string;
  post_number: number;
  start_time: string;
  end_time: string;
  norm_hours: string | null;
  status_id: string | null;
};

export function getWorkshopJobs(workshopId: string, dateFrom: string, dateTo: string): Promise<WorkshopJob[]> {
  return backendGet<WorkshopJob[]>(`/api/v1/planner/workshops/${workshopId}/jobs`, {
    date_from: dateFrom,
    date_to: dateTo,
  });
}

export function createWorkshopJob(
  workshopId: string,
  payload: WorkshopJobWrite,
  actor: { id: string; fullName: string },
): Promise<WorkshopJob> {
  return backendPost<WorkshopJob>(`/api/v1/planner/workshops/${workshopId}/jobs`, payload, actorHeaders(actor));
}

export function updateWorkshopJob(
  id: string,
  payload: WorkshopJobWrite,
  actor: { id: string; fullName: string },
): Promise<WorkshopJob> {
  return backendPut<WorkshopJob>(`/api/v1/planner/jobs/${id}`, payload, actorHeaders(actor));
}

export function deleteWorkshopJob(id: string, actor: { id: string; fullName: string }): Promise<void> {
  return backendDelete(`/api/v1/planner/jobs/${id}`, actorHeaders(actor));
}

export type BodyCarStage = {
  id: string;
  stage_name: string;
  note: string | null;
  start_date: string;
  end_date: string;
};

export type BodyCarStageWrite = {
  stage_name: string;
  note: string | null;
  start_date: string;
  end_date: string;
};

export type BodyCar = {
  id: string;
  workshop_id: string;
  work_order_id: string | null;
  work_order_number: string | null;
  amount: string | null;
  car_description: string | null;
  vin: string | null;
  plate: string | null;
  client_name: string | null;
  work_description: string | null;
  color: string;
  status: string;
  stages: BodyCarStage[];
};

export type BodyCarWrite = {
  work_order_id: string | null;
  car_description: string | null;
  vin: string | null;
  plate: string | null;
  client_name: string | null;
  work_description: string | null;
  status: string;
  stages: BodyCarStageWrite[];
};

export function getBodyCars(workshopId: string): Promise<BodyCar[]> {
  return backendGet<BodyCar[]>(`/api/v1/planner/workshops/${workshopId}/cars`);
}

export function createBodyCar(
  workshopId: string,
  payload: BodyCarWrite,
  actor: { id: string; fullName: string },
): Promise<BodyCar> {
  return backendPost<BodyCar>(`/api/v1/planner/workshops/${workshopId}/cars`, payload, actorHeaders(actor));
}

export function updateBodyCar(
  id: string,
  payload: BodyCarWrite,
  actor: { id: string; fullName: string },
): Promise<BodyCar> {
  return backendPut<BodyCar>(`/api/v1/planner/cars/${id}`, payload, actorHeaders(actor));
}

export function deleteBodyCar(id: string, actor: { id: string; fullName: string }): Promise<void> {
  return backendDelete(`/api/v1/planner/cars/${id}`, actorHeaders(actor));
}
