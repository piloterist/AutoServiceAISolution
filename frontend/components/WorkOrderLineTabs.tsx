"use client";

import { useState } from "react";

import type { WorkOrderLaborLineItem, WorkOrderPartLineItem } from "@/lib/backend-api";

function formatMoney(value: string | null): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value)) + " ₽";
}

function formatQuantity(value: string | null): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 }).format(Number(value));
}

type Tab = "labor" | "parts";

export function WorkOrderLineTabs({
  labor,
  parts,
}: {
  labor: WorkOrderLaborLineItem[];
  parts: WorkOrderPartLineItem[];
}) {
  const [tab, setTab] = useState<Tab>("labor");

  return (
    <div>
      <div className="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "labor"}
          className={tab === "labor" ? "tab tab-active" : "tab"}
          onClick={() => setTab("labor")}
        >
          Работы ({labor.length})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "parts"}
          className={tab === "parts" ? "tab tab-active" : "tab"}
          onClick={() => setTab("parts")}
        >
          Товары ({parts.length})
        </button>
      </div>

      {tab === "labor" && (
        <div className="table-wrap">
          <table className="data-table data-table--labor">
            <thead>
              <tr>
                <th>Работа</th>
                <th className="num">Цена</th>
                <th className="num">Сумма</th>
              </tr>
            </thead>
            <tbody>
              {labor.map((line, index) => (
                <tr key={index}>
                  <td>{line.operation_name || "—"}</td>
                  <td className="num">{formatMoney(line.price)}</td>
                  <td className="num">{formatMoney(line.amount)}</td>
                </tr>
              ))}
              {labor.length === 0 && (
                <tr>
                  <td colSpan={3} className="table-empty">
                    Нет строк по работам.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === "parts" && (
        <div className="table-wrap">
          <table className="data-table data-table--parts">
            <thead>
              <tr>
                <th>Номенклатура</th>
                <th className="num">Количество</th>
                <th className="num">Цена</th>
                <th className="num">Сумма</th>
              </tr>
            </thead>
            <tbody>
              {parts.map((line, index) => (
                <tr key={index}>
                  <td>{line.item_name || "—"}</td>
                  <td className="num">{formatQuantity(line.quantity)}</td>
                  <td className="num">{formatMoney(line.price)}</td>
                  <td className="num">{formatMoney(line.amount)}</td>
                </tr>
              ))}
              {parts.length === 0 && (
                <tr>
                  <td colSpan={4} className="table-empty">
                    Нет строк по товарам.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
