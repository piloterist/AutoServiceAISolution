"use client";

// Client-side fetch wrappers for the Боксы page, talking to the proxy routes
// under app/api/bays/* (the client-safe counterpart to the server-only
// functions in lib/backend-api.ts - types are reused via `import type`).
import type {
  BayEvent,
  BayHistoryResponse,
  BaySnapshotRequest,
  BaysResponse,
  GateStay,
  GateStaysResponse,
} from "@/lib/backend-api";

async function proxyFetch<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, { cache: "no-store", ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(typeof body.error === "string" ? body.error : `Ошибка запроса: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const jsonHeaders = { "Content-Type": "application/json" };

export const baysClient = {
  list: (workshopId: string) =>
    proxyFetch<BaysResponse>(`/api/bays?workshop_id=${encodeURIComponent(workshopId)}`),
  createDefaults: (workshopId: string) =>
    proxyFetch<BaysResponse>(`/api/bays/defaults?workshop_id=${encodeURIComponent(workshopId)}`, {
      method: "POST",
    }),
  create: (workshopId: string, name: string, kind: "bay" | "gate" = "bay") =>
    proxyFetch<BaysResponse>("/api/bays", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ workshop_id: workshopId, name, kind }),
    }),
  setCameraCode: (bayId: string, cameraCode: string) =>
    proxyFetch<BaysResponse>(`/api/bays/${bayId}`, {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify({ camera_code: cameraCode }),
    }),
  addEvent: (bayId: string, eventType: string, plate: string) =>
    proxyFetch<BayEvent>(`/api/bays/${bayId}/events`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ event_type: eventType, plate: plate || null }),
    }),
  history: (params: { dateFrom?: string; dateTo?: string; bayId?: string; jobId?: string }) => {
    const query = new URLSearchParams();
    if (params.dateFrom) query.set("date_from", params.dateFrom);
    if (params.dateTo) query.set("date_to", params.dateTo);
    if (params.bayId) query.set("bay_id", params.bayId);
    if (params.jobId) query.set("job_id", params.jobId);
    return proxyFetch<BayHistoryResponse>(`/api/bays/history?${query.toString()}`);
  },
  // Ворота кузовного цеха: машины внутри (status=inside) или все заезды за период.
  gateStays: (params: { workshopId: string; status: "inside" | "all"; dateFrom?: string; dateTo?: string }) => {
    const query = new URLSearchParams({ workshop_id: params.workshopId, status: params.status });
    if (params.dateFrom) query.set("date_from", params.dateFrom);
    if (params.dateTo) query.set("date_to", params.dateTo);
    return proxyFetch<GateStaysResponse>(`/api/bays/gate/stays?${query.toString()}`);
  },
  addGateStay: (payload: { bayId: string; plate?: string; label?: string; enteredAt?: string }) =>
    proxyFetch<GateStay>("/api/bays/gate/stays", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        bay_id: payload.bayId,
        plate: payload.plate || null,
        label: payload.label || null,
        entered_at: payload.enteredAt || null,
      }),
    }),
  exitGateStay: (stayId: string, exitedAt?: string) =>
    proxyFetch<GateStay>(`/api/bays/gate/stays/${stayId}/exit`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ exited_at: exitedAt || null }),
    }),
  updateGateStay: (stayId: string, payload: { plate: string | null; label: string | null }) =>
    proxyFetch<GateStay>(`/api/bays/gate/stays/${stayId}`, {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  requestSnapshot: (bayId: string) =>
    proxyFetch<BaySnapshotRequest>(`/api/bays/${bayId}/snapshot-requests`, { method: "POST" }),
  snapshotRequest: (requestId: string) =>
    proxyFetch<BaySnapshotRequest>(`/api/bays/snapshot-requests/${requestId}`),
};

export const eventSnapshotUrl = (eventId: string) => `/api/bays/events/${eventId}/snapshot`;
export const requestImageUrl = (requestId: string) => `/api/bays/snapshot-requests/${requestId}/image`;
export const latestFrameUrl = (bayId: string, at: string) =>
  `/api/bays/${bayId}/latest-frame?t=${encodeURIComponent(at)}`;
