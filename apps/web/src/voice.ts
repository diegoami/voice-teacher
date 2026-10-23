import { api, ApiError } from "./api";
import type { Presentation, Receipt } from "./api";
import { journal, journalKey } from "./voice-journal";
import type { Upload, Journal, ControlOperation } from "./voice-journal";

export type VoicePhase =
  | "loading"
  | "ready"
  | "requesting"
  | "recording"
  | "saving"
  | "processing"
  | "playing"
  | "error"
  | "stopping"
  | "pausing"
  | "resuming";
export type VoiceView = {
  phase: VoicePhase;
  message: string;
  presentation: Presentation;
  pending: boolean;
  controlPending: ControlOperation | null;
  hasUpload: boolean;
};
const formats = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];
const maxBytes = 8 * 1024 * 1024,
  maxDuration = 60_000,
  minDuration = 250;

export class VoiceController {
  view: VoiceView;
  private key: string;
  private disposed = false;
  private visible = true;
  private generation = 0;
  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private recordingTimer?: ReturnType<typeof setTimeout>;
  private released = false;
  private captureDiscarded = false;
  private captureEnded: number | null = null;
  private request: AbortController | null = null;
  private saving: Promise<Journal> | null = null;
  private player: HTMLAudioElement | null = null;
  private playbackURL: string | null = null;
  private cancelPlayback: (() => void) | null = null;

  constructor(
    initial: Presentation,
    private token: string,
    learner: string,
    private changed: (view: VoiceView) => void,
    private received: (p: Presentation) => void,
    private unauthorized: (error: ApiError) => void,
  ) {
    this.key = journalKey(learner, initial.session_id);
    this.view = {
      phase: "loading",
      message: "Checking saved response…",
      presentation: initial,
      pending: false,
      controlPending: null,
      hasUpload: false,
    };
  }
  private update(patch: Partial<VoiceView>) {
    this.view = { ...this.view, ...patch };
    if (!this.disposed) this.changed(this.view);
  }
  private accept(presentation: Presentation) {
    this.view.presentation = presentation;
    if (!this.disposed) this.received(presentation);
  }
  private path() {
    return "/sessions/" + encodeURIComponent(this.view.presentation.session_id);
  }
  private fail(error: unknown, fallback: string) {
    if (this.disposed) return;
    if (error instanceof ApiError && error.status === 401)
      this.unauthorized(error);
    this.update({
      phase: "error",
      message: error instanceof ApiError ? error.message : fallback,
    });
  }
  private async status(prepareAudio = true) {
    return api<Presentation>(
      this.path() + (prepareAudio ? "" : "?prepare_audio=false"),
      this.token,
    );
  }

  private pendingInfo(saved: Journal) {
    return {
      pending: Boolean(saved.upload || saved.control),
      hasUpload: Boolean(saved.upload),
      controlPending: saved.control?.operation ?? null,
    };
  }
  private async receipt(id: string): Promise<Receipt | null> {
    try {
      return await api<Receipt>(
        this.path() + "/requests/" + encodeURIComponent(id),
        this.token,
      );
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  }
  private accepted(
    receipt: Receipt | null,
    latest: Presentation,
    upload: Upload,
  ) {
    return (
      (receipt?.request_id === upload.request_id &&
        receipt.status === "ready" &&
        receipt.revision === upload.expected_revision + 1) ||
      (latest.request_id === upload.request_id &&
        latest.revision === upload.expected_revision + 1)
    );
  }
  async initialize() {
    const operation = this.generation;
    try {
      const saved = await journal(this.key);
      if (this.disposed || operation !== this.generation) return;
      this.update(this.pendingInfo(saved));
      if (saved.control) {
        await this.runControl(saved.control.operation);
        return;
      }
      if (!saved.upload) {
        this.update({ phase: "ready", message: "Ready when you are." });
        return;
      }
      const receipt = await this.receipt(saved.upload.request_id);
      const latest = await this.status(false);
      if (this.disposed || operation !== this.generation) return;
      this.accept(latest);
      if (
        this.accepted(receipt, latest, saved.upload) ||
        receipt?.status === "cancelled"
      ) {
        const remaining = await this.clearUpload(saved.upload.request_id);
        if (this.disposed || operation !== this.generation) return;
        this.update({
          ...this.pendingInfo(remaining),
          phase: "ready",
          message:
            receipt?.status === "cancelled"
              ? "The previous recording was cancelled. Current session loaded."
              : "Your last response was saved. Play it when ready.",
        });
        await this.prepareLatest(operation, this.view.message);
      } else
        this.update({
          phase: "error",
          message:
            "An unfinished recording is saved on this device. Recover its response or discard it before recording again.",
        });
    } catch (e) {
      if (operation === this.generation)
        this.fail(
          e,
          "Site storage or server unavailable. Reopen this session when connected.",
        );
    }
  }
  private async prepareLatest(operation: number, message: string) {
    try {
      const prepared = await this.status();
      if (this.disposed || operation !== this.generation) return;
      this.accept(prepared);
      this.update({ phase: "ready", message });
    } catch (e) {
      if (operation === this.generation)
        this.fail(
          e,
          "Your response is saved. Teacher audio is not ready; read the text or recover again.",
        );
    }
  }
  private async clearUpload(id: string) {
    return journal(this.key, (j) => ({
      ...j,
      upload: j.upload?.request_id === id ? null : j.upload,
    }));
  }
  private releaseStream() {
    clearTimeout(this.recordingTimer);
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }
  private cancelCapture() {
    this.released = true;
    this.captureDiscarded = true;
    if (this.recorder && this.recorder.state !== "inactive")
      this.recorder.stop();
    this.recorder = null;
    this.releaseStream();
  }
  setVisible(visible: boolean) {
    this.visible = visible;
    if (!visible && this.view.phase === "playing") this.stopPlayback();
  }
  stopPlayback() {
    this.generation++;
    this.request?.abort();
    this.request = null;
    this.player?.pause();
    this.player = null;
    this.cancelPlayback?.();
    this.cancelPlayback = null;
    if (this.playbackURL) URL.revokeObjectURL(this.playbackURL);
    this.playbackURL = null;
    if (this.view.phase === "playing")
      this.update({
        phase: "ready",
        message: "Playback stopped. Replay it or take your turn.",
      });
  }
  async startRecording() {
    if (
      this.disposed ||
      this.view.pending ||
      this.view.presentation.status !== "active" ||
      !["ready", "error", "playing"].includes(this.view.phase)
    )
      return;
    this.stopPlayback();
    const operation = ++this.generation;
    this.released = false;
    this.captureDiscarded = false;
    this.captureEnded = null;
    this.update({
      phase: "requesting",
      controlPending: null,
      hasUpload: false,
      message: "Allow microphone access to speak. Tap again to cancel.",
    });
    let stream: MediaStream | null = null;
    try {
      if (!isSecureContext || !navigator.mediaDevices?.getUserMedia)
        throw new Error("secure");
      if (typeof MediaRecorder === "undefined") throw new Error("format");
      const mimeType = formats.find((type) =>
        MediaRecorder.isTypeSupported(type),
      );
      if (!mimeType) throw new Error("format");
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (this.disposed || operation !== this.generation || this.released) {
        stream.getTracks().forEach((track) => track.stop());
        if (!this.disposed && operation === this.generation)
          this.update({
            phase: "ready",
            message: "Recording cancelled. Tap to try again.",
          });
        return;
      }
      this.stream = stream;
      const recorder = new MediaRecorder(stream, { mimeType });
      this.recorder = recorder;
      const chunks: Blob[] = [];
      let bytes = 0;
      const began = performance.now();
      recorder.ondataavailable = (e) => {
        if (this.disposed || operation !== this.generation) return;
        if (!this.captureDiscarded && e.data.size) {
          chunks.push(e.data);
          bytes += e.data.size;
        }
        if (bytes > maxBytes) {
          this.cancelCapture();
          this.update({
            phase: "error",
            message: "Recording is too large. Try a shorter answer.",
          });
        }
      };
      recorder.onerror = () => {
        if (this.disposed || operation !== this.generation) return;
        this.cancelCapture();
        this.update({
          phase: "error",
          message:
            "The microphone stopped unexpectedly. Check it and record again.",
        });
      };
      recorder.onstop = () => {
        if (this.recorder === recorder) this.recorder = null;
        if (this.stream === stream) this.releaseStream();
        else stream!.getTracks().forEach((track) => track.stop());
        if (
          this.disposed ||
          operation !== this.generation ||
          this.captureDiscarded
        )
          return;
        const recording = new Blob(chunks, {
          type: recorder.mimeType || mimeType,
        });
        if (
          !recording.size ||
          (this.captureEnded ?? performance.now()) - began < minDuration
        ) {
          this.update({
            phase: "error",
            message:
              "No usable speech was recorded. Speak a little longer and record again.",
          });
          return;
        }
        const media_type = recording.type.split(";", 1)[0].toLowerCase();
        if (
          !["audio/webm", "audio/ogg", "audio/mp4", "audio/wav"].includes(
            media_type,
          )
        ) {
          this.update({
            phase: "error",
            message:
              "This recording format is unsupported. Try another supported browser.",
          });
          return;
        }
        const upload: Upload = {
          request_id: crypto.randomUUID(),
          expected_revision: this.view.presentation.revision,
          recording,
          media_type,
        };
        this.update({
          phase: "saving",
          message: "Saving your recording for a safe retry…",
        });
        void this.saveAndSend(upload, operation);
      };
      recorder.start(1000);
      this.recordingTimer = setTimeout(() => this.endRecording(), maxDuration);
      this.update({
        phase: "recording",
        message: "Listening… Tap to send your answer.",
      });
    } catch (e) {
      stream?.getTracks().forEach((track) => track.stop());
      if (this.disposed || operation !== this.generation) return;
      const name = e instanceof Error ? e.name : "";
      const reason = e instanceof Error ? e.message : "";
      this.update({
        phase: "error",
        message:
          reason === "secure"
            ? "Microphone access needs HTTPS or localhost. Open your secure server address and try again."
            : reason === "format"
              ? "This browser cannot record a supported format. Try a current Android or desktop browser."
              : name === "NotAllowedError"
                ? "Microphone permission was denied. Allow it in your browser site settings, then tap to try again."
                : "Microphone unavailable. Check your input device and tap to try again.",
      });
    }
  }
  endRecording() {
    this.released = true;
    if (this.recorder?.state === "recording") {
      this.captureEnded = performance.now();
      this.update({ phase: "saving", message: "Finishing your recording…" });
      this.recorder.stop();
    }
  }
  cancelRecording() {
    if (this.disposed || !["recording", "requesting"].includes(this.view.phase))
      return;
    this.generation++;
    this.cancelCapture();
    this.update({
      phase: "ready",
      message: "Recording discarded. Tap to start again.",
    });
  }
  private async saveAndSend(upload: Upload, operation: number) {
    const saving = journal(this.key, (j) => ({ ...j, upload }));
    this.saving = saving;
    try {
      const saved = await saving;
      if (this.disposed || operation !== this.generation || saved.control)
        return;
      this.update({ pending: true, hasUpload: true });
      await this.send(upload, operation);
    } catch (e) {
      if (operation === this.generation)
        this.fail(
          e,
          "Recording could not be saved. Free some site storage and record again.",
        );
    } finally {
      if (this.saving === saving) this.saving = null;
    }
  }
  private async send(
    upload: Upload,
    operation: number,
    managed = false,
  ): Promise<Presentation | null> {
    this.update({
      phase:
        managed && this.view.controlPending === "pause"
          ? "pausing"
          : managed && this.view.controlPending === "resume"
            ? "resuming"
            : "processing",
      message: managed
        ? "Saving the unfinished response…"
        : "Preparing the teacher’s response…",
      pending: true,
      hasUpload: true,
    });
    const request = new AbortController();
    this.request = request;
    const timer = setTimeout(() => request.abort(), 45000);
    try {
      const query = new URLSearchParams({
        request_id: upload.request_id,
        expected_revision: String(upload.expected_revision),
      });
      const response = await fetch(
        "/api/v1" + this.path() + "/audio?" + query,
        {
          method: "POST",
          headers: {
            Authorization: "Bearer " + this.token,
            "Content-Type": upload.media_type,
          },
          body: upload.recording,
          credentials: "omit",
          redirect: "error",
          cache: "no-store",
          signal: request.signal,
        },
      );
      if (!response.ok) throw new ApiError(response.status);
      const result: Presentation = await response.json();
      if (
        result.session_id !== this.view.presentation.session_id ||
        result.request_id !== upload.request_id ||
        result.revision !== upload.expected_revision + 1
      )
        throw new Error("unexpected response identity");
      if (this.disposed || operation !== this.generation) return null;
      const remaining = await this.clearUpload(upload.request_id);
      if (this.disposed || operation !== this.generation) return null;
      this.accept(result);
      this.update(this.pendingInfo(remaining));
      if (!managed) {
        this.update({
          phase: "ready",
          message: "Response saved. Play the teacher when ready.",
        });
        // Autoplay is optional. A visible Play control remains on rejection.
        await this.play();
      }
      return result;
    } catch (e) {
      if (managed) throw e;
      if (!this.disposed && operation === this.generation)
        this.fail(
          e,
          "Response interrupted. Recover the saved response to retry this same recording safely.",
        );
      return null;
    } finally {
      clearTimeout(timer);
      if (this.request === request) this.request = null;
    }
  }
  private async drainUpload(
    upload: Upload,
    operation: number,
  ): Promise<Presentation | null> {
    let receipt = await this.receipt(upload.request_id);
    let latest = await this.status(false);
    if (this.disposed || operation !== this.generation) return null;
    if (
      !this.accepted(receipt, latest, upload) &&
      receipt?.status !== "cancelled" &&
      (latest.revision !== upload.expected_revision ||
        latest.status !== "active")
    )
      receipt = await this.receipt(upload.request_id); // It may have committed between the two reads.
    if (
      this.accepted(receipt, latest, upload) ||
      receipt?.status === "cancelled"
    ) {
      if (
        receipt?.revision !== null &&
        receipt?.revision !== undefined &&
        latest.revision < receipt.revision
      )
        latest = await this.status(false);
      const remaining = await this.clearUpload(upload.request_id);
      if (this.disposed || operation !== this.generation) return null;
      this.accept(latest);
      this.update(this.pendingInfo(remaining));
      return latest;
    }
    if (
      latest.revision !== upload.expected_revision ||
      latest.status !== "active"
    ) {
      this.accept(latest);
      throw new ApiError(409);
    }
    try {
      return await this.send(upload, operation, true);
    } catch (e) {
      // A synthesis failure can follow a committed turn; acknowledge its
      // receipt before any pause, and never re-upload it under a fresh ID.
      receipt = await this.receipt(upload.request_id);
      latest = await this.status(false);
      if (this.disposed || operation !== this.generation) return null;
      if (!this.accepted(receipt, latest, upload)) throw e;
      const remaining = await this.clearUpload(upload.request_id);
      if (this.disposed || operation !== this.generation) return null;
      this.accept(latest);
      this.update(this.pendingInfo(remaining));
      return latest;
    }
  }
  async recover() {
    if (this.disposed || !["ready", "error"].includes(this.view.phase)) return;
    this.stopPlayback();
    const operation = ++this.generation;
    this.update({ phase: "processing", message: "Checking saved progress…" });
    try {
      const saved = await journal(this.key);
      if (this.disposed || operation !== this.generation) return;
      this.update(this.pendingInfo(saved));
      if (saved.control) {
        this.update({ phase: "error" });
        await this.runControl(saved.control.operation);
        return;
      }
      if (saved.upload) {
        if (!(await this.drainUpload(saved.upload, operation))) return;
      } else {
        const latest = await this.status(false);
        if (this.disposed || operation !== this.generation) return;
        this.accept(latest);
      }
      await this.prepareLatest(
        operation,
        "Current response loaded. Play the teacher when ready.",
      );
    } catch (e) {
      if (operation === this.generation)
        this.fail(
          e,
          "Progress is still pending. Recover when connected, or discard only the local recording.",
        );
    }
  }
  async discard() {
    if (
      this.disposed ||
      !["ready", "error"].includes(this.view.phase) ||
      this.view.controlPending === "finish"
    )
      return;
    this.stopPlayback();
    const operation = ++this.generation;
    this.update({
      phase: "processing",
      message: "Discarding the local recording…",
    });
    try {
      const saved = await journal(this.key, (j) => ({ ...j, upload: null }));
      if (this.disposed || operation !== this.generation) return;
      this.update({
        ...this.pendingInfo(saved),
        phase: "ready",
        pending: true,
        message: "Local recording discarded. Checking current server progress…",
      });
      await this.recover();
    } catch (e) {
      if (operation === this.generation)
        this.fail(e, "Could not discard the recording. Try again.");
    }
  }
  async play() {
    if (!this.visible) return;
    if (
      this.disposed ||
      this.view.pending ||
      !["ready", "error", "playing"].includes(this.view.phase)
    )
      return;
    this.stopPlayback();
    const operation = ++this.generation;
    this.update({
      phase: "playing",
      controlPending: null,
      hasUpload: false,
      message: "Playing the teacher…",
    });
    try {
      for (const id of this.view.presentation.audio_ids) {
        const request = new AbortController();
        this.request = request;
        const timer = setTimeout(() => request.abort(), 45000);
        let response: Response;
        try {
          response = await fetch(
            "/api/v1" +
              this.path() +
              "/audio/" +
              encodeURIComponent(id) +
              "?revision=" +
              this.view.presentation.revision,
            {
              headers: { Authorization: "Bearer " + this.token },
              credentials: "omit",
              redirect: "error",
              cache: "no-store",
              signal: request.signal,
            },
          );
          if (!response.ok) throw new ApiError(response.status);
          const blob = await response.blob();
          if (this.disposed || operation !== this.generation) return;
          this.playbackURL = URL.createObjectURL(blob);
        } finally {
          clearTimeout(timer);
          if (this.request === request) this.request = null;
        }
        const player = new Audio(this.playbackURL!);
        this.player = player;
        let complete!: () => void;
        const ended = new Promise<void>((resolve, reject) => {
          complete = resolve;
          player.onended = resolve as () => void;
          player.onerror = () => reject(new Error("playback"));
        });
        this.cancelPlayback = complete;
        await Promise.all([player.play(), ended]);
        if (this.disposed || operation !== this.generation) return;
        URL.revokeObjectURL(this.playbackURL!);
        this.playbackURL = null;
        this.player = null;
        this.cancelPlayback = null;
      }
      this.update({ phase: "ready", message: "Your turn when you are ready." });
    } catch (e) {
      if (this.disposed || operation !== this.generation) return;
      this.stopPlayback();
      if (e instanceof ApiError && e.status === 401) this.unauthorized(e);
      this.update({
        phase: "error",
        message:
          "Playback could not start or was interrupted. Tap Play teacher to try again, or read the teacher text.",
      });
    }
  }
  async finish() {
    await this.runControl("finish");
  }
  async pause() {
    await this.runControl("pause");
  }
  async resume() {
    await this.runControl("resume");
  }
  private reached(operation: ControlOperation, p: Presentation) {
    return (
      p.status === "finished" ||
      p.status ===
        (operation === "pause"
          ? "paused"
          : operation === "resume"
            ? "active"
            : "finished")
    );
  }
  private async acknowledgeControl(
    saved: Journal,
    latest: Presentation,
    operation: number,
  ) {
    const id = saved.control!.request_id;
    const remaining = await journal(this.key, (j) => ({
      ...j,
      control: j.control?.request_id === id ? null : j.control,
      upload: latest.status === "finished" ? null : j.upload,
    }));
    if (this.disposed || operation !== this.generation) return;
    this.accept(latest);
    this.update({
      ...this.pendingInfo(remaining),
      phase: "ready",
      message:
        latest.status === "finished"
          ? "Session finished and saved."
          : latest.status === "paused"
            ? "Session paused and saved. Continue when ready."
            : "Session continued from saved progress.",
    });
  }
  private async runControl(kind: ControlOperation) {
    if (
      this.disposed ||
      (["stopping", "pausing", "resuming"].includes(this.view.phase) &&
        kind !== "finish") ||
      (this.view.phase === "stopping" && kind === "finish")
    )
      return;
    this.stopPlayback();
    this.cancelCapture();
    const operation = ++this.generation;
    this.update({
      phase:
        kind === "finish"
          ? "stopping"
          : kind === "pause"
            ? "pausing"
            : "resuming",
      controlPending: kind,
      pending: true,
      message:
        kind === "finish"
          ? "Stopping… Your session will stay saved."
          : kind === "pause"
            ? "Saving the current response before pausing…"
            : "Continuing your saved activity…",
    });
    try {
      // A Send may still be writing its Blob. Controls must observe that write
      // before draining it, or a late write could strand an unsubmitted turn.
      if (this.saving) await this.saving;
      if (this.disposed || operation !== this.generation) return;
      let saved = await journal(this.key, (j) =>
        operation !== this.generation
          ? j
          : {
              ...j,
              control:
                j.control?.operation === kind
                  ? j.control
                  : {
                      request_id: crypto.randomUUID(),
                      expected_revision: this.view.presentation.revision,
                      operation: kind,
                    },
            },
      );
      if (this.disposed || operation !== this.generation) return;
      this.update(this.pendingInfo(saved));
      if (kind !== "finish" && saved.upload) {
        if (!(await this.drainUpload(saved.upload, operation))) return;
        saved = await journal(this.key);
        if (this.disposed || operation !== this.generation) return;
      }
      for (let attempt = 0; attempt < 2; attempt++) {
        const latest = await this.status(false);
        if (this.disposed || operation !== this.generation) return;
        this.accept(latest);
        if (this.reached(kind, latest)) {
          await this.acknowledgeControl(saved, latest, operation);
          return;
        }
        if (saved.control!.expected_revision !== latest.revision) {
          saved = await journal(this.key, (j) =>
            operation !== this.generation
              ? j
              : {
                  ...j,
                  control: {
                    request_id: crypto.randomUUID(),
                    expected_revision: latest.revision,
                    operation: kind,
                  },
                },
          );
          if (this.disposed || operation !== this.generation) return;
        }
        try {
          const result = await api<Presentation>(
            this.path() + "/controls",
            this.token,
            saved.control,
          );
          if (this.disposed || operation !== this.generation) return;
          if (!this.reached(kind, result)) throw new ApiError(409);
          await this.acknowledgeControl(saved, result, operation);
          return;
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) continue;
          const committed = await this.status(false);
          if (this.disposed || operation !== this.generation) return;
          if (!this.reached(kind, committed)) throw e;
          await this.acknowledgeControl(saved, committed, operation);
          return;
        }
      }
      throw new ApiError(409);
    } catch (e) {
      if (operation === this.generation)
        this.fail(
          e,
          kind === "finish"
            ? "Finish is still pending. Recover when connected; your saved stop request will continue without resending the recording."
            : "Pause or continue is still pending. Your current turn and control are saved. Recover when connected, or finish without waiting.",
        );
    }
  }
  dispose() {
    this.disposed = true;
    this.stopPlayback();
    this.cancelCapture();
  }
}
