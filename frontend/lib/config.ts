// All environment-specific values must come from env vars - never hardcode a
// client's backend URL here. NEXT_PUBLIC_* vars are baked in at build/runtime
// per deployed instance.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
