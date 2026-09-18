import { SettingsForm } from "@/components/SettingsForm";
import { getAppSettings, getRepairTypes } from "@/lib/backend-api";

// Must never be statically prerendered: if the backend happens to be
// reachable at build time, Next.js could otherwise freeze this page with
// build-time data that never updates after deploy until the next rebuild.
export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  let settings;
  let repairTypes: string[] = [];
  let error: string | null = null;

  try {
    const [settingsRes, repairTypesRes] = await Promise.all([getAppSettings(), getRepairTypes()]);
    settings = settingsRes;
    repairTypes = repairTypesRes.repair_types;
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div>
      <h1>Настройки</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {settings && <SettingsForm initialSettings={settings} repairTypes={repairTypes} />}
    </div>
  );
}
