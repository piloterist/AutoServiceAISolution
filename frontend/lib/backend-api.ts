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
  phone: string | null;
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
  theme: string;
  department_id: string | null;
  department_name: string | null;
  workshop_id: string | null;
  allowed_tabs: string[];
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
  // Планирование - см. backend app/models/workshop.py.
  zero_revenue: string | null;
  target_revenue: string | null;
  target_norm_hours: string | null;
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
  zero_revenue?: string | null;
  target_revenue?: string | null;
  target_norm_hours?: string | null;
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

// Раздел 1С -> цех: maps a raw WorkOrder.department string (as sent by 1C)
// to a Workshop - see app/models/workshop_source_department.py for why this
// mapping table exists (many raw strings can map to one Workshop; company-
// wide totals include unmapped revenue too, but a specific-workshop filter
// only sees revenue whose department string is mapped here).
export type WorkshopSourceDepartment = {
  id: string;
  workshop_id: string;
  workshop_label: string; // "<Подразделение> — <Тип цеха>"
  source_department: string;
};

export type WorkshopSourceDepartmentWrite = {
  workshop_id: string;
  source_department: string;
};

export function getWorkshopSourceDepartments(): Promise<WorkshopSourceDepartment[]> {
  return backendGet<WorkshopSourceDepartment[]>("/api/v1/settings/workshop-source-departments");
}

/** Raw WorkOrder.department strings with real closed work orders but no
 * mapping row yet - surfaced in the tab as one-click "add" suggestions. */
export function getUnmappedSourceDepartments(): Promise<string[]> {
  return backendGet<{ values: string[] }>(
    "/api/v1/settings/workshop-source-departments/unmapped",
  ).then((r) => r.values);
}

export function createWorkshopSourceDepartment(
  payload: WorkshopSourceDepartmentWrite,
): Promise<WorkshopSourceDepartment> {
  return backendPost<WorkshopSourceDepartment>(
    "/api/v1/settings/workshop-source-departments",
    payload,
  );
}

export function updateWorkshopSourceDepartment(
  id: string,
  payload: WorkshopSourceDepartmentWrite,
): Promise<WorkshopSourceDepartment> {
  return backendPut<WorkshopSourceDepartment>(
    `/api/v1/settings/workshop-source-departments/${id}`,
    payload,
  );
}

export function deleteWorkshopSourceDepartment(id: string): Promise<void> {
  return backendDelete(`/api/v1/settings/workshop-source-departments/${id}`);
}

export type OrgUser = {
  id: string;
  full_name: string;
  login: string;
  role: string;
  theme: string;
  department_id: string | null;
  department_name: string | null;
  workshop_id: string | null;
};

export type OrgUserCreate = {
  full_name: string;
  login: string;
  password: string;
  role: string;
  theme: string;
  department_id: string | null;
  workshop_id: string | null;
};

export type OrgUserUpdate = {
  full_name: string;
  login: string;
  password?: string | null; // empty/omitted keeps the existing password
  role: string;
  theme: string;
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
  work_order_number: string | null;
  car_description: string | null;
};

export function getAuditLog(): Promise<AuditLogEntry[]> {
  return backendGet<AuditLogEntry[]>("/api/v1/settings/audit-log");
}

export type Employee = {
  id: string;
  full_name: string;
  specialty: string;
  department_id: string | null;
  department_name: string | null;
  workshop_id: string | null;
  workshop_label: string | null; // "Каховка / Слесарный"
};

export type EmployeeWrite = {
  full_name: string;
  specialty: string;
  department_id: string | null;
  workshop_id: string | null;
};

export function getEmployees(): Promise<Employee[]> {
  return backendGet<Employee[]>("/api/v1/settings/employees");
}

export function createEmployee(payload: EmployeeWrite): Promise<Employee> {
  return backendPost<Employee>("/api/v1/settings/employees", payload);
}

export function updateEmployee(id: string, payload: EmployeeWrite): Promise<Employee> {
  return backendPut<Employee>(`/api/v1/settings/employees/${id}`, payload);
}

export function deleteEmployee(id: string): Promise<void> {
  return backendDelete(`/api/v1/settings/employees/${id}`);
}

export type RoleTabVisibility = {
  id: string;
  role: string;
  visible_tabs: string[];
};

export type RoleTabVisibilityWrite = {
  role: string;
  visible_tabs: string[];
};

export function getRoleTabVisibility(): Promise<RoleTabVisibility[]> {
  return backendGet<RoleTabVisibility[]>("/api/v1/settings/role-tab-visibility");
}

export function createRoleTabVisibility(payload: RoleTabVisibilityWrite): Promise<RoleTabVisibility> {
  return backendPost<RoleTabVisibility>("/api/v1/settings/role-tab-visibility", payload);
}

export function updateRoleTabVisibility(
  id: string,
  payload: RoleTabVisibilityWrite,
): Promise<RoleTabVisibility> {
  return backendPut<RoleTabVisibility>(`/api/v1/settings/role-tab-visibility/${id}`, payload);
}

export function deleteRoleTabVisibility(id: string): Promise<void> {
  return backendDelete(`/api/v1/settings/role-tab-visibility/${id}`);
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
  phone: string | null;
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
  phone: string | null;
  work_description: string | null;
  job_date: string; // "YYYY-MM-DD"
  post_number: number;
  start_time: string; // "HH:MM:SS"
  end_time: string;
  norm_hours: string | null;
  status_id: string | null;
  status_name: string | null;
  status_color: string | null;
  employee_id: string | null;
  employee_name: string | null;
};

export type WorkshopJobWrite = {
  work_order_id: string | null;
  car_description: string | null;
  vin: string | null;
  plate: string | null;
  client_name: string | null;
  phone: string | null;
  employee_id: string | null;
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
  employee_id: string | null;
  employee_name: string | null;
};

export type BodyCarStageWrite = {
  stage_name: string;
  note: string | null;
  start_date: string;
  end_date: string;
  employee_id: string | null;
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
  phone: string | null;
  work_description: string | null;
  color: string;
  status: string;
  on_site: boolean;
  stages: BodyCarStage[];
  created_at: string;
};

export type BodyCarWrite = {
  work_order_id: string | null;
  car_description: string | null;
  vin: string | null;
  plate: string | null;
  client_name: string | null;
  phone: string | null;
  work_description: string | null;
  status: string;
  on_site: boolean;
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

// ============================================================================
// IP-телефония (Settings -> IP-телефония + /telephony stats page) - see
// backend app/api/v1/endpoints/telephony.py.
// ============================================================================

export type TelephonySettings = {
  provider: string;
  enabled: boolean;
  zeon_api_url: string | null;
  zeon_api_key: string | null;
  zeon_auth: "bearer" | "hash";
  yandex_disk_token: string | null;
  yandex_disk_base_path: string | null;
  operator_names: string | null;
  poll_interval_minutes: number | null;
  zeon_audio_method: "get-mp3" | "get-file";
  yc_api_key: string | null;
  yc_folder_id: string | null;
  speechkit_model: string;
  speechkit_language: string;
  speechkit_timeout_min: number;
};

export type TelephonySettingsWrite = {
  enabled: boolean;
  zeon_api_url: string | null;
  zeon_api_key: string | null;
  zeon_auth: "bearer" | "hash";
  yandex_disk_token: string | null;
  yandex_disk_base_path: string | null;
  operator_names: string | null;
  poll_interval_minutes: number | null;
  zeon_audio_method: "get-mp3" | "get-file";
  yc_api_key: string | null;
  yc_folder_id: string | null;
  speechkit_model: string;
  speechkit_language: string;
  speechkit_timeout_min: number;
};

export function getTelephonySettings(): Promise<TelephonySettings> {
  return backendGet<TelephonySettings>("/api/v1/telephony/settings");
}

export function updateTelephonySettings(payload: TelephonySettingsWrite): Promise<TelephonySettings> {
  return backendPut<TelephonySettings>("/api/v1/telephony/settings", payload);
}

export type TelephonyPingResult = { ok: boolean; error: string | null };

export function pingTelephony(): Promise<TelephonyPingResult> {
  return backendPost<TelephonyPingResult>("/api/v1/telephony/ping", {});
}

export type TelephonyImportResult = { fetched: number; upserted: number };

export function triggerTelephonyImport(
  range?: { startDate: string; endDate: string },
): Promise<TelephonyImportResult> {
  return backendPost<TelephonyImportResult>("/api/v1/telephony/import", {
    start_date: range?.startDate ?? null,
    end_date: range?.endDate ?? null,
  });
}

export type CallRecordingExportResult = { status: string; start_date: string; end_date: string };

/** "Выгрузить и расшифровать" button - fetches call recordings from Zeon,
 * archives them to Yandex.Disk, and transcribes them via Yandex SpeechKit.
 * Runs in the background on the backend (see endpoints/telephony.py) - this
 * call returns as soon as the run is accepted, not once it's finished. */
export function triggerCallRecordingExport(range: {
  startDate: string;
  endDate: string;
}): Promise<CallRecordingExportResult> {
  return backendPost<CallRecordingExportResult>("/api/v1/telephony/recordings/export", {
    start_date: range.startDate,
    end_date: range.endDate,
  });
}

export type PhoneSource = {
  id: string;
  line_code: string;
  name: string;
  caption: string | null;
  group_name: string;
  sort_order: number;
};

export type PhoneSourceWrite = {
  line_code: string;
  name: string;
  caption: string | null;
  group_name: string;
  sort_order: number;
};

export function getPhoneSources(): Promise<PhoneSource[]> {
  return backendGet<PhoneSource[]>("/api/v1/telephony/sources");
}

export function createPhoneSource(payload: PhoneSourceWrite): Promise<PhoneSource> {
  return backendPost<PhoneSource>("/api/v1/telephony/sources", payload);
}

export function updatePhoneSource(id: string, payload: PhoneSourceWrite): Promise<PhoneSource> {
  return backendPut<PhoneSource>(`/api/v1/telephony/sources/${id}`, payload);
}

export function deletePhoneSource(id: string): Promise<void> {
  return backendDelete(`/api/v1/telephony/sources/${id}`);
}

export type SourceSummaryRow = {
  line_code: string;
  name: string;
  caption: string | null;
  group_name: string;
  inbound_total: number;
  answered: number;
  missed: number;
  missed_pct: number | null;
  unique_callers: number;
  unique_missed_callers: number;
  outcome_called_back_reached: number;
  outcome_called_back_not_reached: number;
  outcome_client_called_back: number;
  outcome_no_reaction: number;
  reached_pct: number | null;
};

export type SourceSummaryResponse = {
  start_date: string;
  end_date: string;
  rows: SourceSummaryRow[];
};

export function getSourceSummary(params?: { startDate?: string; endDate?: string }): Promise<SourceSummaryResponse> {
  return backendGet<SourceSummaryResponse>("/api/v1/telephony/source-summary", {
    start_date: params?.startDate ?? "",
    end_date: params?.endDate ?? "",
  });
}

export type LineCallEvent = {
  time: string; // "YYYY-MM-DD HH:MM:SS", Moscow-local
  direction: "in" | "out";
  role: "incoming" | "callback" | "client_recall";
  client: string | null;
  operator: string | null;
  // Extensions that also rang but didn't pick up (Zeon's "lost", minus
  // whichever extension ended up as `operator`) - together with `operator`
  // (when answered), every extension the call rang on. Both empty means
  // the call never got routed to any extension (e.g. abandoned in an IVR).
  rang_not_answered: string[];
  answered: boolean;
  wait_sec: number;
  talk_sec: number;
};

export type LineCallsResponse = {
  line_code: string;
  start_date: string;
  end_date: string;
  events: LineCallEvent[];
};

export function getLineCalls(params: {
  lineCode: string;
  startDate?: string;
  endDate?: string;
}): Promise<LineCallsResponse> {
  return backendGet<LineCallsResponse>("/api/v1/telephony/source-summary/calls", {
    line_code: params.lineCode,
    start_date: params.startDate ?? "",
    end_date: params.endDate ?? "",
  });
}

// Planner's phone-icon badge (see backend telephony_stats_service.
// get_open_missed_calls for the resolution rules - a rolling 2-Moscow-day
// window, >=5s real talk time to count as reached, one real contact clears
// every earlier open miss from that number). Company-wide, not scoped by
// цех - phone lines have no цех of their own in this data model.
export type OpenMissedCall = {
  id: string;
  client: string;
  line: string | null;
  source_label: string | null;
  direction: "in" | "callback";
  time: string; // "YYYY-MM-DD HH:MM:SS", Moscow-local
  operator: string | null;
  // Extensions that rang for an inbound miss (always [] for an outbound
  // callback attempt - `operator` already says which of our own
  // extensions placed that one).
  rang_not_answered: string[];
};

export type OpenMissedCallsResponse = {
  count: number;
  calls: OpenMissedCall[];
};

export function getOpenMissedCalls(): Promise<OpenMissedCallsResponse> {
  return backendGet<OpenMissedCallsResponse>("/api/v1/telephony/missed-calls/open");
}

// ============================================================================
// Заявки (pan-motors.ru website leads) - Planner envelope badge, /leads
// full history page, Settings -> Заявки. See backend
// app/api/v1/endpoints/leads.py, app/services/leads_service.py.
// ============================================================================

export type LeadStatus = "open" | "resolved" | "stale";

export type WebsiteLead = {
  id: string;
  source: string;
  phone: string;
  name: string | null;
  photos: string[] | null;
  raw_payload: Record<string, unknown>;
  created_at: string;
  status: LeadStatus;
};

export type WebsiteLeadsResponse = {
  leads: WebsiteLead[];
};

export type OpenLeadsResponse = {
  count: number;
  leads: WebsiteLead[];
};

export type LeadsSettings = {
  enabled: boolean;
  stale_after_days: number;
  has_intake_token: boolean;
};

export type LeadsSettingsWrite = {
  enabled: boolean;
  stale_after_days: number;
};

export function getLeads(): Promise<WebsiteLeadsResponse> {
  return backendGet<WebsiteLeadsResponse>("/api/v1/leads");
}

export function getOpenLeads(): Promise<OpenLeadsResponse> {
  return backendGet<OpenLeadsResponse>("/api/v1/leads/open");
}

export function getLeadsSettings(): Promise<LeadsSettings> {
  return backendGet<LeadsSettings>("/api/v1/leads/settings");
}

export function updateLeadsSettings(payload: LeadsSettingsWrite): Promise<LeadsSettings> {
  return backendPut<LeadsSettings>("/api/v1/leads/settings", payload);
}

export function regenerateLeadsIntakeToken(): Promise<{ intake_token: string }> {
  return backendPost<{ intake_token: string }>("/api/v1/leads/settings/regenerate-token", {});
}

// ============================================================================
// Cockpit - see backend app/api/v1/endpoints/cockpit.py,
// app/services/cockpit_service.py.
// ============================================================================

export type GaugeScale = {
  step_millions: number;
  max_millions: number;
  labels_millions: number[];
  marker_fraction: number;
};

export type GaugeReading = {
  scale: GaugeScale;
  needle_fraction: number;
  overflow: boolean;
  underflow: boolean;
};

export type CockpitPlan = {
  total_rub: string;
  complete: boolean;
  usable: boolean;
  workshop_count: number;
};

export type CockpitSnapshot = {
  period_start: string;
  period_end: string;
  timezone: string;
  workshop_id: string | null;
  workshop_label: string | null;
  revenue_rub: string;
  nzp_rub: string | null;
  effective_revenue_rub: string;
  payments_rub: string;
  plan: CockpitPlan;
  revenue_gauge: GaugeReading;
  payments_gauge: GaugeReading;
  has_unattributed_revenue: boolean;
};

export function getCockpitSnapshot(params?: {
  workshopId?: string;
  includeNzp?: boolean;
}): Promise<CockpitSnapshot> {
  return backendGet<CockpitSnapshot>("/api/v1/cockpit", {
    workshop_id: params?.workshopId ?? "",
    include_nzp: params?.includeNzp ? "true" : "",
  });
}

export type WorkshopOption = {
  id: string;
  department_name: string;
  workshop_type: string;
};

/** Cockpit's own "цех" filter dropdown - reuses the existing Settings ->
 * Цеха list rather than a separate endpoint (see getWorkshops for the
 * fuller admin shape; this is the same data, just typed for the filter). */
export function getWorkshopOptions(): Promise<WorkshopOption[]> {
  return backendGet<WorkshopOption[]>("/api/v1/settings/workshops");
}
