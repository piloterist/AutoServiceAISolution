"use client";

import { useEffect, useRef, useState } from "react";

import type { PlannerWorkOrder } from "@/lib/backend-api";
import { searchWorkOrders } from "@/lib/planner-client";

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
    </div>
  );
}
