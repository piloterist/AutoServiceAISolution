"use client";

import { useState } from "react";

/** PLAY button for one call (product ask, 2026-10-21 - both the Телефония
 * call table and a lead's matched-calls list reuse this same component).
 * Lazy: the recording is only fetched once this button is actually
 * clicked, not preloaded for every row - see app/api/telephony/calls/
 * [callId]/recording/route.ts for where the audio itself comes from. */
export function CallRecordingPlayer({
  callId,
  hasRecording,
}: {
  callId: string;
  hasRecording: boolean;
}) {
  const [open, setOpen] = useState(false);

  if (!hasRecording) return <span className="call-recording-none">—</span>;

  if (!open) {
    return (
      <button
        type="button"
        className="call-recording-play-btn"
        onClick={(event) => {
          event.stopPropagation();
          setOpen(true);
        }}
        title="Прослушать запись"
        aria-label="Прослушать запись"
      >
        ▶
      </button>
    );
  }

  return (
    // Stops the click from bubbling into an expandable parent row (e.g. a
    // Телефония call row, a lead's own row) - this span itself isn't
    // interactive, it just owns the real <audio controls> below.
    <span onClick={(event) => event.stopPropagation()}>
      <audio
        controls
        autoPlay
        src={`/api/telephony/calls/${callId}/recording`}
        className="call-recording-audio"
      >
        Браузер не поддерживает воспроизведение аудио.
      </audio>
    </span>
  );
}
