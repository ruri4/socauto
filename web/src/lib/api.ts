import type {
  Account,
  AccountImportResponse,
  AccountSessionResponse,
  HealthResponse,
  Job,
  JobCreateInput,
  JobFilters,
  JobRetryInput,
  Page,
} from "./types";

interface ErrorPayload {
  detail?: {
    code?: unknown;
    message?: unknown;
    existing_job_id?: unknown;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly existingJobId: string | null;
  readonly retryAfter: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    existingJobId: string | null,
    retryAfter: string | null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.existingJobId = existingJobId;
    this.retryAfter = retryAfter;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  formData?: FormData;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers({ Accept: "application/json" });
  const init: RequestInit = { method: options.method ?? "GET", headers };

  if (options.formData) {
    init.body = options.formData;
  } else if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(options.body);
  }

  const response = await fetch(path, init);
  const retryAfter = response.headers.get("Retry-After");

  if (!response.ok) {
    let payload: ErrorPayload | null = null;
    try {
      payload = (await response.json()) as ErrorPayload;
    } catch {
      payload = null;
    }
    const detail = payload?.detail;
    const code = typeof detail?.code === "string" ? detail.code : `http_${response.status}`;
    const message =
      typeof detail?.message === "string" ? detail.message : response.statusText || "Request failed";
    const existingJobId =
      typeof detail?.existing_job_id === "string" ? detail.existing_job_id : null;
    throw new ApiError(response.status, code, message, existingJobId, retryAfter);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.retryAfter ? `${error.message} Retry-After: ${error.retryAfter}.` : error.message;
  }
  return "The local API did not respond. Check that it is running on 127.0.0.1:8000.";
}

function idPath(id: string): string {
  return encodeURIComponent(id);
}

export const api = {
  health: () => request<HealthResponse>("/health"),

  listAccounts: (offset = 0, limit = 50) =>
    request<Page<Account>>(`/v1/accounts?offset=${offset}&limit=${limit}`),

  importTikTok: (formData: FormData) =>
    request<AccountImportResponse>("/v1/accounts/tiktok/import", {
      method: "POST",
      formData,
    }),

  validateAccount: (id: string) =>
    request<AccountSessionResponse>(`/v1/accounts/${idPath(id)}/session/validate`, {
      method: "POST",
    }),

  deleteAccount: (id: string) =>
    request<void>(`/v1/accounts/${idPath(id)}`, { method: "DELETE" }),

  createJob: (input: JobCreateInput) =>
    request<Job>("/v1/jobs", { method: "POST", body: input }),

  listJobs: (offset = 0, limit = 50, filters: JobFilters) => {
    const query = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (filters.state) query.set("state", filters.state);
    if (filters.destinationAccountId) {
      query.set("destination_account_id", filters.destinationAccountId);
    }
    return request<Page<Job>>(`/v1/jobs?${query.toString()}`);
  },

  getJob: (id: string) => request<Job>(`/v1/jobs/${idPath(id)}`),

  retryJob: (id: string, input: JobRetryInput = {}) =>
    request<Job>(`/v1/jobs/${idPath(id)}/retry`, { method: "POST", body: input }),

  cancelJob: (id: string) =>
    request<Job>(`/v1/jobs/${idPath(id)}`, { method: "DELETE" }),
};
