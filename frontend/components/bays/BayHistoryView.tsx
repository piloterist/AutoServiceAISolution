"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { BayHistoryItem } from "@/lib/backend-api";
import { baysClient, eventSnapshotUrl } from "@/lib/bays-client";

const SHOP_TZ = "Europe/Moscow";

// YYYY-MM-DD в часовом поясе цеха (sv-SE даёт именно такой формат).
function shopDate(offsetDays = 0): string {
  return new Date(Date.now() + offsetDays * 86_400_000).toLocaleDateString("sv-SE", { timeZone: SHOP_TZ });
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    timeZone: SHOP_TZ,
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return "меньше минуты";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} мин`;
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`;
}

type Lightbox = { src: string; caption: string } | null;

/** Камера прочитала не то (у перекупщиков машины без номеров) или ошиблась в знаках: оператор
 * вводит верный номер или отмечает «Без номера». Заказ-наряд такой машины привязывают в записи
 * планировщика. */
function PlateFix({ item, onSaved }: { item: BayHistoryItem; onSaved: (updated: BayHistoryItem) => void }) {
  const [open, setOpen] = useState(false);
  const [plate, setPlate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (noPlate: boolean) => {
    if (!noPlate && !plate.trim()) {
      setError("Введите номер или нажмите «Без номера»");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onSaved(await baysClient.correctPlate(item.id, { plate: plate.trim(), noPlate }));
      setOpen(false);
      setPlate("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button type="button" className="admin-btn" style={{ marginTop: 6 }} onClick={() => setOpen(true)}>
        Исправить номер
      </button>
    );
  }
  return (
    <div style={{ marginTop: 6, display: "grid", gap: 6 }}>
      <input
        value={plate}
        onChange={(e) => setPlate(e.target.value)}
        placeholder="Например, А123ВС777"
        maxLength={20}
        autoFocus
        disabled={busy}
        onKeyDown={(e) => e.key === "Enter" && void save(false)}
      />
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <button type="button" className="admin-btn" disabled={busy} onClick={() => void save(false)}>
          Сохранить
        </button>
        <button type="button" className="admin-btn" disabled={busy} onClick={() => void save(true)}>
          Без номера
        </button>
        <button type="button" className="admin-btn" disabled={busy} onClick={() => setOpen(false)}>
          Отмена
        </button>
      </div>
      {error && <div className="bay-error">{error}</div>}
    </div>
  );
}

function Photo({
  label,
  event,
  emptyText,
  onOpen,
}: {
  label: string;
  event: BayHistoryItem["entry"];
  emptyText: string;
  onOpen: (lightbox: Lightbox) => void;
}) {
  const caption = event ? `${label}: ${formatDateTime(event.occurred_at)}` : label;
  return (
    <figure className="bay-pane bay-hist-photo">
      <figcaption className="bay-pane-label">{event ? caption : label}</figcaption>
      <div className="bay-viewer">
        {event?.has_snapshot ? (
          <button
            type="button"
            className="bay-viewer-img"
            onClick={() => onOpen({ src: eventSnapshotUrl(event.id), caption: `${caption}, ${event.plate ?? "номер не распознан"}` })}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={eventSnapshotUrl(event.id)} alt={caption} loading="lazy" />
          </button>
        ) : (
          <div className={`bay-viewer-empty${event?.source === "manual" ? " bay-viewer-manual" : ""}`}>
            {event?.source === "manual" ? (
              <>
                <strong>Ручное событие</strong>
                <span>
                  {event.created_by_name ?? "—"}, {event.created_at ? formatDateTime(event.created_at) : "—"}
                </span>
              </>
            ) : event ? (
              "Нет кадра"
            ) : (
              emptyText
            )}
          </div>
        )}
      </div>
    </figure>
  );
}

/** История заездов бокса по дням (product ask, 2026-11-04): широкие полосы от свежих к
 * старым, фильтр по датам (по умолчанию сегодня), в каждой - фото въезда и выезда с датой
 * и временем, номер, время в боксе и заказ-наряд, привязанный в момент въезда. */
export function BayHistoryView({
  bayId,
  bayName,
  jobId = null,
}: {
  bayId: string | null;
  bayName: string | null;
  /** Заезды одной записи планировщика (кнопка «Фото» в записи): без выбора дат. */
  jobId?: string | null;
}) {
  const [dateFrom, setDateFrom] = useState(shopDate());
  const [dateTo, setDateTo] = useState(shopDate());
  const [items, setItems] = useState<BayHistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<Lightbox>(null);

  const load = useCallback(async () => {
    if (!jobId && (!dateFrom || !dateTo || dateTo < dateFrom)) return;
    try {
      const params = jobId ? { jobId } : { dateFrom, dateTo, bayId: bayId ?? undefined };
      setItems((await baysClient.history(params)).items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить историю");
    }
  }, [dateFrom, dateTo, bayId, jobId]);

  useEffect(() => {
    setItems(null);
    void load();
  }, [load]);

  useEffect(() => {
    if (!lightbox) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setLightbox(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightbox]);

  const setRange = (from: string, to: string) => {
    setDateFrom(from);
    setDateTo(to);
  };

  return (
    <div className="bays-page">
      <div className="bays-toolbar card">
        {jobId ? (
          // Пришли из записи планировщика: возвращаем туда же, где были.
          <button type="button" className="admin-btn" onClick={() => window.history.back()}>
            ← Назад
          </button>
        ) : (
          <Link href="/bays" className="admin-btn">
            ← Боксы
          </Link>
        )}
        <h1 className="planner-title">
          {jobId ? "Фото заезда по записи планировщика" : `История${bayName ? `: ${bayName}` : ""}`}
        </h1>
        {!jobId && (
        <div className="bay-hist-filters">
          <label>
            С{" "}
            <input type="date" value={dateFrom} max={dateTo} onChange={(e) => setDateFrom(e.target.value)} />
          </label>
          <label>
            по{" "}
            <input type="date" value={dateTo} min={dateFrom} onChange={(e) => setDateTo(e.target.value)} />
          </label>
          <button type="button" className="admin-btn" onClick={() => setRange(shopDate(), shopDate())}>
            Сегодня
          </button>
          <button type="button" className="admin-btn" onClick={() => setRange(shopDate(-1), shopDate(-1))}>
            Вчера
          </button>
          <button type="button" className="admin-btn" onClick={() => setRange(shopDate(-6), shopDate())}>
            7 дней
          </button>
        </div>
        )}
      </div>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>{error}</p>
        </div>
      )}

      {items === null && !error && <div className="card">Загрузка…</div>}
      {items && items.length === 0 && (
        <div className="card">{jobId ? "У этой записи нет заездов видеоконтроля." : "За выбранные дни заездов не было."}</div>
      )}

      {items?.map((item) => (
        <section key={item.id} className="card bay-hist-row">
          <div className="bay-hist-info">
            <span className="bay-plate">{item.plate ?? (item.no_plate ? "без номера" : "номер не распознан")}</span>
            {!bayId && <div className="settings-description">{item.bay_name}</div>}
            <div className="bay-hist-fact">
              <span className="settings-description">В боксе</span>
              <strong>
                {formatDuration(item.duration_seconds)}
                {item.ended_at ? "" : " (ещё в боксе)"}
              </strong>
            </div>
            <div className="bay-hist-fact">
              <span className="settings-description">Заказ-наряд</span>
              {item.work_order_id ? (
                <Link href={`/work-orders/${item.work_order_id}`} className="bay-link">
                  {item.work_order_number}
                </Link>
              ) : (
                <span>не привязан</span>
              )}
            </div>
            {item.review_status === "needs_review" && <div className="bay-error">Нужна проверка номера</div>}
            {item.no_plate && !item.work_order_id && (
              <div className="settings-description">Заказ-наряд привяжите в записи планировщика</div>
            )}
            <PlateFix
              item={item}
              onSaved={(updated) => setItems((prev) => prev && prev.map((x) => (x.id === updated.id ? updated : x)))}
            />
          </div>
          <Photo label="Въезд" event={item.entry} emptyText="Нет данных" onOpen={setLightbox} />
          <Photo label="Выезд" event={item.exit} emptyText="Ещё в боксе" onOpen={setLightbox} />
        </section>
      ))}

      {lightbox && (
        <div className="bay-lightbox" role="dialog" aria-modal="true" onClick={() => setLightbox(null)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={lightbox.src} alt={lightbox.caption} />
          <div className="bay-lightbox-caption">{lightbox.caption}</div>
        </div>
      )}
    </div>
  );
}
