"use client";

import { useState } from "react";

import { AdminModal } from "@/components/settings/AdminModal";
import type { ExpensesImportReport } from "@/lib/backend-api";

const MONTH_NAMES = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];

function money(value: string): string {
  return Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 2 }) + " ₽";
}

/** Импорт расходов из файла отчёта (.xlsm/.xlsx): the user picks the month
 * (and year) to load into, the file is checked first (what will be loaded, the
 * new cost items, unmatched workshops), then loaded on confirmation. */
export function ExpensesImportDialog({
  defaultYear,
  defaultMonth,
  onClose,
  onImported,
}: {
  defaultYear: number;
  defaultMonth: number;
  onClose: () => void;
  onImported: (year: number) => void;
}) {
  const [year, setYear] = useState(defaultYear);
  const [month, setMonth] = useState(defaultMonth);
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ExpensesImportReport | null>(null);
  const [loaded, setLoaded] = useState<ExpensesImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (dryRun: boolean): Promise<ExpensesImportReport | null> => {
    if (!file) return null;
    const form = new FormData();
    form.set("file", file);
    form.set("year", String(year));
    form.set("month", String(month));
    form.set("dry_run", String(dryRun));
    const res = await fetch("/api/expenses/import", { method: "POST", body: form });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.error === "string" ? body.error : "Не удалось загрузить файл");
    return body as ExpensesImportReport;
  };

  const check = async () => {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      setReport(await send(true));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось проверить файл");
    } finally {
      setBusy(false);
    }
  };

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await send(false);
      setLoaded(result);
      onImported(year); // the table behind refreshes; this window stays to show the result
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить");
    } finally {
      setBusy(false);
    }
  };

  const changed = () => setReport(null); // any change of month/file needs a fresh check

  return (
    <AdminModal open title="Импорт расходов из файла" onClose={onClose} wide>
      {loaded ? (
        <div className="expenses-import-report">
          <p>
            Загружено: <strong>{loaded.cells}</strong> значений на сумму <strong>{money(loaded.total)}</strong> —{" "}
            {MONTH_NAMES[loaded.month - 1]} {loaded.year}.
          </p>
          {loaded.missing_items.length > 0 && (
            <p className="admin-form-error">
              Не загружены, так как статей нет в справочнике: <strong>{loaded.missing_items.join(", ")}</strong>.
              Добавьте их в Настройки → Финансы и повторите импорт.
            </p>
          )}
          {loaded.skipped_inactive.length > 0 && (
            <p>Пропущены неактивные статьи: {loaded.skipped_inactive.join(", ")}</p>
          )}
          {loaded.warnings.map((w) => (
            <p key={w} className="admin-form-error">
              {w}
            </p>
          ))}
        </div>
      ) : (
        <>
      <div className="admin-form-field">
        <label htmlFor="import-month">В какой месяц загрузить</label>
        <div className="expenses-import-period">
          <select
            id="import-month"
            value={month}
            onChange={(e) => {
              setMonth(Number(e.target.value));
              changed();
            }}
          >
            {MONTH_NAMES.map((name, idx) => (
              <option key={name} value={idx + 1}>
                {name}
              </option>
            ))}
          </select>
          <input
            type="number"
            aria-label="Год"
            value={year}
            min={2000}
            max={2100}
            onChange={(e) => {
              setYear(Number(e.target.value));
              changed();
            }}
          />
        </div>
      </div>

      <div className="admin-form-field">
        <label htmlFor="import-file">Файл (.xlsm или .xlsx)</label>
        <input
          id="import-file"
          type="file"
          accept=".xlsm,.xlsx"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            changed();
          }}
        />
        <span className="settings-description">
          Значения загруженных статей в этом месяце будут заменены; статьи, которых нет в файле, не
          трогаются. Статьи из файла, которых нет в справочнике, загружены не будут (о них
          предупредим).
        </span>
      </div>

      {report && (
        <div className="expenses-import-report">
          <p>
            Лист «{report.sheet}»: будет загружено <strong>{report.cells}</strong> значений по{" "}
            <strong>{report.rows}</strong> статьям на сумму <strong>{money(report.total)}</strong> —{" "}
            {MONTH_NAMES[report.month - 1]} {report.year}.
          </p>
          <ul>
            {report.workshops.map((w) => (
              <li key={w.file_label}>
                {w.file_label} → {w.workshop ?? "не сопоставлен, будет пропущен"}
              </li>
            ))}
          </ul>
          {report.missing_items.length > 0 && (
            <p className="admin-form-error">
              Статей нет в справочнике, они НЕ будут загружены: {report.missing_items.join(", ")}
            </p>
          )}
          {report.skipped_inactive.length > 0 && (
            <p>Неактивные статьи, будут пропущены: {report.skipped_inactive.join(", ")}</p>
          )}
          {report.warnings.map((w) => (
            <p key={w} className="admin-form-error">
              {w}
            </p>
          ))}
        </div>
      )}

        </>
      )}

      {error && <p className="admin-form-error">{error}</p>}

      <div className="admin-form-actions">
        <span className="admin-form-actions-spacer" />
        {loaded ? (
          <button type="button" className="admin-btn admin-btn-primary" onClick={onClose}>
            Закрыть
          </button>
        ) : (
          <>
        <button type="button" className="admin-btn" onClick={onClose}>
          Отмена
        </button>
        <button type="button" className="admin-btn" disabled={!file || busy} onClick={() => void check()}>
          Проверить файл
        </button>
        <button
          type="button"
          className="admin-btn admin-btn-primary"
          disabled={!report || report.cells === 0 || busy}
          onClick={() => void load()}
        >
          {busy ? "Загрузка…" : "Загрузить"}
        </button>
          </>
        )}
      </div>
    </AdminModal>
  );
}
