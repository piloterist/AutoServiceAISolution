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
  // "Специфика PanMotors" - a separate feature from the two above (which
  // drive the older insurance-reporting exclusion): gates
  // WorkOrder.is_internal, a car/VIN-and-org/payer-based detection (see
  // backend services/internal_order_rules.py), not an order-number/
  // repair-type-based one.
  const [excludeInternalOrders, setExcludeInternalOrders] = useState(
    initialSettings.exclude_internal_orders,
  );
  const [hideInternalOrders, setHideInternalOrders] = useState(
    initialSettings.hide_internal_orders,
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
          exclude_internal_orders: excludeInternalOrders,
          hide_internal_orders: hideInternalOrders,
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
    <>
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
      </div>

      <div className="card settings-card settings-card--wide">
        <h2 className="chart-title">Специфика PanMotors</h2>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={excludeInternalOrders}
            onChange={(event) => setExcludeInternalOrders(event.target.checked)}
          />
          Исключить внутренние
        </label>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={hideInternalOrders}
            onChange={(event) => setHideInternalOrders(event.target.checked)}
          />
          Скрыть внутренние <span className="settings-hint">(в разработке)</span>
        </label>

        <p className="settings-description">
          <strong>Правила определения внутренних.</strong> Заказ-наряд считается «внутренним», если
          одновременно выполнены два условия: (1) на этот же автомобиль (по VIN) есть хотя бы один
          «внешний» заказ-наряд с видом ремонта «Страховой»; и (2) организация и плательщик
          заказ-наряда проходят правило, заданное для этой организации (для одних организаций
          внутренний заказ-наряд допускается всегда, для других — только если плательщик не
          физическое лицо). Заказ-наряды без распознанного VIN никогда не считаются внутренними.
          Галка «Исключить внутренние» выше влияет только на показатели дашборда (плашки,
          диаграммы) — как будто таких заказ-нарядов не существует; на список заказ-нарядов не
          влияет, там есть отдельный фильтр «Внутренний».
        </p>

        <button
          type="button"
          className="settings-save"
          onClick={handleSave}
          disabled={saveState === "saving"}
        >
          {saveLabel}
        </button>
      </div>
    </>
  );
}
