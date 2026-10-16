import { useEffect, useRef, useState } from "react";
import type { Grant, Presentation } from "./api";
import { ApiError } from "./api";
import { VoiceController } from "./voice";
import type { VoiceView } from "./voice";

export function SessionScreen({
  initial,
  grant,
  received,
  unauthorized,
}: {
  initial: Presentation;
  grant: Grant;
  received: (p: Presentation) => void;
  unauthorized: (e: ApiError) => void;
}) {
  const [view, setView] = useState<VoiceView>({
    phase: "loading",
    message: "Checking saved response…",
    presentation: initial,
    pending: false,
    finishPending: false,
  });
  const [hold, setHold] = useState(false);
  const controller = useRef<VoiceController | null>(null);
  const receivedRef = useRef(received),
    unauthorizedRef = useRef(unauthorized);
  receivedRef.current = received;
  unauthorizedRef.current = unauthorized;
  useEffect(() => {
    const c = new VoiceController(
      initial,
      grant.token,
      grant.learner_id,
      setView,
      (p) => receivedRef.current(p),
      (e) => unauthorizedRef.current(e),
    );
    controller.current = c;
    void c.initialize();
    return () => {
      c.dispose();
      controller.current = null;
    };
    // This component is keyed by identity and session. Updated presentations
    // belong to its controller; they must not reconstruct it after each turn.
  }, [grant.token, grant.learner_id, initial.session_id]);
  const p = view.presentation;
  const usable = ["ready", "error", "playing"].includes(view.phase);
  const capturing = ["recording", "requesting"].includes(view.phase);
  const canTalk =
    capturing || (usable && !view.pending && p.status === "active");
  function tap() {
    const c = controller.current;
    if (!c) return;
    if (["recording", "requesting"].includes(c.view.phase)) c.endRecording();
    else void c.startRecording();
  }
  function holdStart() {
    if (hold) void controller.current?.startRecording();
  }
  function holdEnd() {
    if (hold) controller.current?.endRecording();
  }
  return (
    <section aria-labelledby="session">
      <p className="eyebrow">{p.status}</p>
      <h2 id="session">Session ready</h2>
      {p.activity && (
        <p className="hint">
          Activity {p.activity.position + 1} of {p.activity.total}
          {p.activity.complete ? " · complete" : ""}
        </p>
      )}
      {p.card && <p className="card">{p.card}</p>}
      <div aria-label="Teacher instructions">
        {p.teacher.map((t, i) => (
          <p key={i} className="teacher">
            {t.text}
          </p>
        ))}
      </div>
      <p role={view.phase === "error" ? "alert" : "status"} aria-live="polite">
        {view.message}
      </p>
      {p.status === "paused" && (
        <p className="hint">
          This activity is saved and paused. You can leave this page or finish
          the session.
        </p>
      )}
      <div className="actions">
        <button
          disabled={!canTalk}
          aria-pressed={capturing}
          className="talk"
          onClick={() => {
            if (!hold) tap();
          }}
          onPointerDown={(e) => {
            if (hold && canTalk) {
              e.preventDefault();
              e.currentTarget.setPointerCapture(e.pointerId);
              holdStart();
            }
          }}
          onPointerUp={holdEnd}
          onPointerCancel={() => {
            if (hold) controller.current?.cancelRecording();
          }}
          onKeyDown={(e) => {
            if (hold && [" ", "Enter"].includes(e.key)) {
              e.preventDefault();
              if (!e.repeat) holdStart();
            }
          }}
          onKeyUp={(e) => {
            if (hold && [" ", "Enter"].includes(e.key)) {
              e.preventDefault();
              holdEnd();
            }
          }}
          onBlur={() => {
            if (hold && capturing) controller.current?.cancelRecording();
          }}
        >
          {hold
            ? capturing
              ? "Release to send"
              : "Hold to talk"
            : capturing
              ? "Send answer"
              : "Tap to talk"}
        </button>
        <button
          className="secondary"
          disabled={!usable || view.pending || !p.audio_ids.length}
          onClick={() => void controller.current?.play()}
        >
          Play teacher
        </button>
        <button
          className="secondary"
          disabled={view.phase !== "playing"}
          onClick={() => controller.current?.stopPlayback()}
        >
          Stop playback
        </button>
        <button
          className="secondary"
          disabled={p.status === "finished" || view.phase === "stopping"}
          onClick={() => void controller.current?.finish()}
        >
          Finish session
        </button>
      </div>
      <label className="hold-option">
        <input
          type="checkbox"
          checked={hold}
          disabled={!usable || view.pending}
          onChange={(e) => setHold(e.target.checked)}
        />{" "}
        Hold to talk instead of tapping
      </label>
      {capturing && (
        <button
          className="secondary"
          onClick={() => controller.current?.cancelRecording()}
        >
          Discard this recording
        </button>
      )}
      {view.phase === "error" && (
        <div className="actions">
          <button
            className="secondary"
            onClick={() => void controller.current?.recover()}
          >
            Recover saved response
          </button>
          {view.pending && !view.finishPending && (
            <button
              className="secondary"
              onClick={() => void controller.current?.discard()}
            >
              Discard pending recording
            </button>
          )}
        </div>
      )}
      <p className="hint">
        Your session is saved on the server. An unfinished recording stays on
        this device until its response is confirmed or you discard it. Teacher
        text remains available if audio cannot play.
      </p>
    </section>
  );
}
