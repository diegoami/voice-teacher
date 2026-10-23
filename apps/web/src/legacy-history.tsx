import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

type Entry = {
  archive_id: string;
  title: string;
  record_kind: string;
  source_label: string;
  source_date: string | null;
  source_sha256: string;
  counts: { proposed: number; unresolved: number; conflict: number };
  imports: string[];
};
type Detail = Entry & {
  text: string;
  supporting_groups: {
    import_id: string;
    observation_id: string;
    record_ids: string[];
    original_source: {
      source_id: string;
      course_id: string;
      lesson_id: string;
    };
    practice_source: {
      source_id: string;
      course_id: string;
      lesson_id: string;
    };
  }[];
};
const labels: Record<string, string> = {
  transcript: "Transcript (as labelled in the source)",
  summary: "Session summary or notes — no separate transcript identified",
  session_record: "Session record — transcript not identified",
  tracker: "Tracker reference — not a session transcript",
  queue: "Repetition queue reference — not a session transcript",
};
export function LegacyHistory({
  token,
  unauthorized,
}: {
  token: string;
  unauthorized: (e: ApiError) => void;
}) {
  const [listing, setListing] = useState<{
    configured: boolean;
    records: Entry[];
  } | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const active = useRef(true),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function load(id: string | null) {
    if (running.current) return;
    running.current = true;
    setSelected(id);
    setBusy(true);
    setError("");
    setDetail(null);
    try {
      if (id) {
        const value = await api<Detail>(
          "/legacy-history/" + encodeURIComponent(id),
          token,
        );
        if (active.current) setDetail(value);
      } else {
        const value = await api<{ configured: boolean; records: Entry[] }>(
          "/legacy-history",
          token,
        );
        if (active.current) setListing(value);
      }
    } catch (e) {
      if (!active.current) return;
      if (e instanceof ApiError && e.status === 401) unauthorized(e);
      setError(
        "Legacy history unavailable. Retained records have not been changed; retry when connected.",
      );
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <section className="legacy-history" aria-labelledby="legacy-history">
      <h3 id="legacy-history">Legacy session archive</h3>
      <p>
        Original records from outside this app. These are separate from sessions
        practised here.
      </p>
      <button
        className="secondary"
        disabled={busy}
        onClick={() => void load(null)}
      >
        {listing ? "Refresh legacy archive" : "Load legacy archive"}
      </button>
      {busy && <p role="status">Loading retained legacy record…</p>}
      {error && (
        <div>
          <p role="alert">{error}</p>
          <button disabled={busy} onClick={() => void load(selected)}>
            Retry legacy history
          </button>
        </div>
      )}
      {listing && (
        <>
          {!listing.configured ? (
            <p>The legacy archive is not configured on this server.</p>
          ) : !listing.records.length ? (
            <p>No retained legacy records are available for this learner.</p>
          ) : (
            <>
              <p className="hint">
                Only files retained by reviewed imports are listed. Other
                historical sessions have not been imported. A source labelled as
                a transcript may be partial; summaries and queue references do
                not replace missing conversations.
              </p>
              {[true, false].map((sessions) => (
                <div key={String(sessions)}>
                  <h4>
                    {sessions
                      ? "Legacy sessions"
                      : "Supporting tracker and queue references"}
                  </h4>
                  <ul className="sessions">
                    {listing.records
                      .filter(
                        (row) =>
                          sessions ===
                          !["tracker", "queue"].includes(row.record_kind),
                      )
                      .map((row) => (
                        <li key={row.archive_id}>
                          <div>
                            <strong>{row.title}</strong>
                            <small>{labels[row.record_kind]}</small>
                            {row.source_date && (
                              <small>
                                Date from source label:{" "}
                                <time dateTime={row.source_date}>
                                  {row.source_date}
                                </time>
                              </small>
                            )}
                          </div>
                          <button
                            className="secondary"
                            disabled={busy}
                            onClick={() => void load(row.archive_id)}
                          >
                            Read {row.title}
                          </button>
                        </li>
                      ))}
                  </ul>
                </div>
              ))}
            </>
          )}
        </>
      )}
      {detail && (
        <article aria-labelledby="legacy-detail">
          <h4 id="legacy-detail">{detail.title}</h4>
          <p>{labels[detail.record_kind]}</p>
          <p>Original source label: {detail.source_label}</p>
          <p className="hint">
            Retained mapping: {detail.counts.proposed} proposed records ·{" "}
            {detail.counts.unresolved} unresolved · {detail.counts.conflict}{" "}
            conflicting. Reading this text does not settle unresolved mappings
            or add practice evidence.
          </p>
          <details>
            <summary>Source provenance and supporting groups</summary>
            <p className="archive-hash">
              Original SHA-256: {detail.source_sha256}
            </p>
            {detail.imports.map((id) => (
              <p className="archive-hash" key={id}>
                Retained import: {id}
              </p>
            ))}
            {detail.supporting_groups.map((group) => (
              <div key={group.import_id + group.observation_id}>
                <p className="archive-hash">
                  Selected legacy group: {group.observation_id}
                </p>
                <p>
                  Original: {group.original_source.source_id} /{" "}
                  {group.original_source.course_id} /{" "}
                  {group.original_source.lesson_id}
                </p>
                <p>
                  Practice: {group.practice_source.source_id} /{" "}
                  {group.practice_source.course_id} /{" "}
                  {group.practice_source.lesson_id}
                </p>
                <p className="archive-hash">
                  Supporting records: {group.record_ids.join(", ")}
                </p>
              </div>
            ))}
          </details>
          <pre className="legacy-text">{detail.text}</pre>
        </article>
      )}
    </section>
  );
}
