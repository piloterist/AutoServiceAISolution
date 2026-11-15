"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { RequestControl } from "@/lib/backend-api";
import { invalidateWorkOrdersCache } from "@/lib/work-orders-cache";

const SHOP_TZ = "Europe/Moscow";

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

function formatTalk(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes} мин ${String(seconds % 60).padStart(2, "0")} с` : `${seconds} с`;
}

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { error?: string };
    if (body.error) return body.error;
  } catch {
    // not JSON
  }
  return `Не удалось выполнить (${res.status})`;
}

// Номера из сырого текста 1С (бывает несколько через , ; /) -> последние 10 цифр каждого.
function phoneDigits(raw: string | null): string[] {
  return (raw ?? "")
    .split(/[,;/]/)
    .map((part) => part.replace(/\D/g, "").slice(-10))
    .filter((digits) => digits.length === 10);
}

// "YYYY-MM-DD HH:MM:SS" по Москве - в таком виде время звонков приходит из телефонии.
function mskLocal(iso: string): string {
  return new Date(iso).toLocaleString("sv-SE", { timeZone: SHOP_TZ });
}

function statusLabel(control: RequestControl): string {
  switch (control.status) {
    case "converted":
      return "Заказ-наряд создан";
    case "disqualified":
      return "Дисквалифицирована";
    case "expired":
      return "Устарела (дисквалифицирована автоматически)";
    default:
      return "Открыта";
  }
}

/** Контроль звонков по заявке на ремонт (product ask, 2026-11-06; backend
 * services/request_control_service.py): сколько попыток связаться с клиентом уже есть (разговоры
 * из телефонии и ручные отметки), сроки первого и второго звонка, а также ручные действия -
 * «Отметить попытку» (комментарий обязателен) и «Дисквалифицировать» (после двух попыток; без них
 * - только роли с правом «Дисквалификация заявок без попыток»). Не показывается, пока контроль
 * выключен в настройках. */
export function RequestControlCard({ requestId, phone }: { requestId: string; phone: string | null }) {
  const [control, setControl] = useState<RequestControl | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"idle" | "attempt" | "disqualify">("idle");
  const [attemptComment, setAttemptComment] = useState("");
  const [reason, setReason] = useState("");
  const [reasonComment, setReasonComment] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/repair-requests/${requestId}/control`, { cache: "no-store" });
      if (!res.ok) throw new Error(await readError(res));
      setControl((await res.json()) as RequestControl);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить контроль заявки");
    }
  }, [requestId]);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async (kind: "attempts" | "disqualify", body: Record<string, unknown>) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/repair-requests/${requestId}/${kind}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await readError(res));
      setControl((await res.json()) as RequestControl);
      invalidateWorkOrdersCache(); // список заказ-нарядов подхватит новый статус
      setMode("idle");
      setAttemptComment("");
      setReason("");
      setReasonComment("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось выполнить");
    } finally {
      setBusy(false);
    }
  };

  if (!control) {
    return error ? (
      <div className="card request-control">
        <p className="request-control-error">{error}</p>
      </div>
    ) : null;
  }
  if (!control.control_enabled) return null;

  const isOpen = control.status === "open";
  const phones = phoneDigits(phone);
  const callsHref =
    phones.length > 0
      ? `/telephony?${new URLSearchParams({ phone: phones.join(","), since: mskLocal(control.created_at) })}`
      : null;
  return (
    <div className="card request-control">
      <div className="request-control-head">
        <h2 className="chart-title">Контроль звонков по заявке</h2>
        <span className="request-control-badge">{statusLabel(control)}</span>
        {control.overdue && (
          <span className="request-control-badge request-control-badge--late">
            {control.overdue === "first" ? "просрочен первый звонок" : "просрочен второй звонок"}
          </span>
        )}
        {isOpen && !control.overdue && <span className="request-control-badge request-control-badge--ok">в сроке</span>}
      </div>

      {control.status === "disqualified" && (
        <p className="request-control-note">
          {control.disqualify_reason}
          {control.disqualify_comment ? ` — ${control.disqualify_comment}` : ""}
          {control.disqualified_by ? `. ${control.disqualified_by}` : ""}
          {control.disqualified_at ? `, ${formatDateTime(control.disqualified_at)}` : ""}
        </p>
      )}

      <p className="request-control-note">
        Состоявшихся попыток: {control.attempts_count} из {control.attempts_required}. Срок первого звонка:{" "}
        {formatDay(control.first_deadline)}, второго: {formatDay(control.second_deadline)}.
        {control.missed_calls > 0 &&
          ` Исходящих без разговора: ${control.missed_calls} (попыткой не считаются: разговор от ${control.min_talk_sec} с).`}
      </p>

      {control.attempts.length > 0 && (
        <ul className="request-control-attempts">
          {control.attempts.map((attempt, index) => (
            <li key={`${attempt.at}-${index}`} className="request-control-attempt">
              {attempt.kind === "call" ? (
                <>
                  Звонок клиенту, разговор {formatTalk(attempt.talk_sec ?? 0)}
                  {attempt.operator ? `, доб. ${attempt.operator}` : ""}
                </>
              ) : (
                <>Отметка вручную: {attempt.comment}</>
              )}
              <div className="request-control-attempt-meta">
                {formatDateTime(attempt.at)}
                {attempt.kind === "manual" && attempt.by ? ` · ${attempt.by}` : ""}
              </div>
            </li>
          ))}
        </ul>
      )}

      {callsHref && mode === "idle" && !isOpen && (
        <div className="request-control-actions">
          <Link className="admin-btn" href={callsHref}>
            Все звонки
          </Link>
        </div>
      )}

      {isOpen && mode === "idle" && (
        <div className="request-control-actions">
          <button type="button" className="admin-btn" onClick={() => setMode("attempt")}>
            Отметить попытку
          </button>
          <button
            type="button"
            className="admin-btn"
            disabled={!control.can_disqualify}
            title={
              control.can_disqualify
                ? undefined
                : "Дисквалифицировать можно после двух попыток связаться с клиентом в разные дни"
            }
            onClick={() => setMode("disqualify")}
          >
            Дисквалифицировать
          </button>
          {callsHref && (
            <Link className="admin-btn" href={callsHref} title="Все звонки по номеру клиента после создания заявки">
              Все звонки
            </Link>
          )}
        </div>
      )}

      {isOpen && mode === "attempt" && (
        <div className="request-control-form">
          <p className="request-control-note">
            Разговоры из телефонии засчитываются сами. Отметьте вручную то, чего в телефонии не видно (написали в
            мессенджере, клиент зашёл лично) и опишите, что именно произошло - по комментарию это можно проверить.
          </p>
          <textarea
            rows={3}
            value={attemptComment}
            onChange={(event) => setAttemptComment(event.target.value)}
            placeholder="Что сделали и чем закончилось (обязательно)"
            aria-label="Комментарий к попытке"
          />
          <div className="request-control-actions">
            <button
              type="button"
              className="admin-btn admin-btn-primary"
              disabled={busy || !attemptComment.trim()}
              onClick={() => void submit("attempts", { comment: attemptComment })}
            >
              {busy ? "Сохраняем…" : "Отметить"}
            </button>
            <button type="button" className="admin-btn" disabled={busy} onClick={() => setMode("idle")}>
              Отмена
            </button>
          </div>
        </div>
      )}

      {isOpen && mode === "disqualify" && (
        <div className="request-control-form">
          <select value={reason} onChange={(event) => setReason(event.target.value)} aria-label="Причина">
            <option value="">Причина дисквалификации…</option>
            {control.reasons.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <textarea
            rows={2}
            value={reasonComment}
            onChange={(event) => setReasonComment(event.target.value)}
            placeholder={reason === "Другое" ? "Комментарий (обязателен)" : "Комментарий (необязательно)"}
            aria-label="Комментарий к дисквалификации"
          />
          <div className="request-control-actions">
            <button
              type="button"
              className="admin-btn admin-btn-danger"
              disabled={busy || !reason || (reason === "Другое" && !reasonComment.trim())}
              onClick={() => void submit("disqualify", { reason, comment: reasonComment })}
            >
              {busy ? "Сохраняем…" : "Дисквалифицировать"}
            </button>
            <button type="button" className="admin-btn" disabled={busy} onClick={() => setMode("idle")}>
              Отмена
            </button>
          </div>
        </div>
      )}

      {error && <p className="request-control-error">{error}</p>}
    </div>
  );
}
