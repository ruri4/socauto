import { ApiError } from "./api";
import type { Account, AccountStatus, Job, JobState } from "./types";

const labels: Record<string, string> = {
  active: "Active",
  cancelled: "Cancelled",
  downloaded: "Downloaded",
  downloading: "Downloading",
  expired: "Expired",
  failed: "Failed",
  pending: "Pending",
  posted: "Posted",
  uploading: "Uploading",
};

export function statusLabel(status: AccountStatus | JobState): string {
  return labels[status] ?? status.replaceAll("_", " ");
}

export function formatDate(value: string | null): string {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function utf16CodeUnits(value: string): number {
  let count = 0;
  for (const character of value) {
    count += character.codePointAt(0)! > 0xffff ? 2 : 1;
  }
  return count;
}

export function isActiveJob(job: Job | null): boolean {
  return job !== null && ["pending", "downloading", "downloaded", "uploading"].includes(job.state);
}

export function accountName(account: Account | undefined): string {
  if (!account) return "Unknown account";
  return account.handle ? `@${account.handle}` : `Account ${account.id.slice(0, 8)}`;
}

export function apiErrorCode(error: unknown): string | null {
  return error instanceof ApiError ? error.code : null;
}
