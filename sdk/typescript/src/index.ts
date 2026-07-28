export interface WaveMindClientOptions {
  baseUrl: string;
  apiKey?: string;
  fetch?: typeof globalThis.fetch;
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
  }

  remember(input: RememberInput): Promise<{ id: number }> {
    return this.request("POST", "/remember", input);
  }

  query(input: QueryInput): Promise<{ results: QueryResult[] }> {
    return this.request("POST", "/query", input);
  }

  compileExperiencePacket(
    input: ExperiencePacketInput,
  ): Promise<ExperiencePacket> {
    return this.request("POST", "/experience/packet", input);
  }

  getExperience(
    experienceId: string,
    namespace = "default",
  ): Promise<Record<string, unknown>> {
    const path =
      `/experience/${encodeURIComponent(experienceId)}` +
      `?namespace=${encodeURIComponent(namespace)}`;
    return this.request("GET", path);
  }

  ingestTrajectory(
    input: TrajectoryInput,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "/experience/trajectories", input);
  }

  exportExperienceBundle(
    namespace?: string,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "/experience/export", { namespace });
  }

  importExperienceBundle(
    bundle: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "/experience/import", { bundle });
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
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
    const init: RequestInit = { method, headers };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
    }
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, init);
    const contentType = response.headers.get("content-type") ?? "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    if (!response.ok) {
      throw new WaveMindHTTPError(response.status, payload);
    }
    return payload as T;
  }
}
