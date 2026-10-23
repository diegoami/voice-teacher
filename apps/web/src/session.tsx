import { useEffect, useRef, useState } from "react";
import type { Grant, Presentation, SavedSession } from "./api";
import { ApiError } from "./api";
import { Conversation } from "./conversation";
import { VoiceController } from "./voice";
import type { VoiceView } from "./voice";

export function SessionScreen({
  initial,
  context,
  grant,
  received,
  unauthorized,
}: {
  initial: Presentation;
  context?: SavedSession;
  grant: Grant;
  received: (p: Presentation) => void;
  unauthorized: (e: ApiError) => void;
}) {
  const [view, setView] = useState<VoiceView>({
    phase: "loading",
    message: "Checking saved response…",
    presentation: initial,
    pending: false,
    controlPending: null,
    hasUpload: false,
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
  const recording = view.phase === "recording";
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!recording || view.recordingStartedAt === undefined) return;
    const update = () =>
      setElapsed(Math.floor((Date.now() - view.recordingStartedAt!) / 1000));
    update();
    const timer = setInterval(update, 250);
    return () => clearInterval(timer);
  }, [recording, view.recordingStartedAt]);
  const phaseLabels: Record<VoiceView["phase"], string> = {
    loading: "Loading saved session",
    ready:
      p.status === "paused"
        ? "Session paused"
        : p.status === "finished"
          ? "Session finished"
          : "Ready for your answer",
    requesting: "Waiting for microphone permission",
    recording: "Recording — microphone is on",
    saving: "Microphone off — saving recording",
    processing: "Microphone off — processing answer",
    playing: "Teacher speaking — microphone off",
    error: "Needs attention — microphone off",
    stopping: "Finishing session — microphone off",
    pausing: "Pausing session — microphone off",
    resuming: "Continuing session — microphone off",
  };
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
      {context?.start.mode === "free_conversation" && (
        <p>
          Free conversation · {context.start.topic || context.title} ·{" "}
          {context.start.correction_style === "end_of_session"
            ? "Feedback at the end"
            : "Light immediate correction"}
        </p>
      )}
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
      <div className={`voice-state voice-state-${view.phase}`}>
        <strong aria-label="Microphone state">{phaseLabels[view.phase]}</strong>
        {recording && (
          <span aria-label="Recording elapsed time" aria-live="off">
            {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}
          </span>
        )}
      </div>
      <p role={view.phase === "error" ? "alert" : "status"} aria-live="polite">
        {view.message}
      </p>
      {p.status === "paused" && (
        <p className="hint">
          {p.activity?.complete
            ? "This activity is complete. Continue to the next activity or finish."
            : "This activity is paused at your saved step. Continue when ready."}
        </p>
      )}
      <div className="actions">
        <button
          disabled={!canTalk}
          aria-pressed={recording}
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
          {view.phase === "requesting"
            ? "Cancel microphone request"
            : hold
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
          disabled={
            p.status === "finished" ||
            ["loading", "stopping", "pausing", "resuming"].includes(
              view.phase,
            ) ||
            Boolean(view.controlPending)
          }
          onClick={() =>
            void (p.status === "paused"
              ? controller.current?.resume()
              : controller.current?.pause())
          }
        >
          {p.status === "paused" ? "Continue session" : "Pause session"}
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
          {view.hasUpload && view.controlPending !== "finish" && (
            <button
              className="secondary"
              onClick={() => void controller.current?.discard()}
            >
              Discard pending recording
            </button>
          )}
        </div>
      )}
      <Conversation
        presentation={p}
        token={grant.token}
        deferred={context?.start.correction_style === "end_of_session"}
        unauthorized={unauthorized}
      />
      <p className="hint">
        Your session is saved on the server. An unfinished recording stays on
        this device until its response is confirmed or you discard it. Teacher
        text remains available if audio cannot play.
      </p>
    </section>
  );
}
