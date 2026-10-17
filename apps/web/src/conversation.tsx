import { useEffect, useState } from "react";
import { api, ApiError, type Presentation } from "./api";

type Turn = { turn_id: string; role: string; text: string };
type Feedback = {
  event_id: string;
  turn: { turn_id: string };
  correction: boolean;
  preferred: string | null;
  reason: string | null;
  recognition_uncertain: boolean;
  superseded: boolean;
};
type Page = {
  session_id: string;
  rows: Feedback[];
  next_offset: number | null;
};

// These reads never participate in accepting a turn or controlling playback.
export function Conversation({
  presentation: p,
  token,
  deferred,
  unauthorized,
}: {
  presentation: Presentation;
  token: string;
  deferred: boolean;
  unauthorized: (e: ApiError) => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    const path = "/sessions/" + encodeURIComponent(p.session_id);
    setLoading(true);
    setErrors([]);
    setFeedback([]);
    const failed = (e: unknown, message: string) => {
      if (!active) return;
      if (e instanceof ApiError && e.status === 401) unauthorized(e);
      setErrors((previous) => [...previous, message]);
    };
    const transcript = api<Turn[]>(
      path + "/transcript?revision=" + p.revision,
      token,
    )
      .then((rows) => {
        if (!Array.isArray(rows)) throw new Error("Invalid transcript");
        if (active) setTurns(rows);
      })
      .catch((e) =>
        failed(
          e,
          "Conversation unavailable. Your accepted answers are saved; retry loading the record.",
        ),
      );
    const corrections = async () => {
      if (deferred && p.status !== "finished") return;
      const rows: Feedback[] = [];
      let offset: number | null = 0;
      while (offset !== null && active) {
        const page: Page = await api<Page>(
          path + "/evidence?offset=" + offset,
          token,
        );
        if (
          page.session_id !== p.session_id ||
          !Array.isArray(page.rows) ||
          (page.next_offset !== null &&
            (!Number.isSafeInteger(page.next_offset) ||
              page.next_offset <= offset))
        )
          throw new Error("Invalid evidence page");
        rows.push(...page.rows);
        offset = page.next_offset;
      }
      if (active)
        setFeedback(
          rows.filter(
            (row) =>
              row.correction &&
              !row.recognition_uncertain &&
              !row.superseded &&
              row.preferred,
          ),
        );
    };
    void Promise.all([
      transcript,
      corrections().catch((e) =>
        failed(
          e,
          "Written feedback unavailable. Retry to load saved feedback.",
        ),
      ),
    ]).then(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
    // Authorization callback identity must not refetch after every voice phase.
    // SessionScreen is keyed by authenticated learner and session.
  }, [p.session_id, p.revision, p.status, token, deferred, retry]);
  return (
    <section
      className="conversation"
      aria-labelledby="conversation"
      aria-live="off"
    >
      <h3 id="conversation">Session conversation</h3>
      <p className="hint">
        Recognized answers show what speech recognition understood. They do not
        assess pronunciation or prove correctness.
      </p>
      {loading && <p>Loading saved conversation…</p>}
      {errors.map((message) => (
        <p key={message}>{message}</p>
      ))}
      {errors.length > 0 && (
        <button
          className="secondary"
          disabled={loading}
          onClick={() => setRetry((value) => value + 1)}
        >
          Retry conversation
        </button>
      )}
      {!loading && !errors.length && !turns.length && (
        <p>No saved conversation yet.</p>
      )}
      {deferred && p.status !== "finished" && (
        <p className="hint">
          Written corrections will appear when you finish, as selected.
        </p>
      )}
      <ol>
        {turns.map((turn) => (
          <li
            key={turn.turn_id}
            className={
              turn.role === "learner" ? "learner-turn" : "teacher-turn"
            }
          >
            <strong>
              {turn.role === "learner"
                ? "Recognized answer (speech recognition)"
                : "Teacher"}
            </strong>
            <p>{turn.text}</p>
            {feedback
              .filter((row) => row.turn.turn_id === turn.turn_id)
              .map((row) => (
                <div className="written-feedback" key={row.event_id}>
                  <strong>Written correction</strong>
                  <p>{row.preferred}</p>
                  {row.reason && <p>{row.reason}</p>}
                </div>
              ))}
          </li>
        ))}
      </ol>
    </section>
  );
}
