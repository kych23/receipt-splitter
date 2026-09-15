"use client";

import { useEffect, useState } from "react";
import { apiBaseUrl } from "@/lib/api/config";
import type { components } from "@/lib/api/schema";

type ReadyResponse = components["schemas"]["ReadyResponse"];

export type ApiStatusState =
  | { kind: "checking" }
  | { kind: "ok" }
  | { kind: "unavailable" }
  | { kind: "error"; httpStatus: number }
  | { kind: "unreachable" }
  | { kind: "misconfigured" };

function isReadyResponse(body: unknown): body is ReadyResponse {
  if (typeof body !== "object" || body === null) return false;
  const { status, database } = body as Record<string, unknown>;
  return (
    (status === "ok" || status === "unavailable") &&
    (database === "ok" || database === "error")
  );
}

function describe(state: ApiStatusState): string {
  switch (state.kind) {
    case "checking":
      return "Checking API…";
    case "ok":
      return "API: ok";
    case "unavailable":
      return "API: unavailable (database)";
    case "error":
      return `API error (HTTP ${state.httpStatus})`;
    case "unreachable":
      return "API unreachable";
    case "misconfigured":
      return "API URL not configured";
  }
}

/** Shows whether the API (and its database) is reachable, via GET /readyz. */
export function ApiStatus(): React.JSX.Element {
  const [state, setState] = useState<ApiStatusState>({ kind: "checking" });

  useEffect(() => {
    const controller = new AbortController();

    // Declared inside the effect: react-hooks/set-state-in-effect rejects calling a
    // component-scope function that sets state from an effect.
    async function run(signal: AbortSignal): Promise<void> {
      let base: string;
      try {
        base = apiBaseUrl();
      } catch {
        setState({ kind: "misconfigured" });
        return;
      }

      let response: Response;
      try {
        response = await fetch(`${base}/readyz`, { signal, cache: "no-store" });
      } catch {
        if (signal.aborted) return;
        setState({ kind: "unreachable" });
        return;
      }

      let body: unknown;
      try {
        body = await response.json();
      } catch {
        if (signal.aborted) return;
        setState({ kind: "error", httpStatus: response.status });
        return;
      }
      if (signal.aborted) return;

      if (!isReadyResponse(body)) {
        setState({ kind: "error", httpStatus: response.status });
      } else if (response.status === 200 && body.status === "ok") {
        setState({ kind: "ok" });
      } else if (response.status === 503 && body.status === "unavailable") {
        setState({ kind: "unavailable" });
      } else {
        setState({ kind: "error", httpStatus: response.status });
      }
    }

    void run(controller.signal);
    return () => controller.abort();
  }, []);

  return <p role="status">{describe(state)}</p>;
}
