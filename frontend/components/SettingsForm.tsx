"use client";

import { useState } from "react";

import type { AppSettings } from "@/lib/backend-api";

type SaveState = "idle" | "saving" | "saved" | "error";

export function SettingsForm({
  initialSettings,
  repairTypes,
}: {
  initialSettings: AppSettings;
  /** Distinct ЗаказНаряд.ВидРемонта values actually present in imported
   * work orders (see getRepairTypes) - never a hardcoded list. */
  repairTypes: string[];
}) {
  const [insuranceRepairType, setInsuranceRepairType] = useState(
    initialSettings.insurance_repair_type ?? "",
  );
  const [excludeInternal, setExcludeInternal] = useState(
    initialSettings.exclude_internal_insurance,
  );
  const [saveState, setSaveState] = useState<SaveState>("idle");

  const handleSave = async () => {
    setSaveState("saving");
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          insurance_repair_type: insuranceRepairType || null,
          exclude_internal_insurance: excludeInternal,
        } satisfies AppSettings),
      });
      if (!res.ok) throw new Error(await res.text());
      setSaveState("saved");
    } catch {
      setSaveState("error");
    } finally {
      setTimeout(() => setSaveState("idle"), 2000);
    }
  };

  const saveLabel =
    saveState === "saving"
      ? "Сохранение…"
      : saveState === "saved"
        ? "Сохранено ✓"
        : saveState === "error"
          ? "Не удалось сохранить"
          : "Сохранить";

  return (
    <div className="card settings-card">
      <h2 className="chart-title">Страховые</h2>

      <div className="settings-field">
        <label htmlFor="insurance-repair-type">Вид ремонта для страховых</label>
        <select
          id="insurance-repair-type"
          value={insuranceRepairType}
          onChange={(event) => setInsuranceRepairType(event.target.value)}
        >
          <option value="">Не выбрано</option>
          {repairTypes.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </div>

      <label className="settings-checkbox">
        <input
          type="checkbox"
          checked={excludeInternal}
          onChange={(event) => setExcludeInternal(event.target.checked)}
        />
        Исключить внутренние по страховым
      </label>

      <button
        type="button"
        className="settings-save"
        onClick={handleSave}
        disabled={saveState === "saving"}
      >
        {saveLabel}
      </button>
    </div>
  );
}
