"use client";

// Client-side fetch wrappers for the Planner, talking to the proxy routes
// under app/api/planner/* - the client-safe counterpart to the server-only
// functions in lib/backend-api.ts (types reused via `import type`, erased
// by TypeScript, so none of that file's server-only code reaches the
// browser bundle). See lib/admin-client.ts for the same pattern.
import type {
  BodyCar,
  BodyCarWrite,
  PlannerWorkOrder,
  WorkshopJob,
  WorkshopJobWrite,
} from "@/lib/backend-api";

async function proxyFetch<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(typeof body.error === "string" ? body.error : `Request failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const jsonHeaders = { "Content-Type": "application/json" };

export function searchWorkOrders(q: string): Promise<PlannerWorkOrder[]> {
  return proxyFetch<PlannerWorkOrder[]>(`/api/planner/work-orders/search?q=${encodeURIComponent(q)}`);
}

export const workshopJobsApi = {
  // The URL is otherwise identical across reloads (same workshop/date
  // range), and `cache: "no-store"` alone did not stop stale data from
  // showing right after a drag/edit's PUT resolved (some cache between the
  // browser and the response was still serving the pre-write version). A
  // `_=${Date.now()}` param makes every request's URL unique, which no
  // cache - browser, proxy, or otherwise - can serve a stored response for.
  list: (workshopId: string, dateFrom: string, dateTo: string) =>
    proxyFetch<WorkshopJob[]>(
      `/api/planner/workshops/${workshopId}/jobs?date_from=${dateFrom}&date_to=${dateTo}&_=${Date.now()}`,
      { cache: "no-store" },
    ),
  create: (workshopId: string, payload: WorkshopJobWrite) =>
    proxyFetch<WorkshopJob>(`/api/planner/workshops/${workshopId}/jobs`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: WorkshopJobWrite) =>
    proxyFetch<WorkshopJob>(`/api/planner/jobs/${id}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  remove: (id: string) => proxyFetch<void>(`/api/planner/jobs/${id}`, { method: "DELETE" }),
};

export const bodyCarsApi = {
  list: (workshopId: string) =>
    proxyFetch<BodyCar[]>(`/api/planner/workshops/${workshopId}/cars?_=${Date.now()}`, { cache: "no-store" }),
  create: (workshopId: string, payload: BodyCarWrite) =>
    proxyFetch<BodyCar>(`/api/planner/workshops/${workshopId}/cars`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: BodyCarWrite) =>
    proxyFetch<BodyCar>(`/api/planner/cars/${id}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  remove: (id: string) => proxyFetch<void>(`/api/planner/cars/${id}`, { method: "DELETE" }),
};
