// One shared reactive view of the control plane, fed by REST reads and the /events SSE stream.
//
// The stream is the source of truth for "something changed": a task transition, an approval request or
// a heal patch arriving on it triggers a debounced re-read of the REST collections. No fixed-interval
// state inference (docs/framework.md) — the UI never decides a task's state, it re-asks the plane.

import { reactive } from "vue";
import { api, eventsUrl } from "./api";
import type {
  ApprovalRequest,
  GuiEvent,
  Health,
  LocatorRegistry,
  TaskRecord,
  WindowRecord,
} from "./api";

export const MAX_EVENTS = 2000;

/** Kinds whose arrival changes more than the event log itself. */
const REFRESH_TRIGGERS = new Set([
  "task_state",
  "task_failed",
  "status_timeout",
  "approval_requested",
  "approval_granted",
  "approval_consumed",
  "heal_proposed",
  "heal_reviewed",
  "verify",
]);

export type StreamState = "idle" | "open" | "reconnecting" | "closed";

interface DashboardState {
  health: Health | null;
  tasks: TaskRecord[];
  windows: WindowRecord[];
  registry: LocatorRegistry;
  pending: (GuiEvent & { payload: ApprovalRequest })[];
  events: GuiEvent[];
  stream: StreamState;
  /** Last failure per collection, shown next to it instead of rendering an empty table. */
  errors: Record<string, string>;
  connectedSince: string | null;
}

export const state = reactive<DashboardState>({
  health: null,
  tasks: [],
  windows: [],
  registry: { locators: [], heal_patches: [] },
  pending: [],
  events: [],
  stream: "idle",
  errors: {},
  connectedSince: null,
});

const seen = new Set<number>();
let source: EventSource | null = null;
let timer: number | null = null;

function noteFailure(collection: string, error: unknown): void {
  state.errors[collection] = error instanceof Error ? error.message : String(error);
}

async function load<T>(collection: string, read: () => Promise<T>, apply: (value: T) => void): Promise<void> {
  try {
    apply(await read());
    delete state.errors[collection];
  } catch (error) {
    noteFailure(collection, error);
  }
}

export async function refresh(): Promise<void> {
  await Promise.all([
    load("health", api.health, (health) => { state.health = health; }),
    load("tasks", api.tasks, (body) => { state.tasks = body.tasks; }),
    load("windows", () => api.windows(true), (body) => { state.windows = body.windows; }),
    load("locators", api.locators, (registry) => { state.registry = registry; }),
    load("approvals", api.pendingApprovals, (body) => { state.pending = body.requests; }),
  ]);
}

/** First paint: collections plus the audit stream. Reconnecting the stream resets the local log. */
export async function start(): Promise<void> {
  await Promise.all([refresh(), connectEvents()]);
}

function scheduleRefresh(): void {
  if (timer !== null) window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    timer = null;
    void refresh();
  }, 300);
}

function ingest(event: GuiEvent): void {
  if (seen.has(event.seq)) return;
  seen.add(event.seq);
  state.events.push(event);
  if (state.events.length > MAX_EVENTS) {
    for (const dropped of state.events.splice(0, state.events.length - MAX_EVENTS)) seen.delete(dropped.seq);
  }
  if (REFRESH_TRIGGERS.has(event.kind)) scheduleRefresh();
}

/**
 * Open the audit stream. The plane restarts its cursor at the beginning of the log on every
 * connection and ignores `Last-Event-ID`, so `seen` is what keeps a browser reconnect from duplicating
 * rows; the log is refetched wholesale rather than patched.
 */
async function connectEvents(): Promise<void> {
  closeEvents();
  seen.clear();
  state.events = [];
  await new Promise<void>((resolve) => {
    const stream = new EventSource(eventsUrl);
    source = stream;
    stream.onopen = () => {
      state.stream = "open";
      state.connectedSince = new Date().toISOString();
      delete state.errors.events;
      resolve();
    };
    stream.onerror = () => {
      // EventSource keeps retrying by itself; only the first failure needs to unblock the caller.
      if (state.stream === "open") state.stream = "reconnecting";
      resolve();
    };
    stream.onmessage = (message) => {
      try {
        ingest(JSON.parse(message.data) as GuiEvent);
      } catch (error) {
        noteFailure("events", error);
      }
    };
  });
}

export function closeEvents(): void {
  if (source) source.close();
  source = null;
  state.stream = "closed";
}

export function eventKinds(): string[] {
  return [...new Set(state.events.map((event) => event.kind))].sort();
}
