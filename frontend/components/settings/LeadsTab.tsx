"use client";

import { useState } from "react";

import type { LeadsSettings } from "@/lib/backend-api";
import { leadsSettingsApi } from "@/lib/leads-client";

type SaveState = "idle" | "saving" | "saved" | "error";

export function LeadsTab({ initialSettings }: { initialSettings: LeadsSettings }) {
  const [enabled, setEnabled] = useState(initialSettings.enabled);
  const [staleAfterDays, setStaleAfterDays] = useState(String(initialSettings.stale_after_days));
  const [hasToken, setHasToken] = useState(initialSettings.has_intake_token);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  const [newToken, setNewToken] = useState<string | null>(null);
  const [tokenState, setTokenState] = useState<"idle" | "generating" | "error">("idle");
  const [tokenError, setTokenError] = useState<string | null>(null);

  const handleSave = async () => {
    const days = Number(staleAfterDays);
    if (!days || days <= 0) {
      setSaveState("error");
      setSaveError("Число дней должно быть больше нуля");
      setTimeout(() => setSaveState("idle"), 2500);
      return;
    }
    setSaveState("saving");
    setSaveError(null);
    try {
      await leadsSettingsApi.update({ enabled, stale_after_days: days });
      setSaveState("saved");
    } catch (err) {
      setSaveState("error");
      setSaveError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setTimeout(() => setSaveState("idle"), 2500);
    }
  };

  const handleRegenerateToken = async () => {
    setTokenState("generating");
    setTokenError(null);
    try {
      const result = await leadsSettingsApi.regenerateToken();
      setNewToken(result.intake_token);
      setHasToken(true);
      setTokenState("idle");
    } catch (err) {
      setTokenState("error");
      setTokenError(err instanceof Error ? err.message : "Не удалось сгенерировать токен");
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
    <div className="card telephony-connect-card">
      <h2 className="chart-title">Приём заявок с сайта</h2>
      <p className="settings-description">
        Заявки из форм pan-motors.ru (квизы, «Получить консультацию», «Рассрочка») - см. вкладку «Заявки» в
        верхнем меню. Заявка считается обработанной, если после неё был реальный дозвон нашим сотрудником на
        этот номер. Необработанные заявки старше указанного числа дней перестают считаться новыми, но
        остаются в истории.
      </p>

      <label className="settings-checkbox">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Принимать заявки с сайта
      </label>

      <div className="settings-field">
        <label htmlFor="leads-stale-days">Считать новой в течение (дней)</label>
        <input
          id="leads-stale-days"
          type="number"
          min={1}
          value={staleAfterDays}
          onChange={(e) => setStaleAfterDays(e.target.value)}
        />
      </div>

      {saveError && <p className="admin-form-error">{saveError}</p>}
      <button type="button" className="settings-save" onClick={handleSave} disabled={saveState === "saving"}>
        {saveLabel}
      </button>

      <div className="settings-field" style={{ marginTop: "1rem" }}>
        <label>Токен для сайта</label>
        <p className="settings-description">
          {hasToken ? "Токен настроен." : "Токен ещё не создан — заявки с сайта приниматься не будут."} При
          генерации нового токена старый перестаёт работать - сайт нужно будет обновить.
        </p>
        <div className="admin-form-actions">
          <button
            type="button"
            className="admin-btn"
            onClick={handleRegenerateToken}
            disabled={tokenState === "generating"}
          >
            {tokenState === "generating" ? "Генерация…" : hasToken ? "Сгенерировать новый токен" : "Создать токен"}
          </button>
        </div>
        {tokenError && <p className="admin-form-error">{tokenError}</p>}
        {newToken && (
          <div className="settings-field">
            <label htmlFor="leads-new-token">Новый токен (показывается один раз, сохраните его)</label>
            <input id="leads-new-token" type="text" readOnly value={newToken} onFocus={(e) => e.target.select()} />
          </div>
        )}
      </div>
    </div>
  );
}
