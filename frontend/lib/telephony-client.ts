"use client";

// Client-side fetch wrappers for IP-телефония, talking to the proxy routes
// under app/api/telephony/* - the client-safe counterpart to the
// server-only functions in lib/backend-api.ts (types reused via
// `import type`, erased at build time). Same shape as lib/admin-client.ts.
import type {
  CallRecordingExportResult,
  LineCallsResponse,
  PhoneSource,
  PhoneSourceWrite,
  SourceSummaryResponse,
  TelephonyImportResult,
  TelephonyPingResult,
  TelephonySettings,
  TelephonySettingsWrite,
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
const noStoreFresh: RequestInit = { cache: "no-store" };
function bust(path: string): string {
  return `${path}${path.includes("?") ? "&" : "?"}_=${Date.now()}`;
}

export const telephonySettingsApi = {
  get: () => proxyFetch<TelephonySettings>(bust("/api/telephony/settings"), noStoreFresh),
  update: (payload: TelephonySettingsWrite) =>
    proxyFetch<TelephonySettings>("/api/telephony/settings", {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  ping: () => proxyFetch<TelephonyPingResult>("/api/telephony/ping", { method: "POST" }),
  importNow: (range?: { startDate: string; endDate: string }) =>
    proxyFetch<TelephonyImportResult>("/api/telephony/import", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(range ?? {}),
    }),
  exportRecordings: (range: { startDate: string; endDate: string }) =>
    proxyFetch<CallRecordingExportResult>("/api/telephony/recordings/export", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(range),
    }),
};

export const phoneSourcesApi = {
  list: () => proxyFetch<PhoneSource[]>(bust("/api/telephony/sources"), noStoreFresh),
  create: (payload: PhoneSourceWrite) =>
    proxyFetch<PhoneSource>("/api/telephony/sources", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: PhoneSourceWrite) =>
    proxyFetch<PhoneSource>(`/api/telephony/sources/${id}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  remove: (id: string) => proxyFetch<void>(`/api/telephony/sources/${id}`, { method: "DELETE" }),
};

export function getSourceSummaryClient(params: { startDate: string; endDate: string }): Promise<SourceSummaryResponse> {
  return proxyFetch<SourceSummaryResponse>(
    bust(`/api/telephony/source-summary?start_date=${params.startDate}&end_date=${params.endDate}`),
    noStoreFresh,
  );
}

export function getLineCallsClient(params: {
  lineCode: string;
  startDate: string;
  endDate: string;
}): Promise<LineCallsResponse> {
  const query = new URLSearchParams({
    line_code: params.lineCode,
    start_date: params.startDate,
    end_date: params.endDate,
  });
  return proxyFetch<LineCallsResponse>(bust(`/api/telephony/source-summary/calls?${query}`), noStoreFresh);
}
