import { api, ApiError } from "./api";
import type { Presentation } from "./api";
import { journal, journalKey } from "./voice-journal";
import type { Upload } from "./voice-journal";

export type VoicePhase =
  | "loading"
  | "ready"
  | "requesting"
  | "recording"
  | "saving"
  | "processing"
  | "playing"
  | "error"
  | "stopping";
export type VoiceView = {
  phase: VoicePhase;
  message: string;
  presentation: Presentation;
  pending: boolean;
  finishPending: boolean;
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
  private generation = 0;
  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private recordingTimer?: ReturnType<typeof setTimeout>;
  private released = false;
  private captureDiscarded = false;
  private captureEnded: number | null = null;
  private request: AbortController | null = null;
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
      finishPending: false,
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

  async initialize() {
    const operation = this.generation;
    try {
      const saved = await journal(this.key);
      if (this.disposed || operation !== this.generation) return;
      if (saved.finish) {
        await this.finish();
        return;
      }
      if (saved.upload) {
        const latest = await this.status();
        if (this.disposed || operation !== this.generation) return;
        this.accept(latest);
        if (latest.request_id === saved.upload.request_id) {
          await this.clearUpload(saved.upload.request_id);
          if (this.disposed || operation !== this.generation) return;
          this.update({
            phase: "ready",
            pending: false,
            message: "Your last response was saved. Play it when ready.",
          });
        } else {
          this.update({
            phase: "error",
            pending: true,
            message:
              "An unfinished recording is saved on this device. Recover its response or discard it before recording again.",
          });
        }
      } else this.update({ phase: "ready", message: "Ready when you are." });
    } catch (e) {
      if (operation === this.generation)
        this.fail(
          e,
          "Site storage is unavailable. Enable storage and reopen this session.",
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
      finishPending: false,
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
    this.generation++;
    this.cancelCapture();
    this.update({
      phase: "ready",
      message: "Recording discarded. Tap to start again.",
    });
  }
  private async saveAndSend(upload: Upload, operation: number) {
    try {
      const saved = await journal(this.key, (j) => ({ ...j, upload }));
      if (this.disposed || operation !== this.generation || saved.finish)
        return;
      this.update({ pending: true });
      await this.send(upload, operation);
    } catch (e) {
      if (operation === this.generation)
        this.fail(
          e,
          "Recording could not be saved. Free some site storage and record again.",
        );
    }
  }
  private async send(upload: Upload, operation: number) {
    this.update({
      phase: "processing",
      message: "Preparing the teacher’s response…",
      pending: true,
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
      if (this.disposed || operation !== this.generation) return;
      await this.clearUpload(upload.request_id);
      if (this.disposed || operation !== this.generation) return;
      this.accept(result);
      this.update({
        phase: "ready",
        pending: false,
        message: "Response saved. Play the teacher when ready.",
      });
      // Autoplay is optional. A visible Play control remains on rejection.
      await this.play();
    } catch (e) {
      if (!this.disposed && operation === this.generation)
        this.fail(
          e,
          "Response interrupted. Recover the saved response to retry this same recording safely.",
        );
    } finally {
      clearTimeout(timer);
      if (this.request === request) this.request = null;
    }
  }
  async recover() {
    if (this.disposed || !["ready", "error"].includes(this.view.phase)) return;
    this.stopPlayback();
    const operation = ++this.generation;
    this.update({
      phase: "processing",
      message: "Checking the saved response…",
    });
    try {
      const saved = await journal(this.key);
      if (this.disposed || operation !== this.generation) return;
      if (saved.finish || this.view.finishPending) {
        this.update({ phase: "error" });
        await this.finish();
        return;
      }
      const latest = await this.status();
      if (this.disposed || operation !== this.generation) return;
      this.accept(latest);
      if (!saved.upload) {
        this.update({
          phase: "ready",
          pending: false,
          message: "Current response loaded.",
        });
        return;
      }
      if (latest.request_id === saved.upload.request_id) {
        await this.clearUpload(saved.upload.request_id);
        if (this.disposed || operation !== this.generation) return;
        this.update({
          phase: "ready",
          pending: false,
          message:
            "Saved response recovered without another submission. Play it when ready.",
        });
      } else if (
        latest.revision === saved.upload.expected_revision &&
        latest.status === "active"
      ) {
        await this.send(saved.upload, operation);
      } else
        this.update({
          phase: "error",
          pending: true,
          message:
            "The session has moved on. Your recording was not resubmitted. Discard the pending recording to continue from the server’s current state.",
        });
    } catch (e) {
      if (operation === this.generation)
        this.fail(
          e,
          "Cannot reach the server. Keep the recording and recover when connected.",
        );
    }
  }
  async discard() {
    if (!["ready", "error"].includes(this.view.phase)) return;
    this.stopPlayback();
    const operation = ++this.generation;
    this.update({
      phase: "processing",
      message: "Discarding the local recording…",
    });
    try {
      const saved = await journal(this.key);
      if (this.disposed || operation !== this.generation) return;
      if (saved.finish) {
        this.update({
          phase: "error",
          message: "Finish is still pending. Recover it before continuing.",
        });
        return;
      }
      await journal(this.key, (j) => ({ ...j, upload: null }));
      if (this.disposed || operation !== this.generation) return;
      this.update({
        phase: "ready",
        pending: true,
        message:
          "Pending recording discarded from this device. Reload the server response before another turn.",
      });
      await this.recover();
    } catch (e) {
      if (operation === this.generation)
        this.fail(e, "Could not discard the recording. Try again.");
    }
  }
  async play() {
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
      finishPending: false,
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
    if (this.disposed || this.view.phase === "stopping") return;
    this.stopPlayback();
    this.cancelCapture();
    const operation = ++this.generation;
    this.update({
      phase: "stopping",
      finishPending: true,
      message: "Stopping… Your session will stay saved.",
      pending: true,
    });
    try {
      let saved = await journal(this.key, (j) => ({
        ...j,
        finish: j.finish || {
          request_id: crypto.randomUUID(),
          expected_revision: this.view.presentation.revision,
        },
      }));
      if (this.disposed || operation !== this.generation) return;
      for (let attempt = 0; attempt < 2; attempt++) {
        const latest = await this.status(false);
        if (this.disposed || operation !== this.generation) return;
        this.accept(latest);
        if (latest.status === "finished") {
          await journal(this.key, (j) => ({
            ...j,
            upload: null,
            finish: null,
          }));
          this.update({
            phase: "ready",
            pending: false,
            finishPending: false,
            message: "Session finished and saved.",
          });
          return;
        }
        if (saved.finish!.expected_revision !== latest.revision) {
          saved = await journal(this.key, (j) => ({
            ...j,
            finish: {
              request_id: crypto.randomUUID(),
              expected_revision: latest.revision,
            },
          }));
        }
        try {
          const result = await api<Presentation>(
            this.path() + "/controls",
            this.token,
            { ...saved.finish, operation: "finish" },
          );
          if (this.disposed || operation !== this.generation) return;
          await journal(this.key, (j) => ({
            ...j,
            upload: null,
            finish: null,
          }));
          this.accept(result);
          this.update({
            phase: "ready",
            pending: false,
            finishPending: false,
            message: "Session finished and saved.",
          });
          return;
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) continue;
          // The control can commit before speech preparation fails or its
          // response disappears. Read durable state without invoking speech.
          const committed = await this.status(false);
          if (this.disposed || operation !== this.generation) return;
          if (committed.status !== "finished") throw e;
          await journal(this.key, (j) => ({
            ...j,
            upload: null,
            finish: null,
          }));
          this.accept(committed);
          this.update({
            phase: "ready",
            pending: false,
            finishPending: false,
            message: "Session finished and saved.",
          });
          return;
        }
      }
      throw new Error("changed");
    } catch (e) {
      if (operation === this.generation)
        this.fail(
          e,
          "Finish is still pending. Recover when connected; the saved stop request will continue without resending your recording.",
        );
    }
  }
  dispose() {
    this.disposed = true;
    this.stopPlayback();
    this.cancelCapture();
  }
}
