"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { CrmTaskOverdueCount } from "@/lib/backend-api";

const POLL_INTERVAL_MS = 60_000;

/** Текстовая кнопка «Задачи CRM» (доска задач) слева от трубки в шапке планировщика (product ask, 2026-11-15) со счётчиком:
 * сколько телефонов цеха, выбранного в планировщике, висят в «На контроле» дольше розового срока
 * (Настройки -> Общие; красные входят в счёт). Клик открывает доску CRM на этом же цехе. */
export function TaskBoardBadge({ workshopId }: { workshopId: string | null }) {
  const router = useRouter();
  const [count, setCount] = useState(0);
  const [warnDays, setWarnDays] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setCount(0);

    const load = async () => {
      try {
        const query = workshopId ? `?workshop_id=${workshopId}` : "";
        const res = await fetch(`/api/crm-tasks/overdue-count${query}`, { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as CrmTaskOverdueCount;
        if (cancelled) return;
        setCount(data.count);
        setWarnDays(data.warn_days);
      } catch {
        // next poll tries again; the badge keeps its last number
      }
    };

    void load();
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [workshopId]);

  const title =
    count > 0
      ? `Задачи CRM: ${count} на контроле дольше ${warnDays ?? ""} дн.`
      : "Задачи CRM";

  return (
    <button
      type="button"
      className="task-board-badge-btn"
      onClick={() =>
        router.push(`/telephony?tab=board${workshopId ? `&workshop=${encodeURIComponent(workshopId)}` : ""}`)
      }
      aria-label={title}
      title={title}
    >
      <span className="task-board-badge-label">Задачи CRM</span>
      {count > 0 && <span className="task-board-badge-count">{count}</span>}
    </button>
  );
}
