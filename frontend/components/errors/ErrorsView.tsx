"use client";

import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import type { BayIssue, OverdueRequest, OverdueRequestsResponse } from "@/lib/backend-api";
import { eventSnapshotUrl } from "@/lib/bays-client";
import { ERRORS_CHANGED_EVENT } from "@/lib/errors-badge";

const SHOP_TZ = "Europe/Moscow";
const REFRESH_MS = 30_000;

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    timeZone: SHOP_TZ,
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", { timeZone: SHOP_TZ, day: "2-digit", month: "2-digit" });
}

// "9991234567" -> "+7 999 123-45-67" (как в планировщике).
function formatPhone(phone: string | null): string {
  const digits = (phone ?? "").replace(/\D/g, "").slice(-10);
  if (digits.length !== 10) return phone ?? "";
  return `+7 ${digits.slice(0, 3)} ${digits.slice(3, 6)}-${digits.slice(6, 8)}-${digits.slice(8, 10)}`;
}

// Подписи видов ошибок видеоконтроля. Текст самой ошибки (message) приходит с бэкенда готовым;
// новый вид без подписи здесь показывается без ярлыка, а не ломает лист.
const ISSUE_KIND_LABEL: Record<string, string> = {
  no_work_order: "Нет заказ-наряда",
  no_body_plan: "Нет в плане кузовного",
  exit_without_entry: "Выезд без въезда",
  import_stale: "Нет данных из 1С",
};

function IssueHead({ issue }: { issue: BayIssue }) {
  const kindLabel = ISSUE_KIND_LABEL[issue.kind];
  if (issue.kind === "import_stale") {
    // Не про машину и бокс: ошибка выгрузки из 1С.
    return (
      <>
        <div className="errors-title">
          Выгрузка из 1С<span className="gate-flag gate-flag--down"> {kindLabel}</span>
        </div>
        <div className="errors-sub">с {formatDateTime(issue.occurred_at)}</div>
      </>
    );
  }
  return (
    <>
      <div className="errors-title">
        {issue.plate ?? "Номер не распознан"} · {issue.bay_name}
        {kindLabel ? <span className="gate-flag gate-flag--down"> {kindLabel}</span> : null}
      </div>
      <div className="errors-sub">
        {issue.workshop_label} · {issue.kind === "exit_without_entry" ? "выехала" : "заехала"}{" "}
        {formatDateTime(issue.occurred_at)}
      </div>
    </>
  );
}

/** Лист «Ошибки» (product ask, 2026-11-05): каждая машина в боксе должна быть с заказ-нарядом;
 * у ворот кузовного - с записью в плане (2026-11-19: «нет в плане», «выезд без въезда»).
 * Нет заказ-наряда - здесь появляется ошибка; управляющий оформляет заказ-наряд (ошибка
 * закроется сама) или отмечает «Исправлено». Исправленные уходят вниз серыми. */
export function ErrorsView({ initialIssues }: { initialIssues: BayIssue[] }) {
  const [issues, setIssues] = useState(initialIssues);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  // Просроченные звонки по заявкам на ремонт (все цеха): не хранятся, а вычисляются, поэтому
  // сами исчезают из списка, как только дозвонились, создан заказ-наряд или заявку дисквалифицировали.
  const [requests, setRequests] = useState<OverdueRequest[]>([]);
  const [requestsError, setRequestsError] = useState<string | null>(null);
  // Контроль заявок выключен в настройках - раздела про просроченные заявки нет совсем.
  // Пока ответа нет, раздел скрыт (чтобы не мигал у тех, у кого контроль выключен).
  const [requestControlEnabled, setRequestControlEnabled] = useState(false);

  const reloadRequests = useCallback(async () => {
    try {
      const res = await fetch("/api/repair-requests/overdue?scope=all", { cache: "no-store" });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = (await res.json()) as OverdueRequestsResponse;
      setRequestControlEnabled(data.enabled);
      setRequests(data.items);
      setRequestsError(null);
    } catch {
      setRequestsError("Не удалось обновить просроченные заявки");
    }
  }, []);

  useEffect(() => {
    void reloadRequests();
    const timer = setInterval(reloadRequests, REFRESH_MS);
    return () => clearInterval(timer);
  }, [reloadRequests]);

  const reload = useCallback(async () => {
    try {
      const res = await fetch("/api/errors", { cache: "no-store" });
      if (!res.ok) throw new Error(`${res.status}`);
      setIssues(((await res.json()) as { issues: BayIssue[] }).issues);
      setError(null);
    } catch {
      setError("Не удалось обновить список");
    }
  }, []);

  useEffect(() => {
    const timer = setInterval(reload, REFRESH_MS);
    return () => clearInterval(timer);
  }, [reload]);

  const resolve = async (issue: BayIssue) => {
    const note = window.prompt("Что сделано? (можно оставить пустым)", "");
    if (note === null) return;
    setBusyId(issue.id);
    try {
      const res = await fetch(`/api/errors/${issue.id}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      setIssues(((await res.json()) as { issues: BayIssue[] }).issues);
      setError(null);
      window.dispatchEvent(new Event(ERRORS_CHANGED_EVENT)); // вкладка «Ошибки» перекрасится сразу
    } catch {
      setError("Не удалось отметить ошибку исправленной");
    } finally {
      setBusyId(null);
    }
  };

  const open = issues.filter((i) => !i.resolved_at);
  const resolved = issues.filter((i) => i.resolved_at);

  return (
    <div className="card errors-page">
      <h1 className="planner-title">Ошибки</h1>
      <p className="errors-hint">
        Машина стоит в боксе, а заказ-наряда по её номеру нет. Оформите заказ-наряд в 1С (ошибка закроется сама) или
        нажмите «Исправлено».
      </p>
      {error && <p className="errors-fail">{error}</p>}

      {requestControlEnabled && (
        <>
          <h2 className="errors-subtitle">Заявки без звонка клиенту</h2>
          <p className="errors-hint">
            Первый или второй звонок по заявке на ремонт просрочен (сроки и правила - в Настройках, «Контроль заявок»).
            Ошибка закроется сама, когда дозвонились, создан заказ-наряд или заявку дисквалифицировали.
          </p>
          {requestsError && <p className="errors-fail">{requestsError}</p>}
          {requests.length === 0 ? (
            <p className="errors-empty">Просроченных заявок нет.</p>
          ) : (
            <ul className="errors-list">
              {requests.map((request) => (
                <li key={request.id} className="errors-item errors-item--open">
                  <div className="errors-body">
                    <div className="errors-title">
                      <Link className="errors-request-link" href={`/work-orders/${request.id}`}>
                        {request.external_number}
                      </Link>
                      {request.customer_name ? ` — ${request.customer_name}` : ""}
                    </div>
                    <div className="errors-sub">
                      {[formatPhone(request.phone), request.vehicle_description, request.department]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                    <div>
                      {request.overdue === "first" ? "Просрочен первый звонок" : "Просрочен второй звонок"}: срок был{" "}
                      {formatDay(request.deadline)}, заявка от {formatDay(request.created_at)}, попыток{" "}
                      {request.attempts_count}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <h2 className="errors-subtitle">Видеоконтроль: боксы и ворота</h2>
      {open.length === 0 ? (
        <p className="errors-empty">Неисправленных ошибок нет.</p>
      ) : (
        <ul className="errors-list">
          {open.map((issue) => (
            <li key={issue.id} className="errors-item errors-item--open">
              {issue.entry_event_id && (
                // eslint-disable-next-line @next/next/no-img-element
                <img className="errors-photo" src={eventSnapshotUrl(issue.entry_event_id)} alt="Кадр въезда" loading="lazy" />
              )}
              <div className="errors-body">
                <IssueHead issue={issue} />
                <div>{issue.message}</div>
              </div>
              <button type="button" className="admin-btn" disabled={busyId === issue.id} onClick={() => resolve(issue)}>
                Исправлено
              </button>
            </li>
          ))}
        </ul>
      )}

      {resolved.length > 0 && (
        <>
          <h2 className="errors-subtitle">Исправленные</h2>
          <ul className="errors-list">
            {resolved.map((issue) => (
              <li key={issue.id} className="errors-item errors-item--resolved">
                <div className="errors-body">
                  <IssueHead issue={issue} />
                  <div className="errors-sub">
                    Исправлена {issue.resolved_at ? formatDateTime(issue.resolved_at) : ""}
                    {issue.resolution === "auto" ? " автоматически" : issue.resolved_by ? `: ${issue.resolved_by}` : ""}
                    {issue.resolution_note ? ` — ${issue.resolution_note}` : ""}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
