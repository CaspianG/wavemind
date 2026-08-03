export interface WaveMindClientOptions {
  baseUrl: string;
  apiKey?: string;
  fetch?: typeof globalThis.fetch;
  maxRetries?: number;
  retryBaseDelayMs?: number;
  retryStatuses?: readonly number[];
}

export interface RequestOptions {
  signal?: AbortSignal;
}

export interface RememberInput {
  text: string;
  namespace?: string;
  tags?: string[];
  ttl_seconds?: number;
  metadata?: Record<string, unknown>;
  priority?: number;
}

export interface QueryInput {
  text: string;
  namespace?: string;
  top_k?: number;
  tags?: string[];
  min_score?: number;
}

export interface QueryResult {
  id: number;
  text: string;
  score: number;
  vector_score: number;
  field_score: number;
  graph_score: number;
  namespace: string;
  tags: string[];
  metadata: Record<string, unknown>;
}

export interface FeedbackInput {
  id: number;
  namespace?: string;
  useful?: boolean;
  strength?: number;
  query?: string;
  reason?: string;
}

export interface FeedbackResponse {
  ok: boolean;
  id: number;
  namespace: string;
  priority: number;
  access_count: number;
  cache_invalidated: number;
}

export interface ForgetInput {
  id?: number;
  text?: string;
  namespace?: string;
}

export interface ForgetResponse {
  deleted: number;
}

export interface AuditEvent {
  id: number;
  created_at: number;
  action: string;
  namespace: string | null;
  memory_id: number | null;
  metadata: Record<string, unknown>;
}

export interface MemoryExplanation {
  schema: "wavemind.memory_explanation.v1";
  id: number;
  namespace: string;
  text: string;
  tags: string[];
  metadata: Record<string, unknown>;
  provenance: Record<string, unknown>;
  created_at: number;
  updated_at: number;
  expires_at: number | null;
  priority: number;
  access_count: number;
  audit_events: AuditEvent[];
}

export interface ExperiencePacketInput {
  query: string;
  namespace?: string;
  token_budget?: number;
  top_k?: number;
  domains?: string[];
  task_types?: string[];
  tools?: string[];
  include_canary?: boolean;
}

export interface ExperiencePacketItem {
  experience_id: string;
  version: number;
  kind: string;
  title: string;
  excerpt: string;
  score: number;
  signals: Record<string, number>;
  citation: string;
  detail_ref: string;
  provenance: Record<string, unknown>;
  estimated_tokens: number;
  canary: boolean;
}

export interface ExperiencePacket {
  schema: "wavemind.experience_packet.v1";
  namespace: string;
  query: string;
  token_budget: number;
  estimated_tokens: number;
  items: ExperiencePacketItem[];
  omitted_count: number;
  generated_at: number;
  compiler_policy: Record<string, unknown>;
  citations: string[];
}

export interface TrajectoryInput {
  payload: unknown;
  provider?: "openai" | "anthropic" | "mcp" | "generic";
  namespace?: string;
  trajectory_id?: string;
  trust?: string;
  status?: string;
  confidence?: number;
}

export type VerificationSource = "test" | "tool" | "environment" | "operator";

export interface ExperienceRuntimeStartInput {
  query: string;
  objective: string;
  domain: string;
  task_type: string;
  namespace?: string;
  session_id?: string;
  run_id?: string;
  task_id?: string;
  tools?: string[];
  metadata?: Record<string, unknown>;
  token_budget?: number;
  top_k?: number;
  canary?: boolean;
}

export interface ExperienceRuntimeEventInput {
  id: string;
  namespace?: string;
  run_id: string;
  kind: string;
  sequence: number;
  occurred_at?: number;
  session_id?: string;
  task_id?: string;
  parent_event_id?: string;
  tool_name?: string;
  duration_ms?: number;
  payload?: Record<string, unknown>;
}

export interface ExperienceRuntimeVerificationInput {
  namespace?: string;
  evidence_id: string;
  source: VerificationSource;
  verifier: string;
  success: boolean;
  score?: number;
  reference?: string;
  metadata?: Record<string, unknown>;
  applied_experience_ids?: string[];
}

export interface ExperienceRuntimeInterventionInput {
  query: string;
  namespace?: string;
  run_id?: string;
  task_id?: string;
  domains?: string[];
  task_types?: string[];
  tools?: string[];
  token_budget?: number;
  top_k?: number;
  canary?: boolean;
}

export interface ExperienceRuntimeLifecycleInput {
  namespace?: string;
  reason: string;
  evidence_id?: string;
  score?: number;
}

export interface ExperienceRuntimeRun {
  schema: "wavemind.agent_experience_run.v1";
  namespace: string;
  session_id: string;
  run_id: string;
  task_id: string;
  next_sequence: number;
  intervention: Record<string, unknown>;
  applied_experience_ids: string[];
}

export class WaveMindHTTPError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`WaveMind HTTP request failed with status ${status}`);
    this.name = "WaveMindHTTPError";
    this.status = status;
    this.body = body;
  }
}

export class WaveMindClient {
  readonly baseUrl: string;
  readonly apiKey?: string;
  private readonly fetchImpl: typeof globalThis.fetch;
  private readonly maxRetries: number;
  private readonly retryBaseDelayMs: number;
  private readonly retryStatuses: ReadonlySet<number>;

  constructor(options: WaveMindClientOptions) {
    const baseUrl = options.baseUrl.trim().replace(/\/+$/, "");
    if (!baseUrl) {
      throw new Error("baseUrl must not be empty");
    }
    this.baseUrl = baseUrl;
    if (options.apiKey !== undefined) {
      this.apiKey = options.apiKey;
    }
    this.fetchImpl = options.fetch ?? globalThis.fetch;
    if (!this.fetchImpl) {
      throw new Error("A fetch implementation is required");
    }
    this.maxRetries = requireNonNegativeInteger(
      options.maxRetries ?? 2,
      "maxRetries",
    );
    this.retryBaseDelayMs = requireNonNegativeInteger(
      options.retryBaseDelayMs ?? 100,
      "retryBaseDelayMs",
    );
    this.retryStatuses = new Set(
      options.retryStatuses ?? [408, 429, 500, 502, 503, 504],
    );
  }

  remember(
    input: RememberInput,
    options?: RequestOptions,
  ): Promise<{ id: number }> {
    return this.request("POST", "/remember", input, options);
  }

  query(
    input: QueryInput,
    options?: RequestOptions,
  ): Promise<{ results: QueryResult[] }> {
    return this.request("POST", "/query", input, options, true);
  }

  feedback(
    input: FeedbackInput,
    options?: RequestOptions,
  ): Promise<FeedbackResponse> {
    return this.request("POST", "/feedback", input, options);
  }

  forget(
    input: ForgetInput,
    options?: RequestOptions,
  ): Promise<ForgetResponse> {
    if (input.id === undefined && input.text === undefined) {
      throw new Error("forget requires id or text");
    }
    return this.request("DELETE", "/forget", input, options);
  }

  explainMemory(
    memoryId: number,
    namespace = "default",
    auditLimit = 20,
    options?: RequestOptions,
  ): Promise<MemoryExplanation> {
    if (!Number.isInteger(auditLimit) || auditLimit < 1 || auditLimit > 100) {
      throw new Error("auditLimit must be an integer between 1 and 100");
    }
    const path =
      `/memories/${encodeURIComponent(String(memoryId))}/explain` +
      `?namespace=${encodeURIComponent(namespace)}` +
      `&audit_limit=${auditLimit}`;
    return this.request("GET", path, undefined, options, true);
  }

  compileExperiencePacket(
    input: ExperiencePacketInput,
    options?: RequestOptions,
  ): Promise<ExperiencePacket> {
    return this.request("POST", "/experience/packet", input, options, true);
  }

  getExperience(
    experienceId: string,
    namespace = "default",
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    const path =
      `/experience/${encodeURIComponent(experienceId)}` +
      `?namespace=${encodeURIComponent(namespace)}`;
    return this.request("GET", path, undefined, options, true);
  }

  ingestTrajectory(
    input: TrajectoryInput,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "/experience/trajectories", input, options);
  }

  exportExperienceBundle(
    namespace?: string,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request(
      "POST",
      "/experience/export",
      { namespace },
      options,
      true,
    );
  }

  importExperienceBundle(
    bundle: Record<string, unknown>,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "/experience/import", { bundle }, options);
  }

  startExperienceRun(
    input: ExperienceRuntimeStartInput,
    options?: RequestOptions,
  ): Promise<ExperienceRuntimeRun> {
    return this.request("POST", "/experience/runtime/runs", input, options);
  }

  captureExperienceEvent(
    input: ExperienceRuntimeEventInput,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "/experience/runtime/events", input, options);
  }

  verifyExperienceRun(
    runId: string,
    input: ExperienceRuntimeVerificationInput,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request(
      "POST",
      `/experience/runtime/runs/${encodeURIComponent(runId)}/verify`,
      input,
      options,
    );
  }

  decideExperienceIntervention(
    input: ExperienceRuntimeInterventionInput,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request(
      "POST",
      "/experience/runtime/interventions",
      input,
      options,
      true,
    );
  }

  listExperienceRuns(
    namespace = "default",
    limit = 100,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    const path = `/experience/runtime/runs?namespace=${encodeURIComponent(namespace)}&limit=${limit}`;
    return this.request("GET", path, undefined, options, true);
  }

  getExperienceRun(
    runId: string,
    namespace = "default",
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    const path =
      `/experience/runtime/runs/${encodeURIComponent(runId)}` +
      `?namespace=${encodeURIComponent(namespace)}`;
    return this.request("GET", path, undefined, options, true);
  }

  getExperienceRuntimeState(
    namespace = "default",
    limit = 100,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    const path = `/experience/runtime/state?namespace=${encodeURIComponent(namespace)}&limit=${limit}`;
    return this.request("GET", path, undefined, options, true);
  }

  approveExperience(
    experienceId: string,
    input: ExperienceRuntimeLifecycleInput,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.experienceLifecycle("approve", experienceId, input, options);
  }

  rejectExperience(
    experienceId: string,
    input: ExperienceRuntimeLifecycleInput,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.experienceLifecycle("reject", experienceId, input, options);
  }

  rollbackExperience(
    experienceId: string,
    input: ExperienceRuntimeLifecycleInput,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.experienceLifecycle("rollback", experienceId, input, options);
  }

  private experienceLifecycle(
    action: "approve" | "reject" | "rollback",
    experienceId: string,
    input: ExperienceRuntimeLifecycleInput,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request(
      "POST",
      `/experience/runtime/${encodeURIComponent(experienceId)}/${action}`,
      input,
      options,
    );
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options?: RequestOptions,
    retryable = false,
  ): Promise<T> {
    const headers: Record<string, string> = {
      accept: "application/json",
    };
    if (body !== undefined) {
      headers["content-type"] = "application/json";
    }
    if (this.apiKey) {
      headers.authorization = `Bearer ${this.apiKey}`;
    }
    let attempt = 0;
    while (true) {
      const init: RequestInit = { method, headers };
      if (body !== undefined) {
        init.body = JSON.stringify(body);
      }
      if (options?.signal !== undefined) {
        init.signal = options.signal;
      }
      try {
        const response = await this.fetchImpl(
          `${this.baseUrl}${path}`,
          init,
        );
        const contentType = response.headers.get("content-type") ?? "";
        const payload = contentType.includes("application/json")
          ? await response.json()
          : await response.text();
        if (response.ok) {
          return payload as T;
        }
        if (
          retryable &&
          attempt < this.maxRetries &&
          this.retryStatuses.has(response.status)
        ) {
          await this.waitBeforeRetry(attempt, options?.signal);
          attempt += 1;
          continue;
        }
        throw new WaveMindHTTPError(response.status, payload);
      } catch (error) {
        if (
          !retryable ||
          attempt >= this.maxRetries ||
          error instanceof WaveMindHTTPError ||
          options?.signal?.aborted
        ) {
          throw error;
        }
        await this.waitBeforeRetry(attempt, options?.signal);
        attempt += 1;
      }
    }
  }

  private waitBeforeRetry(
    attempt: number,
    signal?: AbortSignal,
  ): Promise<void> {
    const delay = this.retryBaseDelayMs * 2 ** attempt;
    if (delay === 0) {
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      const onAbort = () => {
        clearTimeout(timer);
        reject(signal?.reason ?? new DOMException("Aborted", "AbortError"));
      };
      const timer = setTimeout(() => {
        signal?.removeEventListener("abort", onAbort);
        resolve();
      }, delay);
      if (signal?.aborted) {
        onAbort();
        return;
      }
      signal?.addEventListener("abort", onAbort, { once: true });
    });
  }
}

function requireNonNegativeInteger(value: number, name: string): number {
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`${name} must be a non-negative integer`);
  }
  return value;
}
