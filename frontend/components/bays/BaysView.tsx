"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { formatTime, linkStatus } from "@/components/bays/bay-utils";
import { GateView } from "@/components/bays/GateView";
import type { BayCard, Workshop } from "@/lib/backend-api";
import { baysClient, eventSnapshotUrl, latestFrameUrl, requestImageUrl } from "@/lib/bays-client";

const REFRESH_MS = 10_000;
const SNAPSHOT_POLL_MS = 1_500;
const SNAPSHOT_TIMEOUT_MS = 60_000;
const PAGE_SIZE = 6;
const EMPTY_AFTER_MS = 10 * 60_000; // столько бокс пуст после выезда - кадр бокса идёт во все три окна

const STATE_LABEL: Record<BayCard["state"], string> = {
  free: "Свободен",
  occupied: "Занят",
  review: "Нужна проверка",
};

type Lightbox = { src: string; caption: string } | null;

type Frame = { src: string; caption: string } | null;

type LiveState =
  | { status: "idle" }
  | { status: "waiting" }
  | { status: "done"; requestId: string; at: number }
  | { status: "failed"; message: string };

function BayTile({
  bay,
  isAdmin,
  onOpen,
  onChanged,
}: {
  bay: BayCard;
  isAdmin: boolean;
  onOpen: (lightbox: Lightbox) => void;
  onChanged: () => void;
}) {
  const [live, setLive] = useState<LiveState>({ status: "idle" });
  const [cameraCode, setCameraCode] = useState(bay.camera_code ?? "");
  const [cameraNote, setCameraNote] = useState<string | null>(null);

  const saveCameraCode = async () => {
    setCameraNote(null);
    try {
      await baysClient.setCameraCode(bay.id, cameraCode.trim());
      setCameraNote("Сохранено");
      onChanged();
    } catch (err) {
      setCameraNote(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };
  const [manualOpen, setManualOpen] = useState(false);
  const [manualType, setManualType] = useState("entry_confirmed");
  const [manualPlate, setManualPlate] = useState("");
  const [manualError, setManualError] = useState<string | null>(null);

  const getFrame = async () => {
    setLive({ status: "waiting" });
    try {
      const request = await baysClient.requestSnapshot(bay.id);
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

  const submitManual = async () => {
    setManualError(null);
    try {
      await baysClient.addEvent(bay.id, manualType, manualPlate);
      setManualPlate("");
      setManualOpen(false);
      onChanged();
    } catch (err) {
      setManualError(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  const eventFrame = (event: BayCard["last_entry"], title: string): Frame =>
    event?.has_snapshot
      ? {
          src: eventSnapshotUrl(event.id),
          caption: `${title}: ${event.plate ?? "номер не распознан"}, ${formatTime(event.occurred_at)}`,
        }
      : null;
  const liveFrame: Frame =
    live.status === "done"
      ? { src: `${requestImageUrl(live.requestId)}?t=${live.at}`, caption: `${bay.name}: кадр сейчас` }
      : null;
  const liveEmpty = live.status === "waiting" ? "Ждём ответа камеры…" : "Нажмите «Получить кадр»";
  // Узел присылает кадр бокса раз в минуту: он всегда в окне «Сейчас» - мастер видит, что в боксе
  // происходит, и пропущенный выезд заметен (бокс «занят», а на кадре пусто). Кадр по кнопке
  // показываем, пока он свежее минутного.
  const latestFrame: Frame = bay.latest_frame_at
    ? {
        src: latestFrameUrl(bay.id, bay.latest_frame_at),
        caption: `${bay.name}: кадр ${formatTime(bay.latest_frame_at)}`,
      }
    : null;
  const liveIsNewer =
    live.status === "done" && (!bay.latest_frame_at || live.at > new Date(bay.latest_frame_at).getTime());
  const nowFrame = liveIsNewer ? liveFrame : latestFrame;
  // Бокс пуст 10+ минут после выезда: тот же кадр показываем во всех трёх окнах, иначе в
  // «Въезде» и «Выезде» висели бы кадры уехавшей машины.
  const lastActivity = Math.max(
    bay.last_entry ? new Date(bay.last_entry.occurred_at).getTime() : 0,
    bay.last_exit ? new Date(bay.last_exit.occurred_at).getTime() : 0,
  );
  const emptyForAWhile = bay.state === "free" && Date.now() - lastActivity > EMPTY_AFTER_MS;
  const emptyFrame: Frame = emptyForAWhile && latestFrame ? { ...latestFrame, caption: `${bay.name}: пустой бокс, кадр ${formatTime(bay.latest_frame_at)}` } : null;
  // Выезд старше текущего въезда относится к прошлой машине: пока она в боксе, окно пустое.
  const link = linkStatus(bay, Date.now());
  const exitIsStale =
    bay.last_entry !== null &&
    bay.last_exit !== null &&
    new Date(bay.last_exit.occurred_at) < new Date(bay.last_entry.occurred_at);

  const pane = (label: string, frame: Frame, emptyText: string, extra = "") => (
    <figure className={`bay-pane ${extra}`.trim()}>
      <figcaption className="bay-pane-label">{label}</figcaption>
      <div className="bay-viewer">
        {frame ? (
          <button type="button" className="bay-viewer-img" onClick={() => onOpen(frame)}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={frame.src} alt={frame.caption} />
          </button>
        ) : (
          <div className="bay-viewer-empty">{emptyText}</div>
        )}
      </div>
      <div className="bay-viewer-caption">{frame ? frame.caption.split(": ").slice(1).join(": ") : " "}</div>
    </figure>
  );

  return (
    <section className={`card bay-tile bay-tile--${bay.state}`}>
      {link.kind === "node" || link.kind === "camera" ? (
        <div className={`bay-alert bay-alert--${link.kind}`} role="alert">
          {link.text}. Данные по боксу могут быть неактуальны.
        </div>
      ) : null}
      <header className="bay-head">
        <span className={`bay-light bay-light--${bay.state}`} role="img" aria-label={STATE_LABEL[bay.state]} />
        <div>
          <h2 className="bay-name">{bay.name}</h2>
          <div className="bay-state">
            {STATE_LABEL[bay.state]}
            {bay.occupied_since ? ` · с ${formatTime(bay.occupied_since)}` : ""}
          </div>
          {bay.work_order_id && (
            <div className="bay-state">
              Заказ-наряд:{" "}
              <Link href={`/work-orders/${bay.work_order_id}`} className="bay-link">
                {bay.work_order_number}
              </Link>
            </div>
          )}
        </div>
        {bay.plate ? (
          <span className="bay-plate">{bay.plate}</span>
        ) : (
          <span className="bay-plate bay-plate--empty">{bay.state === "free" ? "—" : "номер не распознан"}</span>
        )}
      </header>

      <div className="bay-live-row">
        {pane("Сейчас", nowFrame, liveEmpty)}
        <button
          type="button"
          className="admin-btn admin-btn-primary bay-viewer-get"
          onClick={getFrame}
          disabled={live.status === "waiting"}
        >
          {live.status === "waiting" ? "Ждём камеру…" : "Получить кадр"}
        </button>
      </div>
      <div className="bay-pair">
        {pane("Въезд", emptyFrame ?? eventFrame(bay.last_entry, "Въезд"), bay.last_entry ? "Нет кадра" : "Въездов не было")}
        {pane(
          "Выезд",
          emptyFrame ?? (exitIsStale ? null : eventFrame(bay.last_exit, "Выезд")),
          exitIsStale ? "Машина в боксе" : bay.last_exit ? "Нет кадра" : "Выездов не было",
        )}
      </div>
      <div className="bay-actions">
        <Link href={`/bays/history?bay=${bay.id}&name=${encodeURIComponent(bay.name)}`} className="admin-btn">
          История
        </Link>
        <span className={`bay-link-status bay-link-status--${link.kind}`}>
          <span className="bay-link-dot" aria-hidden="true" />
          {link.kind === "node" || link.kind === "camera" ? "Нет связи" : link.text}
        </span>
      </div>
      {live.status === "failed" && <div className="bay-error">{live.message}</div>}

      {isAdmin && (
        <div className="bay-manual-form">
          <input
            type="text"
            aria-label="Код камеры бокса"
            placeholder="Камера, например cam1"
            value={cameraCode}
            onChange={(e) => setCameraCode(e.target.value)}
            maxLength={50}
          />
          <button type="button" className="admin-btn" onClick={saveCameraCode}>
            Сохранить камеру
          </button>
          {cameraNote && <span className="settings-description">{cameraNote}</span>}
        </div>
      )}

      <div className="bay-manual">
        <button type="button" className="bay-link" onClick={() => setManualOpen((v) => !v)}>
          {manualOpen ? "Скрыть ручной ввод" : "Ввести событие вручную"}
        </button>
        {manualOpen && (
          <div className="bay-manual-form">
            <select value={manualType} onChange={(e) => setManualType(e.target.value)}>
              <option value="entry_confirmed">Въезд</option>
              <option value="exit_confirmed">Выезд</option>
            </select>
            <input
              type="text"
              placeholder="Номер, например А123ВС77"
              value={manualPlate}
              onChange={(e) => setManualPlate(e.target.value)}
              maxLength={20}
            />
            <button type="button" className="admin-btn" onClick={submitManual}>
              Записать
            </button>
            {manualError && <div className="bay-error">{manualError}</div>}
          </div>
        )}
      </div>
    </section>
  );
}

/** Боксы (product ask, 2026-11-03): per workshop, a tile per bay with a traffic
 * light (red = occupied, green = free, amber = needs review), the plate of the
 * car in the bay, the entry and exit frames taken when the plate was
 * recognised, and a "Получить кадр" button. Events come from the on-site
 * video-control node (see backend services/bay_service.py); until it is
 * connected they can be typed in by hand. */
export function BaysView({
  workshops,
  defaultWorkshopId,
  isAdmin,
}: {
  workshops: Workshop[];
  defaultWorkshopId: string | null;
  isAdmin: boolean;
}) {
  const [workshopId, setWorkshopId] = useState<string | null>(
    workshops.find((w) => w.id === defaultWorkshopId)?.id ?? workshops[0]?.id ?? null,
  );
  const [bays, setBays] = useState<BayCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<Lightbox>(null);
  const [newName, setNewName] = useState("");
  const [page, setPage] = useState(0);

  const workshop = workshops.find((w) => w.id === workshopId) ?? null;
  const departments = useMemo(() => {
    const seen = new Map<string, string>();
    for (const w of workshops) seen.set(w.department_id, w.department_name);
    return Array.from(seen, ([id, name]) => ({ id, name }));
  }, [workshops]);
  const workshopTypes = workshops.filter((w) => w.department_id === workshop?.department_id);

  const load = useCallback(async () => {
    if (!workshopId) return;
    try {
      setBays((await baysClient.list(workshopId)).bays);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить боксы");
    }
  }, [workshopId]);

  useEffect(() => {
    setBays(null);
    setPage(0);
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!lightbox) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setLightbox(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightbox]);

  const selectDepartment = (departmentId: string) => {
    const first = workshops.find((w) => w.department_id === departmentId);
    if (first) setWorkshopId(first.id);
  };

  const createDefaults = async () => {
    if (!workshopId) return;
    try {
      setBays((await baysClient.createDefaults(workshopId)).bays);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать боксы");
    }
  };

  const createGate = async () => {
    if (!workshopId) return;
    try {
      setBays((await baysClient.create(workshopId, "Ворота", "gate")).bays);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать ворота");
    }
  };

  const addBay = async () => {
    if (!workshopId || !newName.trim()) return;
    try {
      setBays((await baysClient.create(workshopId, newName.trim())).bays);
      setNewName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось добавить бокс");
    }
  };

  // Кузовной цех: у него ворота, а не боксы - вместо карточек показываем «Сейчас в цехе».
  const gates = useMemo(() => bays?.filter((b) => b.kind === "gate") ?? [], [bays]);
  const isBodyShop = workshop?.workshop_type === "Кузовной";
  // У кузовного цеха ворота заменяют боксы: обычные боксы (заготовка слесарного) скрываем.
  const regularBays = useMemo(
    () => (isBodyShop && gates.length > 0 ? [] : (bays?.filter((b) => b.kind !== "gate") ?? [])),
    [bays, gates, isBodyShop],
  );
  const pageCount = Math.max(1, Math.ceil(regularBays.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const pageBays = regularBays.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const occupied = regularBays.filter((b) => b.state !== "free").length;

  return (
    <div className="bays-page">
      <div className="bays-toolbar card">
        <h1 className="planner-title">Боксы</h1>

        <div className="planner-dept-switch">
          {departments.map((department) => (
            <button
              key={department.id}
              type="button"
              className={
                department.id === workshop?.department_id ? "planner-dept-btn planner-dept-btn--on" : "planner-dept-btn"
              }
              onClick={() => selectDepartment(department.id)}
            >
              {department.name}
            </button>
          ))}
        </div>

        <div className="admin-tabs planner-workshop-type-tabs">
          {workshopTypes.map((w) => (
            <button
              key={w.id}
              type="button"
              className={w.id === workshopId ? "admin-tab admin-tab--on" : "admin-tab"}
              onClick={() => setWorkshopId(w.id)}
            >
              {w.workshop_type}
            </button>
          ))}
        </div>

        {regularBays.length > 0 && (
          <div className="settings-description">
            Занято {occupied} из {regularBays.length}
          </div>
        )}
        {pageCount > 1 && (
          <div className="bays-pager">
            <button type="button" className="admin-btn" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>
              ←
            </button>
            <span>
              {currentPage + 1} / {pageCount}
            </span>
            <button
              type="button"
              className="admin-btn"
              disabled={currentPage >= pageCount - 1}
              onClick={() => setPage(currentPage + 1)}
            >
              →
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>{error}</p>
        </div>
      )}

      {bays && isBodyShop && gates.length === 0 && (
        <div className="card">
          <p>
            У кузового цеха нет боксов: одни ворота, а машин внутри может быть много. Камера на воротах
            фиксирует въезд и выезд, а страница показывает список «Сейчас в цехе».
          </p>
          {isAdmin ? (
            <button type="button" className="admin-btn admin-btn-primary" onClick={createGate}>
              Создать ворота
            </button>
          ) : (
            <p className="settings-description">Ворота создаёт администратор.</p>
          )}
        </div>
      )}

      {bays && bays.length === 0 && !isBodyShop && (
        <div className="card">
          <p>В этом цехе пока нет боксов.</p>
          {isAdmin && workshop ? (
            <button type="button" className="admin-btn" onClick={createDefaults}>
              Создать боксы по числу постов ({workshop.posts_count})
            </button>
          ) : (
            <p className="settings-description">Боксы создаёт администратор.</p>
          )}
        </div>
      )}

      {workshop && gates.length > 0 && (
        <GateView workshop={workshop} gates={gates} isAdmin={isAdmin} onOpen={setLightbox} onChanged={load} />
      )}

      {regularBays.length > 0 && (
        <div className="bays-grid">
          {pageBays.map((bay) => (
            <BayTile key={bay.id} bay={bay} isAdmin={isAdmin} onOpen={setLightbox} onChanged={load} />
          ))}
        </div>
      )}

      {isAdmin && regularBays.length > 0 && (
        <div className="bays-add card">
          <input
            type="text"
            placeholder="Название нового бокса"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            maxLength={100}
          />
          <button type="button" className="admin-btn" onClick={addBay} disabled={!newName.trim()}>
            Добавить бокс
          </button>
        </div>
      )}

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
