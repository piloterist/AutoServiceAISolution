import { SettingsForm } from "@/components/SettingsForm";
import { getAppSettings, getRepairTypes } from "@/lib/backend-api";

// See app/work-orders/page.tsx for why this is required.
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
