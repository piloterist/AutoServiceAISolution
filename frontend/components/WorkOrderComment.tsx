"use client";

import { useState } from "react";

import { invalidateWorkOrdersCache } from "@/lib/work-orders-cache";

/** Free-text staff note on the work order detail card (product ask,
 * 2026-10-06) - the one user-editable field on an otherwise read-only
 * (1C-imported) card. Saved explicitly via a button, not auto-saved on
 * blur, so a stray click-away never silently commits an unfinished edit. */
export function WorkOrderComment({
  workOrderId,
  initialComment,
}: {
  workOrderId: string;
  initialComment: string | null;
}) {
  const [comment, setComment] = useState(initialComment ?? "");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  const handleSave = async () => {
    setSaveState("saving");
    try {
      const res = await fetch(`/api/work-orders/${workOrderId}/comment`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: comment.trim() || null }),
      });
      if (!res.ok) throw new Error(await res.text());
      invalidateWorkOrdersCache();
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  };

  return (
    <div className="card">
      <h2 className="chart-title">Комментарий</h2>
      <textarea
        className="work-order-comment-input"
        rows={5}
        value={comment}
        onChange={(event) => {
          setComment(event.target.value);
          setSaveState("idle");
        }}
        placeholder="Заметка для себя - не выгружается в 1С"
        aria-label="Комментарий к заказ-наряду"
      />
      <div className="work-order-comment-footer">
        <button type="button" className="admin-btn" onClick={handleSave} disabled={saveState === "saving"}>
          {saveState === "saving" ? "Сохраняем…" : "Сохранить"}
        </button>
        {saveState === "saved" && <span className="settings-description">Сохранено</span>}
        {saveState === "error" && <span className="admin-form-error">Не удалось сохранить</span>}
      </div>
    </div>
  );
}
