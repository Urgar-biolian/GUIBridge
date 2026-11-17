// Typed client for the loopback control plane (docs/api.md §2).
//
// Every path goes through the Vite proxy (`/api` → `http://127.0.0.1:8765`, prefix stripped), so the
// Dashboard never talks to a second origin and never needs CORS. The plane itself binds to loopback
// only; nothing here may widen that.

export interface ErrorEnvelope {
  error_code: string;
  message: string;
  evidence: string[];
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly evidence: string[];

  constructor(code: string, message: string, status: number, evidence: string[]) {
    super(message);
    this.code = code;
    this.status = status;
    this.evidence = evidence;
  }
}

export interface Health {
  status: string;
  stage: string;
  window_id: string;
  channel: string;
}

export interface WindowRecord {
  window_id: string;
  process_name: string;
  title: string;
  geometry: Record<string, number>;
  whitelisted: boolean;
  first_seen: string;
  last_seen: string;
}

export interface Transition {
  state: string;
  evidence_id: string;
  ts: string;
}

export interface TaskRecord {
  task_id: string;
  app: string;
  project_path: string;
  mode: string;
  state: string;
  acceptance: Record<string, unknown> | null;
  created_ts: string;
  updated_ts: string;
  transitions: Transition[];
}

export interface TaskStatus {
  task_id: string;
  app: string;
  state: string;
  signals: Record<string, boolean>;
  transitions: Transition[];
  evidence: string[];
}

export interface TaskResult {
  task_id: string;
  reply_text: string;
  untrusted: boolean;
  claimed_done: boolean;
  truncated: boolean;
  full_length: number;
  evidence: string[];
}

export interface SnapshotEvidence {
  snapshot_id: string;
  ts: string;
  image_path: string | null;
  element_count: number;
}

export interface EventPayload extends Record<string, unknown> {
  snapshots?: SnapshotEvidence[];
}

export interface GuiEvent {
  seq: number;
  event_id: string;
  ts: string;
  kind: string;
  task_id: string | null;
  window_id: string | null;
  semantic_id: string | null;
  action: string | null;
  payload: EventPayload;
  evidence: string[];
  approval_id: string | null;
}

export interface ApprovalScope {
  window_id?: string;
  semantic_ids?: string[];
  actions?: string[];
}

export interface ApprovalRequest {
  request_id: string;
  scope: ApprovalScope;
  reason: string;
}

export interface GrantResponse {
  token: string;
  scope: ApprovalScope;
}

export interface ChainStrategy extends Record<string, unknown> {
  cdp_selector?: string;
  uia_automation_id?: string;
  ocr_text?: string;
}

export interface LocatorRecord {
  semantic_id: string;
  app: string;
  app_version: string;
  chain: ChainStrategy[];
  verification: string;
  healed_at: string | null;
}

export interface HealPatch {
  patch_id: string;
  semantic_id: string;
  app: string;
  app_version: string;
  proposed_chain: ChainStrategy[];
  status: string;
  created_ts: string;
  reviewed_by: string | null;
}

export interface LocatorRegistry {
  locators: LocatorRecord[];
  heal_patches: HealPatch[];
}

export interface SnapshotCapture {
  snapshot_id: string;
  image_path: string | null;
  ts: string;
  window_id: string;
  elements_summary: { count: number; roles: string[] };
}

/** The `verify` evidence payload written by the independent verifier (docs/agent.md trust boundary). */
export interface VerificationPayload extends EventPayload {
  status?: string;
  verified?: boolean;
  reasons?: string[];
  changed_files?: string[];
  out_of_scope?: string[];
  allow_files?: string[];
  since_rev?: string | null;
  head?: string;
  changes?: Record<string, string[]>;
  committed_since?: string[];
  tests?: { command: string[]; returncode: number | null; error?: string; stdout?: string; stderr?: string }[];
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      throw new ApiError("invalid_response", `${path} returned a non-JSON body (HTTP ${response.status})`,
        response.status, []);
    }
  }
  if (!response.ok) {
    // FastAPI answers a malformed body with `{"detail": …}` instead of the docs/api.md envelope, so
    // both shapes have to surface something readable rather than "HTTP 400". `detail` is a string for
    // our own JSON responses and a list of validation errors for FastAPI's.
    const envelope = (body ?? {}) as Partial<ErrorEnvelope> & { detail?: unknown };
    const detail = typeof envelope.detail === "string"
      ? envelope.detail
      : envelope.detail === undefined ? undefined : JSON.stringify(envelope.detail);
    throw new ApiError(envelope.error_code ?? `http_${response.status}`,
      envelope.message ?? detail ?? `HTTP ${response.status}`, response.status, envelope.evidence ?? []);
  }
  return body as T;
}

const json = (method: string, payload: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});

export const api = {
  health: () => request<Health>("/health"),
  windows: (all = true) => request<{ windows: WindowRecord[] }>(`/windows?all=${all}`),
  whitelist: (windowId: string) =>
    request<{ window_id: string; whitelisted: boolean }>(`/windows/${windowId}/whitelist`, json("POST", {})),
  captureSnapshot: (windowId: string) =>
    request<SnapshotCapture>(`/windows/${encodeURIComponent(windowId)}/snapshot`),
  tasks: () => request<{ tasks: TaskRecord[] }>("/tasks"),
  taskStatus: (taskId: string) => request<TaskStatus>(`/tasks/${encodeURIComponent(taskId)}`),
  taskResult: (taskId: string, maxChars = 4000) =>
    request<TaskResult>(`/tasks/${encodeURIComponent(taskId)}/result?max_chars=${maxChars}`),
  pendingApprovals: () => request<{ requests: (GuiEvent & { payload: ApprovalRequest })[] }>("/approvals/pending"),
  grantApproval: (scope: ApprovalScope, requestId: string | null, grantedBy: string) =>
    request<GrantResponse>("/approvals", json("POST", { scope, request_id: requestId, granted_by: grantedBy })),
  locators: () => request<LocatorRegistry>("/locators"),
  reviewHealPatch: (semanticId: string, patchId: string, decision: "approved" | "rejected", reviewedBy: string) =>
    request<{ patch_id: string; status: string; reviewed_by: string }>(
      `/locators/${encodeURIComponent(semanticId)}/heal-review`,
      json("POST", { patch_id: patchId, decision, reviewed_by: reviewedBy })),
};

export const eventsUrl = `${BASE}/events`;
