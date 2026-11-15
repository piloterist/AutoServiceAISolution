"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { OverdueRequest, OverdueRequestsResponse } from "@/lib/backend-api";

const POLL_INTERVAL_MS = 60_000;
const SHOP_TZ = "Europe/Moscow";
const LIST_URL = "/work-orders?request_issues=1";

function listUrl(workshopId: string | null): string {
  return workshopId ? `${LIST_URL}&workshop_id=${workshopId}` : LIST_URL;
}

// "9991234567" -> "+7 999 123-45-67" - same as MissedCallsBadge.tsx / LeadsBadge.tsx.
function formatPhone(phone: string | null): string {
  const digits = (phone ?? "").replace(/\D/g, "").slice(-10);
  if (digits.length !== 10) return phone ?? "";
  return `+7 ${digits.slice(0, 3)} ${digits.slice(3, 6)}-${digits.slice(6, 8)}-${digits.slice(8, 10)}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", { timeZone: SHOP_TZ, day: "2-digit", month: "2-digit" });
}

function overdueLabel(request: OverdueRequest): string {
  return request.overdue === "first" ? "просрочен 1-й звонок" : "просрочен 2-й звонок";
}

async function fetchOverdue(workshopId: string | null): Promise<OverdueRequestsResponse> {
  const query = workshopId ? `?workshop_id=${workshopId}` : "";
  const res = await fetch(`/api/repair-requests/overdue${query}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return (await res.json()) as OverdueRequestsResponse;
}

/** Колокольчик контроля заявок рядом с трубкой и конвертом в правом верхнем углу планировщика
 * (product ask, 2026-11-06): красная цифра - сколько заявок цеха пользователя просрочили звонок
 * клиенту (backend services/request_control_service.py), клик ведёт в список заказ-нарядов,
 * отфильтрованный по таким заявкам. Цифра не гасится руками: заявка уходит из неё, когда
 * дозвонились, появился заказ-наряд или её дисквалифицировали.
 *
 * Желтое окно с восклицательным знаком выскакивает по центру при каждом открытии планировщика
 * и затем каждые N минут (Настройки -> Общие -> «Контроль заявок»), пока просроченные есть. */
export function RequestsBell({ workshopId }: { workshopId: string | null }) {
  const router = useRouter();
  const [data, setData] = useState<OverdueRequestsResponse | null>(null);
  const [popupOpen, setPopupOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const shownFor = useRef<Set<string>>(new Set());
  const workshopKey = workshopId ?? "";
  const intervalMinutes = data?.popup_interval_minutes ?? null;

  const load = useCallback(async (): Promise<OverdueRequestsResponse | null> => {
    try {
      const next = await fetchOverdue(workshopId);
      setData(next);
      return next;
    } catch {
      return null; // следующий опрос попробует ещё раз; колокольчик остаётся с прежней цифрой
    }
  }, [workshopId]);

  // Опрос раз в минуту; первое окно - сразу после первой загрузки (то есть при открытии планировщика
  // этого цеха; при переключении цеха данные и окно относятся уже к новому цеху).
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setPopupOpen(false);
    void load().then((first) => {
      if (cancelled || !first || !first.enabled || !first.popup_enabled || first.items.length === 0) return;
      if (shownFor.current.has(workshopKey)) return;
      shownFor.current.add(workshopKey);
      setPopupOpen(true);
    });
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [load, workshopKey]);

  // Повторные напоминания - с периодом из настроек, по свежим данным.
  useEffect(() => {
    if (!intervalMinutes) return;
    const timer = setInterval(
      () => {
        void load().then((fresh) => {
          if (fresh && fresh.enabled && fresh.popup_enabled && fresh.items.length > 0) setPopupOpen(true);
        });
      },
      intervalMinutes * 60_000,
    );
    return () => clearInterval(timer);
  }, [intervalMinutes, load]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (popupOpen && !dialog.open) dialog.showModal();
    if (!popupOpen && dialog.open) dialog.close();
  }, [popupOpen]);

  const count = data?.items.length ?? 0;
  if (data && !data.enabled) return null; // контроль выключен в настройках - значка нет

  return (
    <>
      <button
        type="button"
        className="requests-bell-btn"
        onClick={() => router.push(listUrl(workshopId))}
        aria-label={count > 0 ? `Заявки с просроченным звонком: ${count}` : "Просроченных заявок нет"}
        title={count > 0 ? "Заявки с просроченным звонком" : "Просроченных заявок нет"}
      >
        <svg viewBox="0 0 24 24" width={40} height={40} aria-hidden="true">
          <path
            d="M12 2a1.5 1.5 0 0 0-1.5 1.5v.7A6.5 6.5 0 0 0 5.5 10.5V15l-1.7 2.3a.8.8 0 0 0 .6 1.2h15.2a.8.8 0 0 0 .6-1.2L18.5 15v-4.5a6.5 6.5 0 0 0-5-6.3v-.7A1.5 1.5 0 0 0 12 2Zm-2.2 17a2.2 2.2 0 0 0 4.4 0H9.8Z"
            fill="currentColor"
          />
        </svg>
        {count > 0 && <span className="requests-bell-count">{count}</span>}
      </button>

      <dialog
        ref={dialogRef}
        className="requests-popup"
        onClose={() => setPopupOpen(false)}
        aria-label="Просроченные звонки по заявкам"
      >
        <div className="requests-popup-head">
          <span className="requests-popup-mark" aria-hidden="true">
            !
          </span>
          <div>
            <div className="requests-popup-title">Заявки без звонка клиенту</div>
            <div className="requests-popup-sub">
              Нужно связаться с клиентом: первый и второй разговор проводятся в сроки, заказ-наряд по заявке пока не создан.
            </div>
          </div>
        </div>
        <ul className="requests-popup-list">
          {(data?.items ?? []).map((request) => (
            <li key={request.id}>
              <button
                type="button"
                className="requests-popup-row"
                onClick={() => {
                  setPopupOpen(false);
                  router.push(`/work-orders/${request.id}`);
                }}
              >
                <span className="requests-popup-row-main">
                  {request.external_number}
                  {request.customer_name && ` — ${request.customer_name}`}
                </span>
                <span className="requests-popup-row-meta">
                  {[formatPhone(request.phone), request.vehicle_description].filter(Boolean).join(" · ")}
                </span>
                <span className="requests-popup-row-late">
                  {overdueLabel(request)} · заявка от {formatDate(request.created_at)}
                  {request.department ? ` · ${request.department}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <div className="requests-popup-actions">
          <button
            type="button"
            className="admin-btn admin-btn-primary"
            onClick={() => {
              setPopupOpen(false);
              router.push(listUrl(workshopId));
            }}
          >
            Открыть список
          </button>
          <button type="button" className="admin-btn" onClick={() => setPopupOpen(false)}>
            Понятно
          </button>
        </div>
      </dialog>
    </>
  );
}
