import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

type Policy = { retention_days: number };
type Recording = {
  recording_id: string;
  request_id: string;
  media_type: string;
  created_at: number;
  expires_at: number | null;
  state: "retained" | "not_retained" | "expired" | "deleted" | "unavailable";
};
type Props = { token: string; unauthorized: (error: ApiError) => void };

function useAction(unauthorized: Props["unauthorized"]) {
  const active = useRef(true),
    running = useRef(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function action(work: () => Promise<void>) {
    if (running.current || !active.current) return;
    running.current = true;
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      if (!active.current) return;
      if (e instanceof ApiError && e.status === 401) unauthorized(e);
      setError(
        "Recording settings or status could not be confirmed. Reload to check the server's saved state.",
      );
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  return { active, busy, error, action };
}

export function RetentionPanel({ token, unauthorized }: Props) {
  const { active, busy, error, action } = useAction(unauthorized);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [days, setDays] = useState(0),
    [message, setMessage] = useState("");
  async function load() {
    const value = await api<Policy>("/recording-retention", token);
    if (active.current) {
      setPolicy(value);
      setDays(value.retention_days);
      setMessage("");
    }
  }
  async function update(value = days) {
    const saved = await api<Policy>("/recording-retention", token, {
      retention_days: value,
    });
    if (active.current) {
      setPolicy(saved);
      setDays(saved.retention_days);
      setMessage(
        saved.retention_days
          ? "Recording setting saved for future uploads."
          : "Saving is off. Previously retained recordings have been deleted.",
      );
    }
  }
  return (
    <section className="privacy" aria-label="Recording privacy">
      <details>
        <summary>Recording privacy</summary>
        <p>
          Recording saving is off by default. This setting controls private
          copies on your server. Practice history and transcripts remain saved
          separately.
        </p>
        <p>
          Your device keeps a pending recording for retry until the upload is
          acknowledged or cancelled. Speech recognition still sends the
          recording to the configured speech provider.
        </p>
        <button
          className="secondary"
          disabled={busy}
          onClick={() => void action(load)}
        >
          {policy ? "Reload recording settings" : "Load recording settings"}
        </button>
        {error && <p role="alert">{error}</p>}
        {policy && (
          <>
            <p>
              Current server setting:{" "}
              {policy.retention_days
                ? `save for ${policy.retention_days} ${policy.retention_days === 1 ? "day" : "days"}`
                : "saving off"}
              .
            </p>
            <label>
              Save new recordings for
              <select
                value={days}
                disabled={busy}
                onChange={(e) => {
                  setDays(Number(e.target.value));
                  setMessage("");
                }}
              >
                <option value={0}>Off — delete saved recordings</option>
                <option value={1}>1 day</option>
                <option value={7}>7 days</option>
                <option value={30}>30 days</option>
                {![0, 1, 7, 30].includes(policy.retention_days) && (
                  <option value={policy.retention_days}>
                    {policy.retention_days} days
                  </option>
                )}
              </select>
            </label>
            <button disabled={busy} onClick={() => void action(() => update())}>
              Apply recording setting
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => void action(() => update(0))}
            >
              Delete saved recordings and turn saving off
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  await api("/recording-retention/cleanup", token, {});
                  if (active.current)
                    setMessage(
                      "Expired recordings cleaned up; practice history is retained.",
                    );
                })
              }
            >
              Clean up expired recordings
            </button>
            <p>
              Expiry blocks access immediately. The server removes expired files
              during use and checks every minute while running. Increasing the
              duration does not extend existing copies; turning saving off
              deletes them immediately. Deleted or expired audio cannot be
              recovered by retrying an old upload.
            </p>
          </>
        )}
        {message && <p role="status">{message}</p>}
      </details>
    </section>
  );
}

export function RecordingHistory({
  token,
  unauthorized,
  session,
}: Props & { session: string }) {
  const { active, busy, error, action } = useAction(unauthorized);
  const [rows, setRows] = useState<Recording[] | null>(null);
  const labels: Record<Recording["state"], string> = {
    retained: "Saved privately",
    not_retained: "Not saved",
    expired: "Expired — audio removed",
    deleted: "Deleted — saving turned off",
    unavailable: "Audio unavailable",
  };
  return (
    <section aria-label="Saved recording status">
      <h4>Recordings</h4>
      <button
        className="secondary"
        disabled={busy}
        onClick={() =>
          void action(async () => {
            const value = await api<Recording[]>(
              "/sessions/" + encodeURIComponent(session) + "/recordings",
              token,
            );
            if (active.current) setRows(value);
          })
        }
      >
        {rows ? "Refresh recording status" : "Load recording status"}
      </button>
      {error && <p role="alert">{error}</p>}
      {rows && !rows.length && (
        <p>No recording metadata is saved for this session.</p>
      )}
      {rows && rows.length > 0 && (
        <ul>
          {rows.map((row) => (
            <li key={row.recording_id}>
              {labels[row.state]} · recorded{" "}
              {new Date(row.created_at * 1000).toLocaleString()}
              {row.state === "retained" && row.expires_at !== null && (
                <>
                  {" "}
                  · expires {new Date(row.expires_at * 1000).toLocaleString()}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="hint">
        Recording cleanup keeps the session transcript and practice evidence.
      </p>
    </section>
  );
}
