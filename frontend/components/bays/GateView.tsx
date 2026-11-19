"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { SHOP_TZ, formatTime, linkStatus } from "@/components/bays/bay-utils";
import { AdminModal } from "@/components/settings/AdminModal";
import type { BayCard, GateStay, Workshop } from "@/lib/backend-api";
import { baysClient, eventSnapshotUrl, latestFrameUrl, requestImageUrl } from "@/lib/bays-client";

const REFRESH_MS = 10_000;
const SNAPSHOT_POLL_MS = 1_500;
const SNAPSHOT_TIMEOUT_MS = 60_000;

type Lightbox = { src: string; caption: string } | null;
type Tab = "inside" | "history";

// YYYY-MM-DD в часовом поясе цеха (sv-SE даёт именно такой формат).
function shopDate(offsetDays = 0): string {
  return new Date(Date.now() + offsetDays * 86_400_000).toLocaleDateString("sv-SE", { timeZone: SHOP_TZ });
}

/** «меньше минуты», «35 мин», «5 ч 10 мин», «3 дн 04 ч» - сколько машина в цехе. */
function formatDuration(ms: number): string {
  const minutes = Math.floor(Math.max(ms, 0) / 60_000);
  if (minutes < 1) return "меньше минуты";
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const rest = minutes % 60;
  if (days > 0) return `${days} дн ${String(hours).padStart(2, "0")} ч`;
  if (hours === 0) return `${rest} мин`;
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`;
}

function carsWord(count: number): string {
  const last = count % 10;
  const lastTwo = count % 100;
  if (last === 1 && lastTwo !== 11) return "машина";
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return "машины";
  return "машин";
}

function stayTitle(stay: GateStay): string {
  return stay.plate ?? stay.label ?? "номер не распознан";
}

// Нормализация для поиска: регистр и пробелы не важны, латиница и кириллица в номере одна и та же.
const LATIN_TO_CYRILLIC: Record<string, string> = {
  A: "А", B: "В", C: "С", E: "Е", H: "Н", K: "К", M: "М", O: "О", P: "Р", T: "Т", X: "Х", Y: "У",
};

function normalize(value: string): string {
  return value
    .toUpperCase()
    .replace(/\s+/g, "")
    .replace(/[ABCEHKMOPTXY]/g, (ch) => LATIN_TO_CYRILLIC[ch] ?? ch);
}

function matchesQuery(stay: GateStay, query: string): boolean {
  const needle = normalize(query);
  if (!needle) return true;
  return [stay.plate, stay.label, stay.car_description, stay.client_name, stay.work_order_number].some(
    (part) => part && normalize(part).includes(needle),
  );
}

// Статус карточки кузовного планировщика (planner_constants.CAR_STATUSES) -> цвет бейджа.
const CAR_STATUS_CLASS: Record<string, string> = {
  "К приёмке": "gate-status--accept",
  "В работе": "gate-status--work",
  Ожидание: "gate-status--wait",
  Согласование: "gate-status--approval",
  "Готова к выдаче": "gate-status--ready",
  Выдан: "gate-status--done",
};

function StayPhoto({
  stay,
  kind,
  onOpen,
}: {
  stay: GateStay;
  kind: "entry" | "exit";
  onOpen: (lightbox: Lightbox) => void;
}) {
  const event = kind === "entry" ? stay.entry : stay.exit;
  if (!event?.has_snapshot) return <span className="settings-description">—</span>;
  const src = eventSnapshotUrl(event.id);
  const caption = `${kind === "entry" ? "Въезд" : "Выезд"}: ${stayTitle(stay)}, ${formatTime(event.occurred_at)}`;
  return (
    <button type="button" className="gate-thumb" onClick={() => onOpen({ src, caption })} title={caption}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={caption} loading="lazy" />
    </button>
  );
}

type LiveState =
  | { status: "idle" }
  | { status: "waiting" }
  | { status: "done"; requestId: string; at: number }
  | { status: "failed"; message: string };

/** Камера у ворот: связь с узлом, последний кадр раз в минуту и «Получить кадр» сейчас. */
function GateCamera({ gate, onOpen }: { gate: BayCard; onOpen: (lightbox: Lightbox) => void }) {
  const [live, setLive] = useState<LiveState>({ status: "idle" });
  const link = linkStatus(gate, Date.now());

  const getFrame = async () => {
    setLive({ status: "waiting" });
    try {
      const request = await baysClient.requestSnapshot(gate.id);
      const deadline = Date.now() + SNAPSHOT_TIMEOUT_MS;
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, SNAPSHOT_POLL_MS));
        const current = await baysClient.snapshotRequest(request.id);
        if (current.status === "done") {
          setLive({ status: "done", requestId: request.id, at: Date.now() });
          return;
        }
        if (current.status === "failed") break;
      }
      setLive({ status: "failed", message: "Камера не ответила. Узел видеоконтроля на площадке не на связи?" });
    } catch (err) {
      setLive({ status: "failed", message: err instanceof Error ? err.message : "Не удалось получить кадр" });
    }
  };

  const liveIsNewer =
    live.status === "done" && (!gate.latest_frame_at || live.at > new Date(gate.latest_frame_at).getTime());
  const frame =
    liveIsNewer && live.status === "done"
      ? { src: `${requestImageUrl(live.requestId)}?t=${live.at}`, caption: `${gate.name}: кадр сейчас` }
      : gate.latest_frame_at
        ? {
            src: latestFrameUrl(gate.id, gate.latest_frame_at),
            caption: `${gate.name}: кадр ${formatTime(gate.latest_frame_at)}`,
          }
        : null;

  return (
    <div className="gate-camera">
      {(link.kind === "node" || link.kind === "camera") && (
        <div className={`bay-alert bay-alert--${link.kind}`} role="alert">
          {link.text}. Машины у ворот могли быть не замечены.
        </div>
      )}
      <div className="gate-camera-row">
        <div className="gate-camera-frame">
          <div className="bay-viewer">
            {frame ? (
              <button type="button" className="bay-viewer-img" onClick={() => onOpen(frame)}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={frame.src} alt={frame.caption} />
              </button>
            ) : (
              <div className="bay-viewer-empty">
                {live.status === "waiting" ? "Ждём ответа камеры…" : "Кадра ещё не было"}
              </div>
            )}
          </div>
          <div className="bay-viewer-caption">{frame ? frame.caption : " "}</div>
        </div>
        <div className="gate-camera-side">
          <div className="gate-camera-name">{gate.name}</div>
          <span className={`bay-link-status bay-link-status--${link.kind}`}>
            <span className="bay-link-dot" aria-hidden="true" />
            {link.kind === "node" || link.kind === "camera" ? "Нет связи" : link.text}
          </span>
          <button
            type="button"
            className="admin-btn"
            onClick={getFrame}
            disabled={live.status === "waiting"}
          >
            {live.status === "waiting" ? "Ждём камеру…" : "Получить кадр"}
          </button>
          {live.status === "failed" && <div className="bay-error">{live.message}</div>}
        </div>
      </div>
    </div>
  );
}

/** Ворота кузовного цеха (product ask, 2026-11-19): у цеха нет боксов, одни ворота и много места
 * внутри. Камера у ворот фиксирует въезд и выезд каждой машины; здесь - все машины, которые
 * сейчас внутри (въезд есть, выезда ещё не было), и история заездов. Машина может выехать и
 * вернуться - это отдельные заезды одной записи кузовного планировщика. Номера, которые камера
 * не прочитала, вводятся руками. */
export function GateView({
  workshop,
  gates,
  isAdmin,
  onOpen,
  onChanged,
}: {
  workshop: Workshop;
  gates: BayCard[];
  isAdmin: boolean;
  onOpen: (lightbox: Lightbox) => void;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<Tab>("inside");
  const [query, setQuery] = useState("");
  const [newestFirst, setNewestFirst] = useState(true);
  const [inside, setInside] = useState<GateStay[] | null>(null);
  const [history, setHistory] = useState<GateStay[] | null>(null);
  const [dateFrom, setDateFrom] = useState(shopDate(-29));
  const [dateTo, setDateTo] = useState(shopDate());
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // Ручной въезд.
  const [entryOpen, setEntryOpen] = useState(false);
  const [entryPlate, setEntryPlate] = useState("");
  const [entryLabel, setEntryLabel] = useState("");
  const [entryTime, setEntryTime] = useState("");
  const [entryGate, setEntryGate] = useState(gates[0]?.id ?? "");
  const [entryError, setEntryError] = useState<string | null>(null);
  const [entrySaving, setEntrySaving] = useState(false);

  // Правка номера/описания.
  const [editing, setEditing] = useState<GateStay | null>(null);
  const [editPlate, setEditPlate] = useState("");
  const [editLabel, setEditLabel] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [editSaving, setEditSaving] = useState(false);

  const workshopId = workshop.id;
  const gateOptions = useMemo(() => gates.filter((g) => g.enabled), [gates]);
  const insideCount = inside?.length ?? gates.reduce((sum, g) => sum + g.inside_count, 0);

  const loadInside = useCallback(async () => {
    try {
      setInside((await baysClient.gateStays({ workshopId, status: "inside" })).stays);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить список машин в цехе");
    }
  }, [workshopId]);

  const loadHistory = useCallback(async () => {
    if (!dateFrom || !dateTo || dateTo < dateFrom) return;
    try {
      setHistory((await baysClient.gateStays({ workshopId, status: "all", dateFrom, dateTo })).stays);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить историю");
    }
  }, [workshopId, dateFrom, dateTo]);

  useEffect(() => {
    setInside(null);
    void loadInside();
    const timer = setInterval(() => {
      void loadInside();
      setNow(Date.now());
    }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [loadInside]);

  useEffect(() => {
    if (tab !== "history") return;
    setHistory(null);
    void loadHistory();
  }, [tab, loadHistory]);

  const refreshAll = async () => {
    onChanged();
    await loadInside();
    if (tab === "history") await loadHistory();
  };

  const openEntry = () => {
    setEntryPlate("");
    setEntryLabel("");
    setEntryTime("");
    setEntryGate(gateOptions[0]?.id ?? gates[0]?.id ?? "");
    setEntryError(null);
    setEntryOpen(true);
  };

  const submitEntry = async () => {
    const plate = entryPlate.trim();
    const label = entryLabel.trim();
    if (!plate && !label) {
      setEntryError("Укажите номер или опишите машину («без номера»)");
      return;
    }
    if (!entryGate) {
      setEntryError("Нет ворот, на которые можно записать въезд");
      return;
    }
    setEntrySaving(true);
    setEntryError(null);
    try {
      await baysClient.addGateStay({
        bayId: entryGate,
        plate,
        label,
        enteredAt: entryTime ? new Date(entryTime).toISOString() : undefined,
      });
      setEntryOpen(false);
      await refreshAll();
    } catch (err) {
      setEntryError(err instanceof Error ? err.message : "Не удалось записать въезд");
    } finally {
      setEntrySaving(false);
    }
  };

  const markExit = async (stay: GateStay) => {
    if (!window.confirm(`Отметить выезд машины ${stayTitle(stay)} из цеха?`)) return;
    setBusyId(stay.id);
    setActionError(null);
    try {
      await baysClient.exitGateStay(stay.id);
      await refreshAll();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не удалось отметить выезд");
    } finally {
      setBusyId(null);
    }
  };

  const openEdit = (stay: GateStay) => {
    setEditing(stay);
    setEditPlate(stay.plate ?? "");
    setEditLabel(stay.label ?? "");
    setEditError(null);
  };

  const submitEdit = async () => {
    if (!editing) return;
    const plate = editPlate.trim();
    const label = editLabel.trim();
    if (!plate && !label) {
      setEditError("Укажите номер или описание машины");
      return;
    }
    setEditSaving(true);
    setEditError(null);
    try {
      await baysClient.updateGateStay(editing.id, { plate: plate || null, label: label || null });
      setEditing(null);
      await refreshAll();
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setEditSaving(false);
    }
  };

  const rows = useMemo(() => {
    const source = (tab === "inside" ? inside : history) ?? [];
    const filtered = source.filter((stay) => matchesQuery(stay, query));
    filtered.sort((a, b) => {
      const diff = new Date(a.entered_at).getTime() - new Date(b.entered_at).getTime();
      return newestFirst ? -diff : diff;
    });
    return filtered;
  }, [tab, inside, history, query, newestFirst]);

  const loaded = tab === "inside" ? inside !== null : history !== null;
  const noPlan = inside?.filter((s) => !s.has_plan).length ?? 0;
  const showGateColumn = gates.length > 1;

  const renderRow = (stay: GateStay) => {
    const isInside = stay.exited_at === null;
    const duration = isInside
      ? formatDuration(now - new Date(stay.entered_at).getTime())
      : formatDuration(stay.duration_seconds * 1000);
    const rowClass = [
      "gate-row",
      !stay.has_plan ? "gate-row--noplan" : "",
      stay.review_status === "needs_review" ? "gate-row--review" : "",
    ]
      .filter(Boolean)
      .join(" ");
    return (
      <tr key={stay.id} className={rowClass}>
        <td data-label="Номер">
          <span className={stay.plate ? "bay-plate gate-plate" : "bay-plate bay-plate--empty gate-plate"}>
            {stayTitle(stay)}
          </span>
          <div className="gate-flags">
            {!stay.has_plan && <span className="gate-flag gate-flag--down">нет в плане</span>}
            {stay.review_status === "needs_review" && <span className="gate-flag gate-flag--warn">проверить</span>}
            {stay.source === "manual" && <span className="gate-flag">вручную</span>}
            {showGateColumn && <span className="gate-flag">{stay.bay_name}</span>}
          </div>
        </td>
        <td data-label="Автомобиль">
          <div>{stay.car_description ?? (stay.plate && stay.label ? stay.label : "—")}</div>
          {stay.client_name && <div className="settings-description">{stay.client_name}</div>}
        </td>
        <td data-label="Заказ-наряд">
          {stay.work_order_id ? (
            <Link href={`/work-orders/${stay.work_order_id}`} className="bay-link">
              {stay.work_order_number}
            </Link>
          ) : (
            <span className="settings-description">не привязан</span>
          )}
        </td>
        <td data-label="В плане">
          {stay.car_status ? (
            <span className={`gate-status ${CAR_STATUS_CLASS[stay.car_status] ?? ""}`.trim()}>{stay.car_status}</span>
          ) : (
            <span className="settings-description">—</span>
          )}
        </td>
        <td data-label="Въехала">{formatTime(stay.entered_at)}</td>
        {tab === "history" && (
          <td data-label="Выехала">{stay.exited_at ? formatTime(stay.exited_at) : <strong>в цехе</strong>}</td>
        )}
        <td data-label="В цехе">{duration}</td>
        <td data-label="Фото въезда">
          <StayPhoto stay={stay} kind="entry" onOpen={onOpen} />
        </td>
        {tab === "history" && (
          <td data-label="Фото выезда">
            <StayPhoto stay={stay} kind="exit" onOpen={onOpen} />
          </td>
        )}
        <td className="gate-actions" data-label="">
          {isInside && (
            <button type="button" className="admin-btn" disabled={busyId === stay.id} onClick={() => void markExit(stay)}>
              Выезд
            </button>
          )}
          <button type="button" className="admin-btn" onClick={() => openEdit(stay)}>
            Изменить номер
          </button>
        </td>
      </tr>
    );
  };

  return (
    <div className="gate-view">
      <section className="card gate-summary">
        <div className="gate-count">
          <span className="gate-count-num">{insideCount}</span>
          <span className="gate-count-text">
            В цехе: {insideCount} {carsWord(insideCount)}
          </span>
        </div>
        {noPlan > 0 && (
          <div className="gate-flag gate-flag--down gate-flag--big">
            Не найдено в плане кузовного: {noPlan}
          </div>
        )}
        <div className="gate-summary-actions">
          <button type="button" className="admin-btn admin-btn-primary" onClick={openEntry}>
            Ввести въезд вручную
          </button>
        </div>
      </section>

      <div className="gate-cameras">
        {gates.map((gate) => (
          <GateCamera key={gate.id} gate={gate} onOpen={onOpen} />
        ))}
      </div>

      <section className="card gate-list">
        <div className="gate-toolbar">
          <div className="admin-tabs">
            <button
              type="button"
              className={tab === "inside" ? "admin-tab admin-tab--on" : "admin-tab"}
              onClick={() => setTab("inside")}
            >
              Сейчас в цехе
            </button>
            <button
              type="button"
              className={tab === "history" ? "admin-tab admin-tab--on" : "admin-tab"}
              onClick={() => setTab("history")}
            >
              История
            </button>
          </div>
          <input
            type="search"
            className="gate-search"
            placeholder="Поиск: номер, клиент, заказ-наряд"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Поиск по машинам"
          />
          <button type="button" className="admin-btn" onClick={() => setNewestFirst((v) => !v)}>
            Въезд: {newestFirst ? "сначала новые ↓" : "сначала старые ↑"}
          </button>
        </div>

        {tab === "history" && (
          <div className="bay-hist-filters gate-hist-filters">
            <label>
              С <input type="date" value={dateFrom} max={dateTo} onChange={(e) => setDateFrom(e.target.value)} />
            </label>
            <label>
              по <input type="date" value={dateTo} min={dateFrom} onChange={(e) => setDateTo(e.target.value)} />
            </label>
            <button
              type="button"
              className="admin-btn"
              onClick={() => {
                setDateFrom(shopDate());
                setDateTo(shopDate());
              }}
            >
              Сегодня
            </button>
            <button
              type="button"
              className="admin-btn"
              onClick={() => {
                setDateFrom(shopDate(-6));
                setDateTo(shopDate());
              }}
            >
              7 дней
            </button>
            <button
              type="button"
              className="admin-btn"
              onClick={() => {
                setDateFrom(shopDate(-29));
                setDateTo(shopDate());
              }}
            >
              30 дней
            </button>
          </div>
        )}

        {error && <div className="bay-error">{error}</div>}
        {actionError && <div className="bay-error">{actionError}</div>}
        {!loaded && !error && <p>Загрузка…</p>}
        {loaded && rows.length === 0 && (
          <p className="settings-description">
            {query
              ? "Ничего не найдено."
              : tab === "inside"
                ? "В цехе сейчас нет машин."
                : "За выбранный период заездов не было."}
          </p>
        )}

        {rows.length > 0 && (
          <div className="gate-table-wrap">
            <table className="data-table gate-table">
              <thead>
                <tr>
                  <th>Номер</th>
                  <th>Автомобиль / клиент</th>
                  <th>Заказ-наряд</th>
                  <th>В плане</th>
                  <th>Въехала</th>
                  {tab === "history" && <th>Выехала</th>}
                  <th>В цехе</th>
                  <th>Фото въезда</th>
                  {tab === "history" && <th>Фото выезда</th>}
                  <th />
                </tr>
              </thead>
              <tbody>{rows.map(renderRow)}</tbody>
            </table>
          </div>
        )}
        {rows.length > 0 && <div className="settings-description gate-total">Показано: {rows.length}</div>}
      </section>

      {isAdmin && gates.length > 0 && <GateCameraCodes gates={gates} onChanged={onChanged} />}

      <AdminModal
        open={entryOpen}
        title="Ввести въезд вручную"
        onClose={() => {
          if (!entrySaving) setEntryOpen(false);
        }}
      >
        <div className="gate-dialog">
          <p className="settings-description">
            Для машины без номера или если камера её не увидела. Укажите номер или опишите машину.
          </p>
          <label htmlFor="gate-entry-plate">Номер</label>
          <input
            id="gate-entry-plate"
            type="text"
            placeholder="Например, А123ВС77"
            value={entryPlate}
            onChange={(e) => setEntryPlate(e.target.value)}
            maxLength={20}
          />
          <label htmlFor="gate-entry-label">Или описание (без номера)</label>
          <input
            id="gate-entry-label"
            type="text"
            placeholder="Например, белый Solaris без номера"
            value={entryLabel}
            onChange={(e) => setEntryLabel(e.target.value)}
            maxLength={200}
          />
          <label htmlFor="gate-entry-time">Время въезда (если не сейчас)</label>
          <input
            id="gate-entry-time"
            type="datetime-local"
            value={entryTime}
            onChange={(e) => setEntryTime(e.target.value)}
          />
          {gateOptions.length > 1 && (
            <>
              <label htmlFor="gate-entry-gate">Ворота</label>
              <select id="gate-entry-gate" value={entryGate} onChange={(e) => setEntryGate(e.target.value)}>
                {gateOptions.map((gate) => (
                  <option key={gate.id} value={gate.id}>
                    {gate.name}
                  </option>
                ))}
              </select>
            </>
          )}
          {entryError && <p className="admin-form-error">{entryError}</p>}
          <div className="request-control-actions">
            <button
              type="button"
              className="admin-btn admin-btn-primary"
              disabled={entrySaving}
              onClick={() => void submitEntry()}
            >
              {entrySaving ? "Сохраняем…" : "Записать въезд"}
            </button>
            <button type="button" className="admin-btn" disabled={entrySaving} onClick={() => setEntryOpen(false)}>
              Отмена
            </button>
          </div>
        </div>
      </AdminModal>

      <AdminModal
        open={editing !== null}
        title="Изменить номер"
        onClose={() => {
          if (!editSaving) setEditing(null);
        }}
      >
        <div className="gate-dialog">
          <p className="settings-description">
            После сохранения запись кузовного планировщика ищется заново по новому номеру.
          </p>
          <label htmlFor="gate-edit-plate">Номер</label>
          <input
            id="gate-edit-plate"
            type="text"
            placeholder="Например, А123ВС77"
            value={editPlate}
            onChange={(e) => setEditPlate(e.target.value)}
            maxLength={20}
          />
          <label htmlFor="gate-edit-label">Описание (если без номера)</label>
          <input
            id="gate-edit-label"
            type="text"
            value={editLabel}
            onChange={(e) => setEditLabel(e.target.value)}
            maxLength={200}
          />
          {editError && <p className="admin-form-error">{editError}</p>}
          <div className="request-control-actions">
            <button
              type="button"
              className="admin-btn admin-btn-primary"
              disabled={editSaving}
              onClick={() => void submitEdit()}
            >
              {editSaving ? "Сохраняем…" : "Сохранить"}
            </button>
            <button type="button" className="admin-btn" disabled={editSaving} onClick={() => setEditing(null)}>
              Отмена
            </button>
          </div>
        </div>
      </AdminModal>
    </div>
  );
}

/** Админ: код камеры у ворот (узел на площадке сопоставляет ворота с камерой по нему). */
function GateCameraCodes({ gates, onChanged }: { gates: BayCard[]; onChanged: () => void }) {
  return (
    <section className="card gate-codes">
      {gates.map((gate) => (
        <GateCameraCode key={gate.id} gate={gate} onChanged={onChanged} />
      ))}
    </section>
  );
}

function GateCameraCode({ gate, onChanged }: { gate: BayCard; onChanged: () => void }) {
  const [code, setCode] = useState(gate.camera_code ?? "");
  const [note, setNote] = useState<string | null>(null);

  const save = async () => {
    setNote(null);
    try {
      await baysClient.setCameraCode(gate.id, code.trim());
      setNote("Сохранено");
      onChanged();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  return (
    <div className="bay-manual-form">
      <input
        type="text"
        aria-label={`Код камеры: ${gate.name}`}
        placeholder="Камера, например cam2"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        maxLength={50}
      />
      <button type="button" className="admin-btn" onClick={save}>
        Сохранить камеру ({gate.name})
      </button>
      {note && <span className="settings-description">{note}</span>}
    </div>
  );
}
