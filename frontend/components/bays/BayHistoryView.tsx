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
          <div className="bay-viewer-empty">{event ? "Нет кадра" : emptyText}</div>
        )}
      </div>
    </figure>
  );
}

/** История заездов бокса по дням (product ask, 2026-11-04): широкие полосы от свежих к
 * старым, фильтр по датам (по умолчанию сегодня), в каждой - фото въезда и выезда с датой
 * и временем, номер, время в боксе и заказ-наряд, привязанный в момент въезда. */
export function BayHistoryView({ bayId, bayName }: { bayId: string | null; bayName: string | null }) {
  const [dateFrom, setDateFrom] = useState(shopDate());
  const [dateTo, setDateTo] = useState(shopDate());
  const [items, setItems] = useState<BayHistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<Lightbox>(null);

  const load = useCallback(async () => {
    if (!dateFrom || !dateTo || dateTo < dateFrom) return;
    try {
      setItems((await baysClient.history({ dateFrom, dateTo, bayId: bayId ?? undefined })).items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить историю");
    }
  }, [dateFrom, dateTo, bayId]);

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
        <Link href="/bays" className="admin-btn">
          ← Боксы
        </Link>
        <h1 className="planner-title">История{bayName ? `: ${bayName}` : ""}</h1>
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
      </div>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>{error}</p>
        </div>
      )}

      {items === null && !error && <div className="card">Загрузка…</div>}
      {items && items.length === 0 && <div className="card">За выбранные дни заездов не было.</div>}

      {items?.map((item) => (
        <section key={item.id} className="card bay-hist-row">
          <div className="bay-hist-info">
            <span className="bay-plate">{item.plate ?? "номер не распознан"}</span>
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
