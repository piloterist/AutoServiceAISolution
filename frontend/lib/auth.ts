// Signed-cookie session for the per-user auth layer (see app/login,
// app/api/auth/*, middleware.ts, backend app/models/user.py). The cookie
// carries the user's identity/role claims directly (base64url(JSON).sig) -
// self-contained and self-expiring, so middleware (Edge runtime, can't
// reach Postgres) never needs a server-side session lookup to know who's
// asking and what role they have, same tradeoff the previous single-
// shared-login version already made (no revocation short of the cookie
// expiring or AUTH_SECRET rotating - acceptable for a handful of internal
// accounts). Uses Web Crypto only (no Node `crypto` module, no `Buffer`)
// so the same code runs unchanged in the Edge middleware and in the Node
// route handlers.

export const SESSION_COOKIE_NAME = "pm_session";

// Mirrors backend app/models/user.py's ROLE_ADMIN - only this role can
// reach /settings (see middleware.ts).
export const ROLE_ADMIN = "Админ";

// Mirrors backend app/models/user.py's ROLE_SERVICE_ADVISOR - the reverse
// restriction from ROLE_ADMIN above: this role can reach ONLY /planner
// (see middleware.ts) - a tabs/pages-level restriction only, nothing
// inside the Planner itself is further gated by role.
export const ROLE_SERVICE_ADVISOR = "Мастер приёмщик";

export type SessionUser = {
  id: string;
  fullName: string;
  login: string;
  role: string;
  departmentId: string | null;
  departmentName: string | null;
  workshopId: string | null;
};

type SessionPayload = SessionUser & { exp: number };

const SESSION_DURATION_MS = 30 * 24 * 60 * 60 * 1000; // 30 days
export const SESSION_MAX_AGE_SECONDS = SESSION_DURATION_MS / 1000;

function getSecret(): string {
  const secret = process.env.AUTH_SECRET;
  if (!secret) {
    throw new Error("AUTH_SECRET is not set - required to sign/verify the login session cookie.");
  }
  return secret;
}

function toBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sign(message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(getSecret()),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return toBase64Url(signature);
}

function toBase64UrlString(text: string): string {
  return toBase64Url(new TextEncoder().encode(text).buffer as ArrayBuffer);
}

/** `atob` only undoes base64 - it hands back a "binary string" (one JS char
 * per byte, not per Unicode codepoint), so decoding straight into that and
 * JSON.parse-ing it silently mangles any non-ASCII text (role names, full
 * names are Cyrillic here). Re-decode those bytes as UTF-8 via TextDecoder
 * before parsing - the mirror of toBase64UrlString's TextEncoder above. */
function fromBase64Url(value: string): string {
  const padded = value
    .replace(/-/g, "+")
    .replace(/_/g, "/")
    .padEnd(value.length + ((4 - (value.length % 4)) % 4), "=");
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

/** `base64url(JSON payload).signature` - see module comment on why this is
 * self-contained rather than a bare session id needing a DB lookup. */
export async function createSessionToken(user: SessionUser): Promise<string> {
  const payload: SessionPayload = { ...user, exp: Date.now() + SESSION_DURATION_MS };
  const encoded = toBase64UrlString(JSON.stringify(payload));
  const signature = await sign(encoded);
  return `${encoded}.${signature}`;
}

/** Verifies the signature and expiry, and returns the carried user/role
 * claims - or null for a missing/tampered/expired/malformed cookie. */
export async function readSessionToken(
  token: string | undefined | null,
): Promise<SessionUser | null> {
  if (!token) return null;

  const [encoded, signature] = token.split(".");
  if (!encoded || !signature) return null;

  const expected = await sign(encoded);
  if (expected !== signature) return null;

  try {
    const payload = JSON.parse(fromBase64Url(encoded)) as SessionPayload;
    if (!Number.isFinite(payload.exp) || payload.exp < Date.now()) return null;
    return {
      id: payload.id,
      fullName: payload.fullName,
      login: payload.login,
      role: payload.role,
      departmentId: payload.departmentId,
      departmentName: payload.departmentName,
      workshopId: payload.workshopId,
    };
  } catch {
    return null;
  }
}

export async function isValidSessionToken(token: string | undefined | null): Promise<boolean> {
  return (await readSessionToken(token)) !== null;
}

/** Only ever redirect to a same-site path - `next` round-trips through a
 * query param, so without this an attacker-crafted login link
 * (`?next=https://evil.example`) could bounce a successful login to an
 * external site (open redirect). */
export function safeNextPath(next: string | null | undefined): string {
  if (next && next.startsWith("/") && !next.startsWith("//")) return next;
  return "/dashboard";
}

/** Builds an absolute URL for a redirect Response, preferring the
 * X-Forwarded-* headers Timeweb's Caddy reverse proxy sets over
 * `request.url` - the Next.js standalone server binds to
 * `HOSTNAME=0.0.0.0` (see frontend/Dockerfile, a fix for an unrelated
 * container-networking bug), which then leaks into `request.url` in a Node
 * route handler (unlike Edge middleware, which reports it correctly) and
 * produces a redirect to `https://0.0.0.0:3000/...` - unreachable from a
 * real browser. */
export function absoluteUrl(path: string, request: Request): URL {
  const forwardedHost = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (forwardedHost) {
    const forwardedProto = request.headers.get("x-forwarded-proto") ?? "https";
    return new URL(path, `${forwardedProto}://${forwardedHost}`);
  }
  return new URL(path, request.url);
}
