"use client";

import { useState } from "react";

import { DateInput } from "@/components/DateInput";
import { PHONE_SOURCE_GROUPS, ZEON_AUDIO_METHODS, ZEON_AUTH_MODES } from "@/lib/admin-constants";
import type { PhoneSource, TelephonySettings } from "@/lib/backend-api";
import { mskToday } from "@/lib/period";
import { phoneSourcesApi, telephonySettingsApi } from "@/lib/telephony-client";

import { AdminModal } from "./AdminModal";

type SaveState = "idle" | "saving" | "saved" | "error";

function ConnectionForm({ initialSettings }: { initialSettings: TelephonySettings }) {
  const [enabled, setEnabled] = useState(initialSettings.enabled);
  const [apiUrl, setApiUrl] = useState(initialSettings.zeon_api_url ?? "");
  const [apiKey, setApiKey] = useState(initialSettings.zeon_api_key ?? "");
  const [auth, setAuth] = useState(initialSettings.zeon_auth);
  const [operatorNames, setOperatorNames] = useState(initialSettings.operator_names ?? "");
  const [pollIntervalMinutes, setPollIntervalMinutes] = useState(
    initialSettings.poll_interval_minutes ? String(initialSettings.poll_interval_minutes) : "",
  );
  const [yandexToken, setYandexToken] = useState(initialSettings.yandex_disk_token ?? "");
  const [yandexBasePath, setYandexBasePath] = useState(initialSettings.yandex_disk_base_path ?? "");
  const [audioMethod, setAudioMethod] = useState(initialSettings.zeon_audio_method);
  const [ycApiKey, setYcApiKey] = useState(initialSettings.yc_api_key ?? "");
  const [ycFolderId, setYcFolderId] = useState(initialSettings.yc_folder_id ?? "");
  const [speechkitModel, setSpeechkitModel] = useState(initialSettings.speechkit_model);
  const [speechkitLanguage, setSpeechkitLanguage] = useState(initialSettings.speechkit_language);
  const [speechkitTimeoutMin, setSpeechkitTimeoutMin] = useState(String(initialSettings.speechkit_timeout_min));
  const [classifyCallsEnabled, setClassifyCallsEnabled] = useState(initialSettings.classify_calls_enabled);
  const [yandexgptModel, setYandexgptModel] = useState(initialSettings.yandexgpt_model);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  const [pingState, setPingState] = useState<"idle" | "checking" | "ok" | "error">("idle");
  const [pingError, setPingError] = useState<string | null>(null);

  const [importState, setImportState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [exportState, setExportState] = useState<"idle" | "running" | "started" | "error">("idle");
  const [exportMessage, setExportMessage] = useState<string | null>(null);

  // One shared period for both import actions below - the operator picks
  // it once, not per-button. Moscow's own calendar date (see
  // lib/period.ts's mskToday), not the browser's local date formatted as
  // UTC - those can disagree for up to 3h a day even when the browser's
  // own clock is set to Moscow time.
  const today = mskToday();
  const [periodStart, setPeriodStart] = useState(today);
  const [periodEnd, setPeriodEnd] = useState(today);

  const handleSave = async () => {
    setSaveState("saving");
    setSaveError(null);
    try {
      await telephonySettingsApi.update({
        enabled,
        zeon_api_url: apiUrl || null,
        zeon_api_key: apiKey || null,
        zeon_auth: auth,
        yandex_disk_token: yandexToken || null,
        yandex_disk_base_path: yandexBasePath || null,
        operator_names: operatorNames || null,
        poll_interval_minutes: pollIntervalMinutes ? Number(pollIntervalMinutes) : null,
        zeon_audio_method: audioMethod,
        yc_api_key: ycApiKey || null,
        yc_folder_id: ycFolderId || null,
        speechkit_model: speechkitModel,
        speechkit_language: speechkitLanguage,
        speechkit_timeout_min: Number(speechkitTimeoutMin) || 60,
        classify_calls_enabled: classifyCallsEnabled,
        yandexgpt_model: yandexgptModel,
      });
      setSaveState("saved");
    } catch (err) {
      setSaveState("error");
      setSaveError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setTimeout(() => setSaveState("idle"), 2500);
    }
  };

  const handlePing = async () => {
    setPingState("checking");
    setPingError(null);
    try {
      const result = await telephonySettingsApi.ping();
      if (result.ok) {
        setPingState("ok");
      } else {
        setPingState("error");
        setPingError(result.error ?? "Не удалось подключиться");
      }
    } catch (err) {
      setPingState("error");
      setPingError(err instanceof Error ? err.message : "Не удалось подключиться");
    } finally {
      setTimeout(() => setPingState("idle"), 4000);
    }
  };

  const handleImportStats = async () => {
    setImportState("running");
    setImportMessage(null);
    try {
      const result = await telephonySettingsApi.importNow({ startDate: periodStart, endDate: periodEnd });
      setImportState("done");
      setImportMessage(`Получено: ${result.fetched}, сохранено/обновлено: ${result.upserted}`);
    } catch (err) {
      setImportState("error");
      setImportMessage(err instanceof Error ? err.message : "Не удалось импортировать");
    }
  };

  const handleImportCalls = async () => {
    setExportState("running");
    setExportMessage(null);
    try {
      await telephonySettingsApi.exportRecordings({ startDate: periodStart, endDate: periodEnd });
      setExportState("started");
      setExportMessage(
        "Запущено в фоне — записи выгружаются из Zeon на Яндекс.Диск и расшифровываются. " +
          "Это может занять несколько минут; уже выгруженные/расшифрованные звонки не трогаются повторно.",
      );
    } catch (err) {
      setExportState("error");
      setExportMessage(err instanceof Error ? err.message : "Не удалось запустить выгрузку");
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
      <div className="telephony-connect-grid">
        <div className="telephony-connect-col">
          <h2 className="chart-title">Подключение ZEON</h2>

          <label className="settings-checkbox">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Включить автосбор статистики
          </label>

          <div className="settings-field">
            <label htmlFor="tel-api-url">API URL</label>
            <input
              id="tel-api-url"
              type="text"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder="https://z138.fpg.ru/zeon/api/v2/start.php"
            />
          </div>

          <div className="settings-field">
            <label htmlFor="tel-api-key">API ключ</label>
            <input
              id="tel-api-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              autoComplete="off"
            />
          </div>

          <div className="settings-field">
            <label htmlFor="tel-auth">Способ аутентификации</label>
            <select id="tel-auth" value={auth} onChange={(e) => setAuth(e.target.value as typeof auth)}>
              {ZEON_AUTH_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>
                  {mode.label}
                </option>
              ))}
            </select>
          </div>

          <div className="settings-field">
            <label htmlFor="tel-poll-interval">Как часто собирать (минут)</label>
            <input
              id="tel-poll-interval"
              type="number"
              min={1}
              value={pollIntervalMinutes}
              onChange={(e) => setPollIntervalMinutes(e.target.value)}
              placeholder="например, 5"
            />
          </div>

          <div className="settings-field">
            <label htmlFor="tel-operator-names">Имена операторов</label>
            <textarea
              id="tel-operator-names"
              value={operatorNames}
              onChange={(e) => setOperatorNames(e.target.value)}
              placeholder="302:Алексей,303:Мария"
              rows={2}
            />
          </div>

          <div className="admin-form-actions">
            <button type="button" className="admin-btn" onClick={handlePing} disabled={pingState === "checking"}>
              {pingState === "checking" ? "Проверка…" : "Проверить соединение"}
            </button>
          </div>
          {pingState === "ok" && <p className="settings-description">Соединение установлено ✓</p>}
          {pingState === "error" && <p className="admin-form-error">{pingError}</p>}
        </div>

        <div className="telephony-connect-col">
          <h2 className="chart-title">Подключение Yandex SpeechKit</h2>
          <p className="settings-description">
            Диск — для архива снимков статистики и хранения записей/расшифровок звонков. SpeechKit —
            для расшифровки записей разговоров.
          </p>

          <div className="settings-field">
            <label htmlFor="tel-yadisk-token">Яндекс.Диск токен</label>
            <input
              id="tel-yadisk-token"
              type="password"
              value={yandexToken}
              onChange={(e) => setYandexToken(e.target.value)}
              autoComplete="off"
            />
          </div>

          <div className="settings-field">
            <label htmlFor="tel-yadisk-path">Яндекс.Диск папка</label>
            <input
              id="tel-yadisk-path"
              type="text"
              value={yandexBasePath}
              onChange={(e) => setYandexBasePath(e.target.value)}
              placeholder="disk:/ZEON"
            />
          </div>

          <div className="settings-field">
            <label htmlFor="tel-audio-method">Метод скачивания записи</label>
            <select
              id="tel-audio-method"
              value={audioMethod}
              onChange={(e) => setAudioMethod(e.target.value as typeof audioMethod)}
            >
              {ZEON_AUDIO_METHODS.map((method) => (
                <option key={method.value} value={method.value}>
                  {method.label}
                </option>
              ))}
            </select>
          </div>

          <div className="settings-field">
            <label htmlFor="tel-yc-api-key">Yandex Cloud API-ключ</label>
            <input
              id="tel-yc-api-key"
              type="password"
              value={ycApiKey}
              onChange={(e) => setYcApiKey(e.target.value)}
              autoComplete="off"
            />
          </div>

          <div className="settings-field">
            <label htmlFor="tel-yc-folder-id">Yandex Cloud Folder ID</label>
            <input
              id="tel-yc-folder-id"
              type="text"
              value={ycFolderId}
              onChange={(e) => setYcFolderId(e.target.value)}
              placeholder="b1g..."
            />
          </div>

          <div className="settings-field">
            <label htmlFor="tel-speechkit-model">Модель распознавания</label>
            <input
              id="tel-speechkit-model"
              type="text"
              value={speechkitModel}
              onChange={(e) => setSpeechkitModel(e.target.value)}
              placeholder="general"
            />
          </div>

          <div className="settings-field">
            <label htmlFor="tel-speechkit-language">Язык</label>
            <input
              id="tel-speechkit-language"
              type="text"
              value={speechkitLanguage}
              onChange={(e) => setSpeechkitLanguage(e.target.value)}
              placeholder="ru-RU"
            />
          </div>

          <div className="settings-field">
            <label htmlFor="tel-speechkit-timeout">Таймаут расшифровки (мин)</label>
            <input
              id="tel-speechkit-timeout"
              type="number"
              min={1}
              value={speechkitTimeoutMin}
              onChange={(e) => setSpeechkitTimeoutMin(e.target.value)}
            />
          </div>

          <label className="settings-checkbox">
            <input
              type="checkbox"
              checked={classifyCallsEnabled}
              onChange={(e) => setClassifyCallsEnabled(e.target.checked)}
            />
            Определять тему звонка (YandexGPT)
          </label>
          <p className="settings-description">
            Раз в несколько минут отправляет готовую расшифровку отвеченного звонка в YandexGPT и
            помечает его темой «Кузовной» / «Слесарный» / «Не определено» — платный запрос
            дополнительно к SpeechKit, использует тот же аккаунт Yandex Cloud (ключ/Folder ID выше).
          </p>
          <div className="settings-field">
            <label htmlFor="tel-yandexgpt-model">Модель YandexGPT</label>
            <input
              id="tel-yandexgpt-model"
              type="text"
              value={yandexgptModel}
              onChange={(e) => setYandexgptModel(e.target.value)}
              placeholder="yandexgpt-lite/latest"
            />
          </div>
        </div>

        <div className="telephony-connect-col">
          <h2 className="chart-title">Импорт</h2>

          <div className="settings-field">
            <label htmlFor="tel-period-start">Период</label>
            <div className="admin-form-actions">
              <DateInput id="tel-period-start" value={periodStart} onChange={setPeriodStart} ariaLabel="Период с" />
              <DateInput value={periodEnd} onChange={setPeriodEnd} ariaLabel="Период по" />
            </div>
          </div>

          <div className="admin-form-actions">
            <button
              type="button"
              className="admin-btn admin-btn-primary"
              onClick={handleImportStats}
              disabled={importState === "running"}
            >
              {importState === "running" ? "Импорт…" : "Импортировать статистику"}
            </button>
          </div>
          {importMessage && (
            <p className={importState === "error" ? "admin-form-error" : "settings-description"}>{importMessage}</p>
          )}

          <div className="admin-form-actions">
            <button
              type="button"
              className="admin-btn admin-btn-primary"
              onClick={handleImportCalls}
              disabled={exportState === "running"}
            >
              {exportState === "running" ? "Запуск…" : "Импортировать звонки"}
            </button>
          </div>
          {exportMessage && (
            <p className={exportState === "error" ? "admin-form-error" : "settings-description"}>{exportMessage}</p>
          )}
          <p className="settings-description">
            «Импортировать статистику» — журнал звонков (кто/кому/когда звонил) для страницы «Телефония».
            «Импортировать звонки» — сами записи разговоров: скачивает их из Zeon, кладёт на Яндекс.Диск
            и расшифровывает через SpeechKit. Обе можно запускать за любой период сколько угодно раз —
            уже полученное повторно не трогается.
          </p>
        </div>
      </div>

      {saveError && <p className="admin-form-error">{saveError}</p>}
      <button type="button" className="settings-save" onClick={handleSave} disabled={saveState === "saving"}>
        {saveLabel}
      </button>
    </div>
  );
}

function SourcesTable({ initialSources }: { initialSources: PhoneSource[] }) {
  const [sources, setSources] = useState(initialSources);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<PhoneSource | "new" | null>(null);
  const [lineCode, setLineCode] = useState("");
  const [name, setName] = useState("");
  const [caption, setCaption] = useState("");
  const [groupName, setGroupName] = useState<(typeof PHONE_SOURCE_GROUPS)[number]>(PHONE_SOURCE_GROUPS[0]);
  const [sortOrder, setSortOrder] = useState("0");
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PhoneSource | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const selected = sources.find((s) => s.id === selectedId) ?? null;
  const toggleSelect = (source: PhoneSource) => setSelectedId((prev) => (prev === source.id ? null : source.id));

  const openNew = () => {
    setLineCode("");
    setName("");
    setCaption("");
    setGroupName(PHONE_SOURCE_GROUPS[0]);
    setSortOrder("0");
    setError(null);
    setEditing("new");
  };
  const openEdit = () => {
    if (!selected) return;
    setLineCode(selected.line_code);
    setName(selected.name);
    setCaption(selected.caption ?? "");
    setGroupName(selected.group_name as (typeof PHONE_SOURCE_GROUPS)[number]);
    setSortOrder(String(selected.sort_order));
    setError(null);
    setEditing(selected);
  };
  const close = () => setEditing(null);

  const save = async () => {
    if (!lineCode.trim() || !name.trim()) return setError("Заполните код линии и название");
    const payload = {
      line_code: lineCode.trim(),
      name: name.trim(),
      caption: caption.trim() || null,
      group_name: groupName,
      sort_order: Number(sortOrder) || 0,
    };
    try {
      if (editing === "new") {
        const created = await phoneSourcesApi.create(payload);
        setSources((prev) => [...prev, created]);
      } else if (editing) {
        const updated = await phoneSourcesApi.update(editing.id, payload);
        setSources((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      }
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    try {
      await phoneSourcesApi.remove(pendingDelete.id);
      setSources((prev) => prev.filter((s) => s.id !== pendingDelete.id));
      setSelectedId(null);
      setPendingDelete(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  return (
    <div className="card">
      <div className="admin-toolbar">
        <h2 className="chart-title">Источники (линии)</h2>
        <div className="admin-toolbar-actions">
          <button type="button" className="admin-btn" disabled={!selected} onClick={openEdit}>
            Изменить
          </button>
          <button
            type="button"
            className="admin-btn admin-btn-danger"
            disabled={!selected}
            onClick={() => {
              setDeleteError(null);
              if (selected) setPendingDelete(selected);
            }}
          >
            Удалить
          </button>
          <button type="button" className="admin-btn admin-btn-primary" onClick={openNew}>
            + Добавить
          </button>
        </div>
      </div>

      <table className="data-table admin-data-table">
        <thead>
          <tr>
            <th>Линия</th>
            <th>Название</th>
            <th>Подпись</th>
            <th>Группа</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((source) => (
            <tr
              key={source.id}
              className={source.id === selectedId ? "admin-row admin-row--selected" : "admin-row"}
              onClick={() => toggleSelect(source)}
            >
              <td>{source.line_code}</td>
              <td>{source.name}</td>
              <td>{source.caption ?? "—"}</td>
              <td>{source.group_name}</td>
            </tr>
          ))}
          {sources.length === 0 && (
            <tr>
              <td colSpan={4} className="admin-empty-row">
                Источников пока нет
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <AdminModal open={editing !== null} title={editing === "new" ? "Новый источник" : "Изменить источник"} onClose={close}>
        <div className="admin-form-field">
          <label htmlFor="src-line-code">Код линии</label>
          <input
            id="src-line-code"
            type="text"
            value={lineCode}
            onChange={(e) => setLineCode(e.target.value)}
            placeholder="pan, pan2, 79257111125…"
          />
        </div>
        <div className="admin-form-field">
          <label htmlFor="src-name">Название</label>
          <input id="src-name" type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="2GIS" />
        </div>
        <div className="admin-form-field">
          <label htmlFor="src-caption">Подпись</label>
          <input
            id="src-caption"
            type="text"
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            placeholder="IVR Yamaps"
          />
        </div>
        <div className="admin-form-field">
          <label htmlFor="src-group">Группа</label>
          <select
            id="src-group"
            value={groupName}
            onChange={(e) => setGroupName(e.target.value as (typeof PHONE_SOURCE_GROUPS)[number])}
          >
            {PHONE_SOURCE_GROUPS.map((group) => (
              <option key={group} value={group}>
                {group}
              </option>
            ))}
          </select>
        </div>
        <div className="admin-form-field">
          <label htmlFor="src-sort">Порядок</label>
          <input id="src-sort" type="number" value={sortOrder} onChange={(e) => setSortOrder(e.target.value)} />
        </div>

        {error && <p className="admin-form-error">{error}</p>}
        <div className="admin-form-actions">
          <span className="admin-form-actions-spacer" />
          <button type="button" className="admin-btn" onClick={close}>
            Отмена
          </button>
          <button type="button" className="admin-btn admin-btn-primary" onClick={save}>
            Сохранить
          </button>
        </div>
      </AdminModal>

      <AdminModal open={pendingDelete !== null} title="Удалить источник?" onClose={() => setPendingDelete(null)}>
        <p>Точно хотите удалить «{pendingDelete?.name}»?</p>
        {deleteError && <p className="admin-form-error">{deleteError}</p>}
        <div className="admin-form-actions">
          <span className="admin-form-actions-spacer" />
          <button type="button" className="admin-btn" onClick={() => setPendingDelete(null)}>
            Отмена
          </button>
          <button type="button" className="admin-btn admin-btn-danger" onClick={confirmDelete}>
            Удалить
          </button>
        </div>
      </AdminModal>
    </div>
  );
}

export function TelephonyTab({
  initialSettings,
  initialSources,
}: {
  initialSettings: TelephonySettings;
  initialSources: PhoneSource[];
}) {
  return (
    <>
      <ConnectionForm initialSettings={initialSettings} />
      <SourcesTable initialSources={initialSources} />
    </>
  );
}
