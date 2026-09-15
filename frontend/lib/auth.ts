// Minimal signed-cookie session for the single hardcoded operator login
// (see app/login, app/api/auth/*, middleware.ts). There is no user
// database and no per-user state - there's exactly one account for now,
// so a signed, self-expiring cookie is all "authentication" needs to mean
// here (see ARCHITECTURE.md on the lack of a real auth system yet). Uses
// Web Crypto only (no Node `crypto` module, no `Buffer`) so the same code
// runs unchanged in the Edge middleware and in the Node route handlers.

export const SESSION_COOKIE_NAME = "pm_session";

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

/** `expiresAt.signature` - carries its own expiry so there's no server-side
 * session store to check against (nothing to invalidate short of rotating
 * AUTH_SECRET, which is an acceptable tradeoff for a single hardcoded
 * account). */
export async function createSessionToken(): Promise<string> {
  const expiresAt = Date.now() + SESSION_DURATION_MS;
  const signature = await sign(String(expiresAt));
  return `${expiresAt}.${signature}`;
}

export async function isValidSessionToken(token: string | undefined | null): Promise<boolean> {
  if (!token) return false;

  const [expiresAtRaw, signature] = token.split(".");
  if (!expiresAtRaw || !signature) return false;

  const expiresAt = Number(expiresAtRaw);
  if (!Number.isFinite(expiresAt) || expiresAt < Date.now()) return false;

  const expected = await sign(expiresAtRaw);
  return expected === signature;
}

export function checkCredentials(username: string, password: string): boolean {
  return Boolean(
    process.env.AUTH_USERNAME &&
      process.env.AUTH_PASSWORD &&
      username === process.env.AUTH_USERNAME &&
      password === process.env.AUTH_PASSWORD,
  );
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
