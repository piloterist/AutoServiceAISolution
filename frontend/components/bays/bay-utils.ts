// Общие мелочи страницы «Боксы»: время по часовому поясу цеха и состояние связи с узлом
// видеоконтроля (используют и карточки боксов, и список «Сейчас в цехе» у ворот кузовного).
import type { BayCard } from "@/lib/backend-api";

export const SHOP_TZ = "Europe/Moscow";
export const NODE_OFFLINE_MS = 2 * 60_000; // узел шлёт сигнал раз в ~30 секунд; тишина дольше - не на связи

export function formatTime(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("ru-RU", {
    timeZone: SHOP_TZ,
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatSpan(ms: number): string {
  const minutes = Math.max(Math.round(ms / 60_000), 1);
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  return minutes % 60 === 0 ? `${hours} ч` : `${hours} ч ${minutes % 60} мин`;
}

export type LinkKind = "none" | "unknown" | "ok" | "node" | "camera";

// Состояние связи видеоконтроля бокса: узел на площадке и камера. Не «всё тихо», а явно -
// иначе выключенный узел выглядит как спокойный бокс со старыми кадрами.
export function linkStatus(bay: BayCard, now: number): { kind: LinkKind; text: string } {
  if (!bay.camera_code) return { kind: "none", text: "Камера не назначена" };
  if (!bay.node_seen_at) return { kind: "unknown", text: "Узел видеоконтроля ещё не выходил на связь" };
  const silent = now - new Date(bay.node_seen_at).getTime();
  if (silent > NODE_OFFLINE_MS) {
    return {
      kind: "node",
      text: `Узел видеоконтроля не на связи уже ${formatSpan(silent)} (с ${formatTime(bay.node_seen_at)})`,
    };
  }
  if (bay.camera_ok === false && bay.camera_ok_since) {
    return {
      kind: "camera",
      text: `Камера не отдаёт видео уже ${formatSpan(now - new Date(bay.camera_ok_since).getTime())}`,
    };
  }
  return { kind: "ok", text: "Узел на связи, камера работает" };
}
