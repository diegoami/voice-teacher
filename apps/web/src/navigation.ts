import { useEffect, useRef, useState } from "react";

export type Route = {
  page: "lessons" | "practice" | "history" | "settings" | "missing";
  session?: string;
};
export function routeFor(hash: string): Route {
  if (!hash || hash === "#/lessons") return { page: "lessons" };
  if (["#/practice", "#/history", "#/settings"].includes(hash))
    return { page: hash.slice(2) as Route["page"] };
  const match = /^#\/practice\/([A-Za-z0-9][A-Za-z0-9._-]{0,95})$/.exec(hash);
  return match ? { page: "practice", session: match[1] } : { page: "missing" };
}
type Target = { hash: string; index?: number };
const indexKey = "voiceTeacherNavigationIndex";
export function useNavigation(
  blocked: () => boolean,
  leaving: (route: Route) => void,
) {
  const [route, setRoute] = useState<Route>(() => routeFor(location.hash));
  const [pending, setPending] = useState<Target | null>(null);
  const callbacks = useRef({ blocked, leaving });
  callbacks.current = { blocked, leaving };
  const current = useRef({
    hash: location.hash || "#/lessons",
    index: Number.isSafeInteger(history.state?.[indexKey])
      ? history.state[indexKey]
      : 0,
  });
  const restoring = useRef<number | null>(null),
    allowed = useRef(false);
  const commit = (target: Target) => {
    callbacks.current.leaving(routeFor(target.hash));
    current.current = {
      hash: target.hash,
      index: target.index ?? current.current.index + 1,
    };
    setRoute(routeFor(target.hash));
  };
  useEffect(() => {
    history.replaceState(
      { ...history.state, [indexKey]: current.current.index },
      "",
      current.current.hash,
    );
    const pop = (event: PopStateEvent) => {
      let index = event.state?.[indexKey];
      if (!Number.isSafeInteger(index)) {
        index = current.current.index + 1;
        history.replaceState(
          { ...history.state, [indexKey]: index },
          "",
          location.hash,
        );
      }
      if (restoring.current !== null) {
        if (index === restoring.current) restoring.current = null;
        return;
      }
      const target = { hash: location.hash, index };
      if (
        !allowed.current &&
        target.hash !== current.current.hash &&
        callbacks.current.blocked()
      ) {
        setPending(target);
        restoring.current = current.current.index;
        history.go(current.current.index - index);
        return;
      }
      allowed.current = false;
      commit(target);
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  function navigate(hash: string) {
    if (hash === current.current.hash) return;
    if (callbacks.current.blocked()) {
      setPending({ hash });
      return;
    }
    const index = current.current.index + 1;
    history.pushState({ ...history.state, [indexKey]: index }, "", hash);
    commit({ hash, index });
  }
  function proceed() {
    if (!pending || restoring.current !== null) return;
    const target = pending;
    setPending(null);
    if (target.index !== undefined) {
      allowed.current = true;
      history.go(target.index - current.current.index);
    } else {
      const index = current.current.index + 1;
      history.pushState(
        { ...history.state, [indexKey]: index },
        "",
        target.hash,
      );
      commit({ ...target, index });
    }
  }
  return { route, navigate, pending, proceed, stay: () => setPending(null) };
}
