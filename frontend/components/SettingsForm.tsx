"use client";

import { useState } from "react";

import type { AppSettings, AutoMatchResult } from "@/lib/backend-api";

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
  // Planner's "Получить ЗН" live 5Systems plate lookup - a runtime switch
  // staff can flip here without a deploy. Still requires the backend's own
  // ENABLE_FIVESYSTEMS_LOOKUP env var (credentials configured) - this
  // checkbox alone can't turn the feature on if that isn't set too, see
  // backend/app/models/app_settings.py.
  const [fivesystemsApiEnabled, setFivesystemsApiEnabled] = useState(
    initialSettings.fivesystems_api_enabled,
  );
  // Every non-Admin session still open at/after this time (Moscow) gets
  // force-logged-out - see lib/auth.ts's nextDailyBoundary and
  // middleware.ts. Baked into the session cookie at login, so a change
  // here takes effect for logins AFTER the save, same staleness tradeoff
  // allowedTabs already has (no mid-session push, no server-side session
  // store to revoke from - see lib/auth.ts's module comment).
  const [dailyLogoutTime, setDailyLogoutTime] = useState(initialSettings.daily_logout_time);
  // Auto-links an unlinked Planner record (WorkshopJob/BodyCar with no ЗН
  // yet) to a work order imported shortly afterward, matched by phone or
  // VIN - see backend services/planner_service.auto_match_planner_records.
  const [plannerAutoMatchEnabled, setPlannerAutoMatchEnabled] = useState(
    initialSettings.planner_auto_match_enabled,
  );
  const [plannerAutoMatchIntervalMinutes, setPlannerAutoMatchIntervalMinutes] = useState(
    String(initialSettings.planner_auto_match_interval_minutes),
  );
  const [plannerSearchExcludeClosedOrders, setPlannerSearchExcludeClosedOrders] = useState(
    initialSettings.planner_search_exclude_closed_orders,
  );
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [autoMatchState, setAutoMatchState] = useState<"idle" | "running" | "done" | "error">(
    "idle",
  );
  const [autoMatchMessage, setAutoMatchMessage] = useState<string | null>(null);

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
          fivesystems_api_enabled: fivesystemsApiEnabled,
          daily_logout_time: dailyLogoutTime,
          planner_auto_match_enabled: plannerAutoMatchEnabled,
          planner_auto_match_interval_minutes: Number(plannerAutoMatchIntervalMinutes) || 180,
          planner_search_exclude_closed_orders: plannerSearchExcludeClosedOrders,
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

  const handleAutoMatchNow = async () => {
    setAutoMatchState("running");
    setAutoMatchMessage(null);
    try {
      const res = await fetch("/api/planner/auto-match", { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const result = (await res.json()) as AutoMatchResult;
      setAutoMatchState("done");
      setAutoMatchMessage(
        `Проверено записей: ${result.processed}, привязано: ${result.matched}`,
      );
    } catch (err) {
      setAutoMatchState("error");
      setAutoMatchMessage(err instanceof Error ? err.message : "Не удалось выполнить");
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
      </div>

      <div className="card settings-card">
        <h2 className="chart-title">Сессия</h2>

        <div className="settings-field">
          <label htmlFor="daily-logout-time">Автовыход в</label>
          <input
            id="daily-logout-time"
            type="time"
            value={dailyLogoutTime}
            onChange={(event) => setDailyLogoutTime(event.target.value)}
          />
        </div>

        <p className="settings-description">
          Ежедневно в указанное время (по Москве) все пользователи, кроме Админа, автоматически
          разлогиниваются при следующем действии в системе. Изменение применяется к новым входам —
          уже открытые сессии выйдут по старому времени, пока не перелогинятся.
        </p>
      </div>

      <div className="card settings-card">
        <h2 className="chart-title">Планировщик</h2>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={plannerAutoMatchEnabled}
            onChange={(event) => setPlannerAutoMatchEnabled(event.target.checked)}
          />
          Автоматически привязывать ЗН к записям планировщика
        </label>

        <div className="settings-field">
          <label htmlFor="planner-auto-match-interval">Проверять раз в (мин)</label>
          <input
            id="planner-auto-match-interval"
            type="number"
            min={1}
            value={plannerAutoMatchIntervalMinutes}
            onChange={(event) => setPlannerAutoMatchIntervalMinutes(event.target.value)}
          />
        </div>

        <p className="settings-description">
          Если в записи планировщика (Слесарный/Кузовной) ещё не указан заказ-наряд, система ищет
          среди недавно пришедших из 1С ЗН (с даты создания записи и не позже чем через 3 дня
          после) такой же номер телефона или VIN — и если находит, подставляет заказ-наряд, а
          пустые поля «Автомобиль»/«Клиент»/VIN/телефон заполняет из него. Уже заполненные вручную
          поля и уже привязанные к ЗН записи никогда не трогаются.
        </p>

        <button
          type="button"
          className="admin-btn"
          onClick={handleAutoMatchNow}
          disabled={autoMatchState === "running"}
        >
          {autoMatchState === "running" ? "Выполняется…" : "Выполнить сейчас"}
        </button>

        {autoMatchMessage && (
          <p className={autoMatchState === "error" ? "admin-form-error" : "settings-description"}>
            {autoMatchMessage}
          </p>
        )}

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={plannerSearchExcludeClosedOrders}
            onChange={(event) => setPlannerSearchExcludeClosedOrders(event.target.checked)}
          />
          Исключить Закрыт и Выполнен
        </label>

        <p className="settings-description">
          Не показывать в поиске заказ-наряда (по номеру, VIN и т.п.) при создании записи
          планировщика заказ-наряды в статусе «Закрыт» или «Выполнен» — привязывать новую запись к
          уже завершённому заказ-наряду незачем.
        </p>
      </div>

      <div className="card settings-card">
        <h2 className="chart-title">Интеграции</h2>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={fivesystemsApiEnabled}
            onChange={(event) => setFivesystemsApiEnabled(event.target.checked)}
          />
          Включить API
        </label>

        <p className="settings-description">
          Кнопка «Получить ЗН» в Планировщике — поиск ещё не выгруженного из 1С заказ-наряда
          напрямую по гос.номеру через API 5Systems. Если выключить — кнопка в Планировщике
          станет недоступна, независимо от того, введён гос.номер или нет.
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
