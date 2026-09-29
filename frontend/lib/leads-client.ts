"use client";

// Client-side fetch wrappers for Заявки, talking to the proxy routes under
// app/api/leads/* - the client-safe counterpart to the server-only
// functions in lib/backend-api.ts. Same shape as lib/telephony-client.ts.
import type {
  LeadsSettings,
  LeadsSettingsWrite,
  OpenLeadsResponse,
  WebsiteLeadsResponse,
} from "@/lib/backend-api";

async function proxyFetch<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(typeof body.error === "string" ? body.error : `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

const jsonHeaders = { "Content-Type": "application/json" };
const noStoreFresh: RequestInit = { cache: "no-store" };
function bust(path: string): string {
  return `${path}${path.includes("?") ? "&" : "?"}_=${Date.now()}`;
}

export const leadsApi = {
  list: () => proxyFetch<WebsiteLeadsResponse>(bust("/api/leads"), noStoreFresh),
  open: () => proxyFetch<OpenLeadsResponse>(bust("/api/leads/open"), noStoreFresh),
};

export const leadsSettingsApi = {
  get: () => proxyFetch<LeadsSettings>(bust("/api/leads/settings"), noStoreFresh),
  update: (payload: LeadsSettingsWrite) =>
    proxyFetch<LeadsSettings>("/api/leads/settings", {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  regenerateToken: () =>
    proxyFetch<{ intake_token: string }>("/api/leads/settings/regenerate-token", { method: "POST" }),
};
