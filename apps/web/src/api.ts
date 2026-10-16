export type Mode = "repetition" | "guided_conversation" | "free_conversation";
export const modes: [Mode, string][] = [
  ["repetition", "Repetition"],
  ["guided_conversation", "Guided conversation"],
  ["free_conversation", "Free conversation"],
];
export type Grant = {
  token: string;
  client_id: string;
  learner_id: string;
  expires_at: number;
};
export type Source = {
  source_id: string;
  name: string;
  version_id: string | null;
  available: boolean;
};
export type Course = {
  course_id: string;
  title: string;
  language: string;
  instruction_language: string;
};
export type Lesson = {
  lesson_id: string;
  title: string;
  authored_modes: Mode[];
  available_modes: Mode[];
};
export type Choice = {
  source_id: string;
  course_id: string;
  lesson_id: string;
  mode: Mode;
};
export type Start = Choice & { session_id: string; activity: "combined" };
export type Presentation = {
  session_id: string;
  request_id: string | null;
  revision: number;
  status: "active" | "paused" | "finished";
  done: boolean;
  card: string | null;
  teacher: { text: string; kind: string }[];
  audio_ids: string[];
  activity?: {
    activity_id: string;
    position: number;
    total: number;
    complete: boolean;
  } | null;
};
export type SavedSession = {
  start: Start;
  title: string;
  sourceName: string;
  version: string | null;
};
export class ApiError extends Error {
  constructor(public status: number) {
    super(
      status === 401
        ? "Pairing expired or was revoked. Pair again to continue."
        : status === 409
          ? "The lesson or session changed. Reload its current status."
          : "The server could not complete this request. Please retry.",
    );
  }
}
export async function api<T>(
  path: string,
  token?: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      ...(token ? { Authorization: "Bearer " + token } : {}),
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
    signal: AbortSignal.timeout(45000),
  });
  if (!response.ok) throw new ApiError(response.status);
  return response.json();
}
export function serverOrigin(value: string): string {
  const url = new URL(value);
  if (
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash ||
    !["http:", "https:"].includes(url.protocol)
  )
    throw new Error(
      "Enter a server origin, for example https://lessons.example.org",
    );
  if (
    url.protocol === "http:" &&
    !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
  )
    throw new Error("Use HTTPS for a phone or remote server.");
  return url.origin;
}
const key = "voice-teacher:grant:v1";
export function readGrant(storage: Storage = localStorage): Grant | null {
  try {
    const g = JSON.parse(storage.getItem(key) || "null");
    return g &&
      typeof g.token === "string" &&
      g.token.length >= 32 &&
      typeof g.client_id === "string" &&
      typeof g.learner_id === "string" &&
      Number.isFinite(g.expires_at) &&
      g.expires_at > Date.now() / 1000
      ? g
      : null;
  } catch {
    return null;
  }
}
export function writeGrant(g: Grant | null) {
  if (g) localStorage.setItem(key, JSON.stringify(g));
  else localStorage.removeItem(key);
}
export function accountKey(learner: string, kind: string) {
  return "voice-teacher:v1:" + encodeURIComponent(learner) + ":" + kind;
}
export function load<T>(learner: string, kind: string, fallback: T): T {
  try {
    return (
      JSON.parse(localStorage.getItem(accountKey(learner, kind)) || "null") ??
      fallback
    );
  } catch {
    return fallback;
  }
}
export function save(learner: string, kind: string, value: unknown) {
  localStorage.setItem(accountKey(learner, kind), JSON.stringify(value));
}

const id = (v: unknown): v is string =>
  typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/.test(v);
export function readChoice(learner: string): Choice {
  const empty: Choice = {
    source_id: "",
    course_id: "",
    lesson_id: "",
    mode: "guided_conversation",
  };
  const value = load<Partial<Choice> | null>(learner, "choice", null);
  return value &&
    typeof value === "object" &&
    modes.some(([m]) => m === value.mode) &&
    ["source_id", "course_id", "lesson_id"].every(
      (k) => value[k as keyof Choice] === "" || id(value[k as keyof Choice]),
    )
    ? (value as Choice)
    : empty;
}
export function readSessions(learner: string): SavedSession[] {
  const value = load<unknown>(learner, "sessions", []);
  return Array.isArray(value)
    ? value.filter(
        (v): v is SavedSession =>
          v &&
          typeof v === "object" &&
          v.start &&
          id(v.start.session_id) &&
          id(v.start.source_id) &&
          id(v.start.course_id) &&
          id(v.start.lesson_id) &&
          v.start.activity === "combined" &&
          modes.some(([m]) => m === v.start.mode) &&
          typeof v.title === "string" &&
          typeof v.sourceName === "string" &&
          (v.version === null || typeof v.version === "string"),
      )
    : [];
}
