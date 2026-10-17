import { ProgressPanel } from "./progress";
import { RetentionPanel } from "./retention";
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  api,
  ApiError,
  readGrant,
  writeGrant,
  readChoice,
  readSessions,
  save,
  serverOrigin,
  modes,
} from "./api";
import type {
  Grant,
  Source,
  Course,
  Lesson,
  Choice,
  SavedSession,
  Presentation,
  CorrectionStyle,
} from "./api";
import "./style.css";
import { SessionScreen } from "./session";

function App() {
  const [grant, setGrant] = useState<Grant | null>(() => readGrant());
  const [verified, setVerified] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [server, setServer] = useState(location.origin),
    [code, setCode] = useState("");
  const [sources, setSources] = useState<Source[]>([]),
    [courses, setCourses] = useState<Course[]>([]),
    [lessons, setLessons] = useState<Lesson[]>([]);
  const [choice, setChoice] = useState<Choice>({
    source_id: "",
    course_id: "",
    lesson_id: "",
    mode: "guided_conversation",
  });
  const [sourceFree, setSourceFree] = useState(false);
  const [topic, setTopic] = useState("");
  const [correction, setCorrection] =
    useState<CorrectionStyle>("light_immediate");
  const [sessions, setSessions] = useState<SavedSession[]>([]),
    [current, setCurrent] = useState<Presentation | null>(null);
  const [reload, setReload] = useState(0);
  const [sessionOpen, setSessionOpen] = useState(0);
  const epoch = useRef(0);
  function failure(e: unknown) {
    setError(
      e instanceof Error
        ? e.message
        : "Connection failed. Retry when the server is available.",
    );
    if (e instanceof ApiError && e.status === 401) {
      writeGrant(null);
      setGrant(null);
      setVerified(false);
    }
  }
  async function action(fn: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      failure(e);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    const id = ++epoch.current;
    setVerified(false);
    setSources([]);
    setCourses([]);
    setLessons([]);
    setCurrent(null);
    if (!grant) return;
    void (async () => {
      try {
        const identity = await api<{ learner_id: string }>(
          "/identity",
          grant.token,
        );
        if (id !== epoch.current) return;
        if (identity.learner_id !== grant.learner_id) throw new ApiError(401);
        setChoice(readChoice(grant.learner_id));
        setSessions(readSessions(grant.learner_id));
        setVerified(true);
      } catch (e) {
        if (id === epoch.current) failure(e);
      }
    })();
    return () => {
      epoch.current++;
    };
  }, [grant, reload]);
  useEffect(() => {
    if (!verified || !grant) return;
    let alive = true;
    setSources([]);
    void api<Source[]>("/sources", grant.token)
      .then((v) => {
        if (alive) setSources(v);
      })
      .catch((e) => {
        if (alive) failure(e);
      });
    return () => {
      alive = false;
    };
  }, [verified, grant, reload]);
  useEffect(() => {
    setCourses([]);
    setLessons([]);
    if (!verified || !grant || !choice.source_id) return;
    let alive = true;
    void api<Course[]>(
      "/sources/" + encodeURIComponent(choice.source_id) + "/courses",
      grant.token,
    )
      .then((v) => {
        if (alive) setCourses(v);
      })
      .catch((e) => {
        if (alive) failure(e);
      });
    return () => {
      alive = false;
    };
  }, [verified, grant, choice.source_id, reload]);
  useEffect(() => {
    setLessons([]);
    if (!verified || !grant || !choice.source_id || !choice.course_id) return;
    let alive = true;
    void api<Lesson[]>(
      "/sources/" +
        encodeURIComponent(choice.source_id) +
        "/courses/" +
        encodeURIComponent(choice.course_id) +
        "/lessons",
      grant.token,
    )
      .then((v) => {
        if (alive) setLessons(v);
      })
      .catch((e) => {
        if (alive) failure(e);
      });
    return () => {
      alive = false;
    };
  }, [verified, grant, choice.source_id, choice.course_id, reload]);
  function select(next: Choice) {
    setChoice(next);
    if (grant) save(grant.learner_id, "choice", next);
  }
  const source = sources.find((s) => s.source_id === choice.source_id),
    course = courses.find((c) => c.course_id === choice.course_id),
    lesson = lessons.find((l) => l.lesson_id === choice.lesson_id);
  const available = Boolean(
    sourceFree
      ? topic.trim().length > 0 && topic.trim().length <= 500
      : source?.available &&
          course &&
          lesson?.available_modes.includes(choice.mode),
  );
  async function openSession(s: SavedSession) {
    if (!grant) return;
    try {
      setCurrent(
        await api<Presentation>(
          "/sessions/" + encodeURIComponent(s.start.session_id),
          grant.token,
        ),
      );
    } catch (e) {
      if (e instanceof ApiError && e.status === 502) {
        setCurrent(
          await api<Presentation>(
            "/sessions/" +
              encodeURIComponent(s.start.session_id) +
              "?prepare_audio=false",
            grant.token,
          ),
        );
      } else {
        if (!(e instanceof ApiError) || e.status !== 404) throw e;
        setCurrent(await api<Presentation>("/sessions", grant.token, s.start));
      }
    }
    // An explicit Open replaces the local media controller even for the same
    // session ID. Its old capture/playback ends; the new server state and any
    // durable pending intent are loaded together. Turn replies keep it mounted.
    setSessionOpen((n) => n + 1);
  }
  async function start() {
    if (!grant || !available) return;
    const free = sourceFree || choice.mode === "free_conversation";
    const entry: SavedSession = {
      start: {
        ...(sourceFree
          ? {
              mode: "free_conversation" as const,
              language: "uk",
              instruction_language: "en",
            }
          : choice),
        session_id: crypto.randomUUID(),
        ...(free
          ? {
              correction_style: correction,
              ...(topic.trim() ? { topic: topic.trim() } : {}),
            }
          : { activity: "combined" as const }),
      },
      title: sourceFree ? topic.trim() : lesson!.title,
      sourceName: sourceFree ? "Personal topic" : source!.name,
      version: sourceFree ? null : source!.version_id,
    };
    const next = [entry, ...sessions];
    save(grant.learner_id, "sessions", next);
    setSessions(next);
    setCurrent(await api<Presentation>("/sessions", grant.token, entry.start));
  }
  return (
    <main>
      <header>
        <a href="/" className="brand">
          Voice Teacher
        </a>
        <p>Make room for a little conversation.</p>
      </header>
      <section aria-labelledby="connection">
        <div className="section-title">
          <h1 id="connection">Your practice space</h1>
          {verified && <span className="badge">Connected</span>}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void action(async () => {
              const target = serverOrigin(server);
              if (target !== location.origin) {
                location.assign(target);
                return;
              }
              const g = await api<Grant>("/pair", undefined, {
                code: code.trim(),
              });
              writeGrant(g);
              setCode("");
              setGrant(g);
            });
          }}
        >
          <label>
            Server address
            <input
              type="url"
              required
              value={server}
              onChange={(e) => setServer(e.target.value)}
              autoCapitalize="none"
              spellCheck={false}
            />
          </label>
          <p className="hint">
            Open the app at your server address to pair. Each server keeps its
            own connection and saved sessions.
          </p>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() =>
              void action(async () => {
                const target = serverOrigin(server);
                if (target !== location.origin) location.assign(target);
              })
            }
          >
            Open server address
          </button>
          {!verified && (
            <label>
              Pairing code
              <input
                required
                minLength={32}
                type="password"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoComplete="off"
              />
            </label>
          )}
          {!verified && <button disabled={busy}>Connect and pair</button>}
          {verified && (
            <>
              <p>
                Paired learner: <strong>{grant?.learner_id}</strong>
              </p>
              <div className="actions">
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => {
                    epoch.current++;
                    writeGrant(null);
                    setGrant(null);
                    setVerified(false);
                    setSessions([]);
                    setCurrent(null);
                  }}
                >
                  Disconnect
                </button>
              </div>
            </>
          )}
        </form>
      </section>
      {error && (
        <aside role="alert">
          <p>{error}</p>
          <button
            disabled={busy}
            onClick={() => {
              setError("");
              setReload((n) => n + 1);
            }}
          >
            Retry connection and catalogue
          </button>
        </aside>
      )}
      {grant && !verified && !error && (
        <p role="status">Checking your paired identity…</p>
      )}
      {verified && (
        <>
          <section aria-labelledby="catalogue">
            <p className="eyebrow">Choose today’s practice</p>
            <h2 id="catalogue">Your lessons</h2>
            <label className="mode">
              <input
                type="checkbox"
                checked={sourceFree}
                onChange={(e) => setSourceFree(e.target.checked)}
              />
              Practise a topic without a lesson
            </label>
            {!sourceFree && (
              <div className="selections">
                <label>
                  Lesson source
                  <select
                    value={choice.source_id}
                    onChange={(e) =>
                      select({
                        ...choice,
                        source_id: e.target.value,
                        course_id: "",
                        lesson_id: "",
                      })
                    }
                  >
                    <option value="">Choose a source</option>
                    {sources.map((s) => (
                      <option
                        key={s.source_id}
                        value={s.source_id}
                        disabled={!s.available}
                      >
                        {s.name}
                        {s.available ? "" : " — unavailable"}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Course
                  <select
                    disabled={!source?.available}
                    value={choice.course_id}
                    onChange={(e) =>
                      select({
                        ...choice,
                        course_id: e.target.value,
                        lesson_id: "",
                      })
                    }
                  >
                    <option value="">Choose a course</option>
                    {courses.map((c) => (
                      <option key={c.course_id} value={c.course_id}>
                        {c.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Lesson or topic
                  <select
                    disabled={!course}
                    value={choice.lesson_id}
                    onChange={(e) =>
                      select({ ...choice, lesson_id: e.target.value })
                    }
                  >
                    <option value="">Choose a lesson</option>
                    {lessons.map((l) => (
                      <option key={l.lesson_id} value={l.lesson_id}>
                        {l.title}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
            {!sourceFree && lesson && (
              <fieldset>
                <legend>How would you like to practise?</legend>
                {modes.map(([mode, label]) => (
                  <label className="mode" key={mode}>
                    <input
                      type="radio"
                      name="mode"
                      checked={choice.mode === mode}
                      onChange={() => select({ ...choice, mode })}
                    />
                    <span>
                      <strong>{label}</strong>
                      {!lesson.available_modes.includes(mode) && (
                        <small>
                          {lesson.authored_modes.includes(mode)
                            ? "Available in this lesson when the server enables this mode."
                            : "This lesson does not include this mode."}
                        </small>
                      )}
                    </span>
                  </label>
                ))}
              </fieldset>
            )}
            {(sourceFree || choice.mode === "free_conversation") && (
              <fieldset>
                <legend>Free conversation</legend>
                {sourceFree && (
                  <p className="hint">
                    Ukrainian conversation with English explanations.
                  </p>
                )}
                <label>
                  Conversation topic
                  <input
                    maxLength={500}
                    required={sourceFree}
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    placeholder={
                      sourceFree
                        ? "Choose something to talk about"
                        : "Use the lesson topic, or choose your own"
                    }
                  />
                </label>
                <label>
                  Correction preference
                  <select
                    value={correction}
                    onChange={(e) =>
                      setCorrection(e.target.value as CorrectionStyle)
                    }
                  >
                    <option value="light_immediate">
                      Light immediate correction
                    </option>
                    <option value="end_of_session">Feedback at the end</option>
                  </select>
                </label>
                <p className="hint">
                  Choose the preference before starting. A resumed conversation
                  keeps its original choice.
                </p>
              </fieldset>
            )}
            <button
              disabled={busy || !available}
              onClick={() => void action(start)}
            >
              Start practice
            </button>
            {!sourceFree && lesson && !available && (
              <p role="status">
                Choose an available mode to start this lesson.
              </p>
            )}
          </section>
          <section aria-labelledby="saved">
            <h2 id="saved">Continue a session</h2>
            <p className="hint">
              Changing your lesson source keeps these sessions attached to their
              original lesson revision.
            </p>
            {sessions.length === 0 ? (
              <p>No sessions started on this device yet.</p>
            ) : (
              <ul className="sessions">
                {sessions.map((s) => (
                  <li key={s.start.session_id}>
                    <div>
                      <strong>{s.title}</strong>
                      <small>
                        {s.sourceName} ·{" "}
                        {modes.find(([m]) => m === s.start.mode)?.[1]}
                      </small>
                    </div>
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() => void action(() => openSession(s))}
                    >
                      Open {s.title}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {current && grant && (
            <SessionScreen
              key={
                grant.client_id + ":" + current.session_id + ":" + sessionOpen
              }
              initial={current}
              context={sessions.find(
                (s) => s.start.session_id === current.session_id,
              )}
              grant={grant}
              received={setCurrent}
              unauthorized={failure}
            />
          )}
          {grant && (
            <RetentionPanel
              key={"retention-" + grant.client_id}
              token={grant.token}
              unauthorized={failure}
            />
          )}
          {grant && (
            <ProgressPanel
              key={grant.client_id}
              token={grant.token}
              learner={grant.learner_id}
              selection={choice}
              availableLessons={lessons.map((l) => l.lesson_id)}
              chooseLesson={(source_id, course_id, lesson_id) => {
                setSourceFree(false);
                select({ ...choice, source_id, course_id, lesson_id });
                document
                  .getElementById("lesson")
                  ?.scrollIntoView({ block: "center" });
              }}
              unauthorized={failure}
            />
          )}
        </>
      )}
      <footer>
        Your lessons and progress stay with your configured server.
      </footer>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
