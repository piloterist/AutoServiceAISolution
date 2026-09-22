"use client";

import { useEffect, useRef, useState } from "react";

import type { PlannerWorkOrder } from "@/lib/backend-api";
import { lookupWorkOrderByPlate, searchWorkOrders } from "@/lib/planner-client";

/** "Заказ-наряд" picker both Planner dialogs share (product brief: "выбор
 * из выпадающего списка, с возможностью начать писать в поле и тогда
 * выпадающий список отфильтровывается по вхождениям"). Selecting a result
 * calls onSelect with the full record so the dialog can autofill
 * Автомобиль/VIN/Клиент; typing without selecting just keeps `value` as
 * free text (the caller decides what that means - see the two dialogs). */
export function WorkOrderAutocomplete({
  value,
  onChange,
  onSelect,
}: {
  value: string;
  onChange: (text: string) => void;
  onSelect: (workOrder: PlannerWorkOrder) => void;
}) {
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<PlannerWorkOrder[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  // Fallback for today's own ЗН - the 1C export is now once a day (see
  // DEPLOYMENT.md), so a car that just arrived genuinely won't be in
  // `results` above yet. Collapsed by default so it doesn't clutter the
  // common case where the autocomplete above already finds the record.
  const [showPlateLookup, setShowPlateLookup] = useState(false);
  const [plate, setPlate] = useState("");
  const [plateLookupBusy, setPlateLookupBusy] = useState(false);
  const [plateLookupError, setPlateLookupError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || value.trim().length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      searchWorkOrders(value.trim())
        .then((found) => {
          if (!cancelled) setResults(found);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [value, open]);

  useEffect(() => {
    if (!open) return;
    const onOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onOutside);
    return () => document.removeEventListener("mousedown", onOutside);
  }, [open]);

  const runPlateLookup = async () => {
    if (!plate.trim()) return;
    setPlateLookupBusy(true);
    setPlateLookupError(null);
    try {
      const wo = await lookupWorkOrderByPlate(plate.trim());
      onSelect(wo);
      setShowPlateLookup(false);
      setPlate("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "";
      setPlateLookupError(
        message.includes("404")
          ? "Открытый заказ-наряд с таким гос.номером не найден"
          : message.includes("503")
            ? "Поиск по 5Systems сейчас отключён"
            : "Не удалось получить данные — попробуйте ещё раз или введите вручную",
      );
    } finally {
      setPlateLookupBusy(false);
    }
  };

  return (
    <div className="admin-form-field planner-autocomplete" ref={containerRef}>
      <label htmlFor="planner-wo-search">Заказ-наряд</label>
      <input
        id="planner-wo-search"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="Начните вводить номер, авто, клиента…"
        autoComplete="off"
      />
      {open && results.length > 0 && (
        <ul className="planner-autocomplete-list">
          {results.map((wo) => (
            <li key={wo.id}>
              <button
                type="button"
                onClick={() => {
                  onSelect(wo);
                  setOpen(false);
                }}
              >
                <span className="planner-autocomplete-number">{wo.external_number}</span>
                <span className="planner-autocomplete-detail">
                  {wo.vehicle_description ?? "—"} · {wo.customer_name ?? "—"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {!showPlateLookup ? (
        <button
          type="button"
          className="admin-btn-link planner-plate-lookup-toggle"
          onClick={() => setShowPlateLookup(true)}
        >
          Не нашли? Найти по гос.номеру
        </button>
      ) : (
        <div className="planner-plate-lookup">
          <input
            value={plate}
            onChange={(e) => setPlate(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                runPlateLookup();
              }
            }}
            placeholder="Гос.номер, например Х669МЕ777"
            autoComplete="off"
          />
          <button type="button" className="admin-btn" disabled={plateLookupBusy} onClick={runPlateLookup}>
            {plateLookupBusy ? "Ищем…" : "Получить ЗН"}
          </button>
          {plateLookupError && <p className="admin-form-error planner-plate-lookup-error">{plateLookupError}</p>}
        </div>
      )}
    </div>
  );
}
