export const ACCOUNT_STATUSES = ["active", "expired"] as const;
export type AccountStatus = (typeof ACCOUNT_STATUSES)[number];

export interface Account {
  id: string;
  platform: "tiktok";
  platform_user_id: string | null;
  handle: string | null;
  status: AccountStatus;
  created_at: string;
  updated_at: string;
}

export interface TikTokUser {
  user_id: string;
  username: string;
  display_name: string | null;
}

export interface AccountImportResponse {
  account: Account;
  valid: true;
  checked_at: string;
  user: TikTokUser;
}

export interface AccountSessionResponse {
  account_id: string;
  valid: true;
  checked_at: string;
  user: TikTokUser;
}

export const JOB_STATES = [
  "pending",
  "downloading",
  "downloaded",
  "uploading",
  "posted",
  "failed",
  "cancelled",
] as const;
export type JobState = (typeof JOB_STATES)[number];

export interface Job {
  id: string;
  source_url: string;
  canonical_url: string;
  source_platform: "x";
  destination_platform: "tiktok";
  destination_account_id: string;
  caption_override: string | null;
  resolved_caption: string | null;
  state: JobState;
  attempt_count: number;
  cancel_requested_at: string | null;
  error_code: string | null;
  creation_id: string | null;
  video_id: string | null;
  post_id: string | null;
  posted_url: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface HealthResponse {
  status: "ok";
}

export interface JobFilters {
  state: JobState | "";
  destinationAccountId: string;
}

export interface JobCreateInput {
  source_url: string;
  destination_account_id: string;
  caption_override: string | null;
}

export interface JobRetryInput {
  acknowledge_duplicate_risk?: boolean;
}

export type Workspace = "jobs" | "accounts";
