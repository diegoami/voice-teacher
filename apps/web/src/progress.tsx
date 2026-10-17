import { useEffect, useRef, useState } from "react";
import { LegacyHistory } from "./legacy-history";
import { RecordingHistory } from "./retention";
import { api, ApiError, load as loadSaved, save, type Choice } from "./api";

type SourceRef = {
  source_id: string;
  course_id: string;
  lesson_id: string;
  revision: { content_sha256: string };
};
type Counts = { locally_saved: number; exported: number; pushed: number };
type Progress = {
  criterion: string;
  courses: {
    source_id: string;
    course_id: string;
    content_sha256: string;
    title: string;
    required_items: number;
    covered_items: number;
    version_id?: string | null;
    decision_revision?: number;
    next_lesson_id: string | null;
    lessons: {
      lesson_id: string;
      title: string;
      required_items: number;
      covered_items: number;
      covered: boolean;
      completed?: boolean;
      learner_completed?: boolean | null;
    }[];
  }[];
  legacy_positions?: {
    source_id: string;
    course_id: string;
    covered_lesson_ids: string[];
    next_lesson_id: string | null;
  }[];
  sessions: ({
    session_id: string;
    title: string;
    mode: string;
    source: SourceRef | null;
    status: string;
    accepted_turns: number;
    updated_at: string;
  } & Counts)[];
  more_sessions: boolean;
  sync: Counts & {
    configured: boolean;
    last_push_at: string | null;
    error: string | null;
  };
};
type Turn = { turn_id: string; role: string; text: string };
type Evidence = {
  event_id: string;
  session_id: string;
  turn: Turn;
  outcome: string;
  attempt: string;
  preferred: string | null;
  reason: string | null;
  recognition_uncertain: boolean;
  correction: boolean;
  assistance: { kind: string; target_exposed: boolean };
  superseded: boolean;
  provenance: {
    original_source: SourceRef | null;
    practice_source: SourceRef | null;
    origin_session_id: string;
    origin_turn_id: string;
    original_item: { item_id: string; item_revision: number } | null;
  };
};
type Page = {
  session_id: string;
  rows: Evidence[];
  next_offset: number | null;
};
const labels: Record<string, string> = {
  independent: "Independent use",
  repeated: "Repeated after a model",
  cued: "Cued use",
  modelled_repeated: "Modelled and repeated",
  corrected_repeated: "Corrected and repeated",
  needs_turn: "Needs another turn",
  skipped: "Skipped goal",
  observed: "Observed use",
};
function sourceName(source: SourceRef | null) {
  if (source?.source_id.startsWith("private-review-")) return "Personal review";
  return source
    ? `${source.source_id} / ${source.course_id} / ${source.lesson_id} · revision ${source.revision.content_sha256.slice(0, 8)}`
    : "Source-free conversation";
}
function CountsView({ value }: { value: Counts }) {
  return (
    <span>
      {value.locally_saved} locally saved · {value.exported} exported ·{" "}
      {value.pushed} pushed
    </span>
  );
}

export function ProgressPanel({
  token,
  unauthorized,
  learner,
  chooseLesson,
  selection,
  availableLessons,
}: {
  token: string;
  learner: string;
  selection: Choice;
  availableLessons: string[];
  chooseLesson: (source: string, course: string, lesson: string) => void;
  unauthorized: (e: ApiError) => void;
}) {
  const [view, setView] = useState<Progress | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [detail, setDetail] = useState<Page | null>(null),
    [turns, setTurns] = useState<Turn[]>([]);
  const [limit, setLimit] = useState(50);
  type Intent = {
    request_id: string;
    source_id: string;
    course_id: string;
    lesson_id: string;
    version_id: string;
    expected_revision: number;
    completed: boolean;
  };
  const [pending, setPending] = useState<Intent | null>(() => {
    const v = loadSaved<Intent | null>(learner, "lesson-choice", null);
    const id = (x: unknown) =>
      typeof x === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/.test(x);
    return v &&
      [v.request_id, v.source_id, v.course_id, v.lesson_id, v.version_id].every(
        id,
      ) &&
      Number.isSafeInteger(v.expected_revision) &&
      v.expected_revision >= 0 &&
      typeof v.completed === "boolean"
      ? v
      : null;
  });
  const [conflict, setConflict] = useState(false);
  async function submitDecision(intent: Intent) {
    try {
      await api("/lesson-completions", token, intent);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(true);
      throw e;
    }
    save(learner, "lesson-choice", null);
    setPending(null);
    setConflict(false);
    await load();
  }
  async function decide(
    course: Progress["courses"][number],
    lesson: string,
    completed: boolean,
  ) {
    if (pending || !course.version_id) return;
    const intent = {
      request_id: crypto.randomUUID(),
      source_id: course.source_id,
      course_id: course.course_id,
      lesson_id: lesson,
      version_id: course.version_id,
      expected_revision: course.decision_revision ?? 0,
      completed,
    };
    save(learner, "lesson-choice", intent);
    setPending(intent);
    await submitDecision(intent);
  }
  const active = useRef(true),
    running = useRef(false);
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
        e instanceof ApiError
          ? e.message
          : "History is unavailable. Your saved progress is retained; retry when connected.",
      );
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function load(nextLimit = limit) {
    const result = await api<Progress>("/progress?limit=" + nextLimit, token);
    if (active.current) {
      setView(result);
      setLimit(nextLimit);
    }
  }
  async function show(session: string, offset = 0) {
    const [page, transcript] = await Promise.all([
      api<Page>(
        "/sessions/" +
          encodeURIComponent(session) +
          "/evidence?offset=" +
          offset,
        token,
      ),
      api<Turn[]>(
        "/sessions/" + encodeURIComponent(session) + "/transcript",
        token,
      ),
    ]);
    if (!active.current) return;
    setDetail((previous) =>
      offset && previous?.session_id === session
        ? { ...page, rows: [...previous.rows, ...page.rows] }
        : page,
    );
    setTurns(transcript);
  }
  return (
    <section aria-labelledby="progress">
      <h2 id="progress">History and progress</h2>
      <LegacyHistory token={token} unauthorized={unauthorized} />
      <button
        className="secondary"
        disabled={busy}
        onClick={() => void action(() => load())}
      >
        {view ? "Refresh history" : "Load history and progress"}
      </button>
      {busy && <p role="status">Loading saved progress…</p>}
      {error && <p role="alert">{error}</p>}
      {pending && (
        <div role="status">
          <p>
            A lesson choice is awaiting confirmation. Retry to recover the same
            choice after a connection failure.
          </p>
          <button
            disabled={busy || conflict}
            onClick={() => void action(() => submitDecision(pending))}
          >
            Retry saved lesson choice
          </button>
          {conflict && (
            <button
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  await load();
                  save(learner, "lesson-choice", null);
                  setPending(null);
                  setConflict(false);
                })
              }
            >
              Reload changed lesson choices
            </button>
          )}
        </div>
      )}
      {view && (
        <>
          <h3>Backup state</h3>
          <p>
            <CountsView value={view.sync} />
          </p>
          <p className="hint">
            Locally saved records are on this server. Exported records are in
            the private archive. Pushed records were confirmed at the configured
            remote.
          </p>
          {!view.sync.configured && (
            <p>Remote progress sync is not configured.</p>
          )}
          {view.sync.error && <p role="status">{view.sync.error}</p>}
          {view.sync.last_push_at && (
            <p>
              Last confirmed push:{" "}
              <time dateTime={view.sync.last_push_at}>
                {new Date(view.sync.last_push_at).toLocaleString()}
              </time>
            </p>
          )}
          <h3>Imported course position</h3>
          {(view.legacy_positions ?? []).map((position) => (
            <article key={position.source_id + ":" + position.course_id}>
              <p>
                {position.source_id} / {position.course_id}: historical lessons
                covered {position.covered_lesson_ids.join(", ") || "none"}.
                Next: {position.next_lesson_id ?? "none recorded"}.
              </p>
              <p className="hint">
                Historical position is preserved separately from practice
                evidence. Choose its current course above to use the recorded
                next lesson.
              </p>
              {position.next_lesson_id && (
                <button
                  disabled={
                    busy ||
                    !selection.source_id ||
                    !selection.course_id ||
                    !availableLessons.includes(position.next_lesson_id)
                  }
                  onClick={() =>
                    chooseLesson(
                      selection.source_id,
                      selection.course_id,
                      position.next_lesson_id!,
                    )
                  }
                >
                  Use imported next lesson in selected course
                </button>
              )}
            </article>
          ))}
          <h3>Course item practice</h3>
          <p className="hint">
            You decide when a lesson is complete. Completing it changes the next
            lesson; item coverage and weak expressions remain available for
            review.
          </p>
          <p className="hint">{view.criterion}</p>
          {!view.courses.length && <p>No lesson course history yet.</p>}
          {view.courses.map((course) => (
            <article
              key={[
                course.source_id,
                course.course_id,
                course.content_sha256,
              ].join(":")}
            >
              <h4>{course.title}</h4>
              <p>
                {course.source_id} / {course.course_id} · revision{" "}
                {course.content_sha256.slice(0, 8)}
              </p>
              <p>
                {course.covered_items} of {course.required_items} items covered
              </p>
              <p>
                {course.next_lesson_id
                  ? "Next lesson: " +
                    (course.lessons.find(
                      (l) => l.lesson_id === course.next_lesson_id,
                    )?.title ?? course.next_lesson_id)
                  : "All listed lessons are complete."}
              </p>
              {course.next_lesson_id && course.version_id && (
                <button
                  disabled={busy}
                  onClick={() =>
                    chooseLesson(
                      course.source_id,
                      course.course_id,
                      course.next_lesson_id!,
                    )
                  }
                >
                  Continue to next lesson
                </button>
              )}
              <ol>
                {course.lessons.map((l) => (
                  <li key={l.lesson_id}>
                    {l.title}:{" "}
                    {l.required_items
                      ? `${l.covered_items} of ${l.required_items} items covered`
                      : "No item coverage criterion"}
                    {l.learner_completed != null && (
                      <span>
                        {" "}
                        ·{" "}
                        {l.learner_completed
                          ? "Completed by you"
                          : "Reopened by you"}
                      </span>
                    )}
                    {course.version_id && (
                      <button
                        disabled={busy || !!pending}
                        onClick={() =>
                          void action(() =>
                            decide(
                              course,
                              l.lesson_id,
                              !(l.completed ?? l.covered),
                            ),
                          )
                        }
                      >
                        {(l.completed ?? l.covered)
                          ? "Reopen lesson"
                          : "Mark lesson complete"}
                        : {l.title}
                      </button>
                    )}
                  </li>
                ))}
              </ol>
            </article>
          ))}
          <h3>Recent sessions</h3>
          {!view.sessions.length && <p>No sessions saved for this learner.</p>}
          <ul className="sessions">
            {view.sessions.map((s) => (
              <li key={s.session_id}>
                <div>
                  <strong>{s.title}</strong>
                  <small>
                    <time dateTime={s.updated_at}>
                      {new Date(s.updated_at).toLocaleString()}
                    </time>
                  </small>
                  <small>
                    {s.status} · {s.mode.replaceAll("_", " ")} ·{" "}
                    {s.accepted_turns} saved{" "}
                    {s.accepted_turns === 1 ? "response" : "responses"}
                  </small>
                  <small>{sourceName(s.source)}</small>
                  <small>
                    <CountsView value={s} />
                  </small>
                </div>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => void action(() => show(s.session_id))}
                >
                  Evidence for {s.title}
                </button>
              </li>
            ))}
          </ul>
          {view.more_sessions && (
            <button
              className="secondary"
              disabled={busy || limit >= 100}
              onClick={() => void action(() => load(100))}
            >
              Show up to 100 recent sessions
            </button>
          )}
          {view.more_sessions && limit >= 100 && (
            <p>
              Showing the 100 most recent sessions. Course coverage still
              includes the full saved history.
            </p>
          )}
        </>
      )}
      {detail && (
        <article aria-label="Session evidence">
          <h3>
            Evidence for{" "}
            {view?.sessions.find((s) => s.session_id === detail.session_id)
              ?.title ?? "saved session"}
          </h3>
          {!detail.rows.length && (
            <p>
              No item observations recorded. Saved turns below remain available.
            </p>
          )}
          <ul>
            {detail.rows.map((e) => (
              <li key={e.event_id}>
                <p>
                  <strong>{labels[e.outcome] ?? e.outcome}</strong>
                  {e.superseded ? " · superseded observation" : ""}
                  {e.recognition_uncertain ? " · recognition uncertain" : ""}
                </p>
                <p>Recorded attempt: {e.attempt}</p>
                {e.correction && <p>Supported correction: {e.preferred}</p>}
                {!e.correction && e.preferred && (
                  <p>
                    {e.recognition_uncertain
                      ? "Unconfirmed suggested form: "
                      : "Practised form: "}
                    {e.preferred}
                  </p>
                )}
                {e.reason && (
                  <p>
                    {e.recognition_uncertain ? "Unconfirmed reason: " : ""}
                    {e.reason}
                  </p>
                )}
                <p>
                  Assistance: {e.assistance.kind.replaceAll("_", " ")}
                  {e.assistance.target_exposed ? " · target was offered" : ""}
                </p>
                <p>
                  Original: {sourceName(e.provenance.original_source)}
                  {e.provenance.original_item
                    ? " · item " +
                      e.provenance.original_item.item_id +
                      " v" +
                      e.provenance.original_item.item_revision
                    : ""}
                  <br />
                  Later practice: {sourceName(e.provenance.practice_source)}
                </p>
                <a href={"#turn-" + encodeURIComponent(e.turn.turn_id)}>
                  Supporting learner turn
                </a>
                {e.provenance.origin_session_id !== detail.session_id && (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      void action(() => show(e.provenance.origin_session_id))
                    }
                  >
                    View original session
                  </button>
                )}
              </li>
            ))}
          </ul>
          {detail.next_offset !== null && (
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                void action(() => show(detail.session_id, detail.next_offset!))
              }
            >
              More observations
            </button>
          )}
          <RecordingHistory
            key={detail.session_id}
            token={token}
            unauthorized={unauthorized}
            session={detail.session_id}
          />
          <h4>Saved transcript</h4>
          <ol>
            {turns.map((t) => (
              <li id={"turn-" + encodeURIComponent(t.turn_id)} key={t.turn_id}>
                <strong>{t.role}: </strong>
                {t.text}
              </li>
            ))}
          </ol>
        </article>
      )}
    </section>
  );
}
