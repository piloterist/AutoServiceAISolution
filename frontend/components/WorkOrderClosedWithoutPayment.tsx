"use client";

import { useState } from "react";

import { invalidateWorkOrdersCache } from "@/lib/work-orders-cache";

/** "Закрыть без оплат" checkbox on the work order detail card (product ask,
 * 2026-10-07): some work orders are closed by an off-system arrangement and
 * will never actually get paid, which was inflating ДЗ (receivables) with
 * debt that's never coming. Settable only by the Админ role - every other
 * role sees the current state but can't change it (the save route itself
 * is also Админ-gated, see app/api/work-orders/[id]/closed-without-payment,
 * middleware.ts - `canEdit` here is a UI convenience, not the real guard). */
export function WorkOrderClosedWithoutPayment({
  workOrderId,
  initialValue,
  canEdit,
}: {
  workOrderId: string;
  initialValue: boolean;
  canEdit: boolean;
}) {
  const [checked, setChecked] = useState(initialValue);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const next = event.target.checked;
    setChecked(next);
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`/api/work-orders/${workOrderId}/closed-without-payment`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ closed_without_payment: next }),
      });
      if (!res.ok) throw new Error(await res.text());
      invalidateWorkOrdersCache();
    } catch {
      setChecked(!next);
      setError("Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="detail-field">
      <span className="detail-label">Закрыть без оплат</span>
      <label className="closed-without-payment-label">
        <input
          type="checkbox"
          checked={checked}
          disabled={!canEdit || saving}
          onChange={handleChange}
          aria-label="Закрыть без оплат - исключить из дебиторской задолженности"
        />
        {!canEdit && <span className="settings-description">Изменяет только роль «Админ»</span>}
      </label>
      {error && <span className="admin-form-error">{error}</span>}
    </div>
  );
}
