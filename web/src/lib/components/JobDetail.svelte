<script lang="ts">
  import { api, errorMessage } from "../api";
  import { accountName, formatDate, isActiveJob } from "../format";
  import type { Account, Job } from "../types";
  import StatusChip from "./StatusChip.svelte";
  import UnknownOutcomeDialog from "./UnknownOutcomeDialog.svelte";
  let {
    job,
    accounts,
    loading,
    error,
    onclose,
    onrefresh,
    onjobchanged,
  } = $props<{
    job: Job | null;
    accounts: Account[];
    loading: boolean;
    error: string | null;
    onclose: () => void;
    onrefresh: () => void;
    onjobchanged: (job: Job) => void;
  }>();
  let reviewOpen = $state(false);
  let busyAction = $state<"retry" | "cancel" | null>(null);
  let actionError = $state<string | null>(null);
  const destinationAccount = $derived(
    accounts.find((account: Account) => account.id === job?.destination_account_id),
  );
  const canCancel = $derived(
    job !== null && ["pending", "downloading", "downloaded", "failed"].includes(job.state),
  );
  const unknownOutcome = $derived(
    job?.state === "failed" && job.error_code === "upload_outcome_unknown",
  );
  const canRetry = $derived(job?.state === "failed" && !unknownOutcome);
  function actionFailure(caught: unknown): void {
    actionError = errorMessage(caught);
  }

  async function retry(acknowledgeDuplicateRisk = false): Promise<void> {
    if (!job || busyAction) return;
    actionError = null;
    busyAction = "retry";
    try {
      const next = await api.retryJob(
        job.id,
        acknowledgeDuplicateRisk ? { acknowledge_duplicate_risk: true } : {},
      );
      reviewOpen = false;
      onjobchanged(next);
    } catch (caught) {
      actionFailure(caught);
    } finally {
      busyAction = null;
    }
  }

  async function cancel(): Promise<void> {
    if (!job || busyAction) return;
    actionError = null;
    busyAction = "cancel";
    try {
      const next = await api.cancelJob(job.id);
      onjobchanged(next);
    } catch (caught) {
      actionFailure(caught);
    } finally {
      busyAction = null;
    }
  }
</script>
<section class="detail-surface" aria-labelledby="job-detail-title">
  <div class="detail-surface-inner">
    <div class="detail-heading">
      <div>
        <h2 id="job-detail-title">Job detail</h2>
        <p>{job ? `Job ${job.id}` : "Choose a job to inspect its server state."}</p>
      </div>
      <div class="detail-actions">
        {#if job}
          <button class="button button-small" type="button" disabled={loading || busyAction !== null} onclick={onrefresh}>
            {loading ? "Loading" : "Refresh"}
          </button>
        {/if}
        <button class="button button-quiet button-small" type="button" onclick={onclose}>Close</button>
      </div>
    </div>
    {#if error && !job}
      <div class="inline-error" role="alert">{error}</div>
    {:else if loading && !job}
      <div class="detail-loading" aria-label="Loading job detail" aria-busy="true">
        <span class="skeleton medium"></span>
        <span class="skeleton"></span>
        <span class="skeleton short"></span>
      </div>
    {:else if !job}
      <div class="detail-empty">
        <p>Job fields, acknowledgement IDs, and safe failure codes appear here.</p>
      </div>
    {:else}
      {#if error}
        <div class="inline-error" role="alert">{error}</div>
      {/if}
      {#if actionError}
        <div class="inline-error" role="alert">{actionError}</div>
      {/if}
      <div class="detail-state">
        <StatusChip status={job.state} />
        {#if job.state === "posted"}
          <span>Posted means acknowledged, not confirmed visible.</span>
        {:else if isActiveJob(job)}
          <span>Showing the latest state reported by the API.</span>
        {/if}
      </div>

      <div class="detail-actions detail-actions-main">
        {#if canRetry}
          <button class="button button-primary button-small" type="button" disabled={busyAction !== null} onclick={() => void retry()}>
            {busyAction === "retry" ? "Retrying" : "Retry job"}
          </button>
        {:else if unknownOutcome}
          <button class="button button-primary button-small" type="button" disabled={busyAction !== null} onclick={() => (reviewOpen = true)}>
            Review and retry
          </button>
        {/if}
        {#if canCancel}
          <button class="button button-danger button-small" type="button" disabled={busyAction !== null || job.cancel_requested_at !== null} onclick={() => void cancel()}>
            {busyAction === "cancel" ? "Cancelling" : job.cancel_requested_at ? "Cancellation requested" : "Cancel job"}
          </button>
        {/if}
      </div>
      <dl class="detail-fields">
        <div>
          <dt>Source URL</dt>
          <dd><a href={job.source_url} target="_blank" rel="noreferrer">{job.source_url}</a></dd>
        </div>
        <div>
          <dt>Canonical URL</dt>
          <dd><code>{job.canonical_url}</code></dd>
        </div>
        <div>
          <dt>Source platform</dt>
          <dd>{job.source_platform}</dd>
        </div>
        <div>
          <dt>Destination platform</dt>
          <dd>{job.destination_platform}</dd>
        </div>
        <div>
          <dt>Destination</dt>
          <dd>{accountName(destinationAccount)}</dd>
        </div>
        <div>
          <dt>Destination account ID</dt>
          <dd><code>{job.destination_account_id}</code></dd>
        </div>
        <div>
          <dt>Caption override</dt>
          <dd class="caption-value">{job.caption_override === null ? "Source caption" : job.caption_override === "" ? "Intentionally blank" : job.caption_override}</dd>
        </div>
        <div>
          <dt>Resolved caption</dt>
          <dd class="caption-value">{job.resolved_caption ?? "Not resolved"}</dd>
        </div>
        <div>
          <dt>Attempt count</dt>
          <dd>{job.attempt_count}</dd>
        </div>
        <div>
          <dt>Error code</dt>
          <dd class:code-danger={job.error_code !== null}><code>{job.error_code ?? "None"}</code></dd>
        </div>
        <div>
          <dt>Creation ID</dt>
          <dd><code>{job.creation_id ?? "Not available"}</code></dd>
        </div>
        <div>
          <dt>Video ID</dt>
          <dd><code>{job.video_id ?? "Not available"}</code></dd>
        </div>
        <div>
          <dt>Post ID</dt>
          <dd><code>{job.post_id ?? "Not available"}</code></dd>
        </div>
        <div>
          <dt>Posted URL</dt>
          <dd>{#if job.posted_url}<a href={job.posted_url} target="_blank" rel="noreferrer">{job.posted_url}</a>{:else}Not available{/if}</dd>
        </div>
        <div>
          <dt>Cancel requested</dt>
          <dd>{formatDate(job.cancel_requested_at)}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{formatDate(job.created_at)}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{formatDate(job.updated_at)}</dd>
        </div>
        <div>
          <dt>Finished</dt>
          <dd>{formatDate(job.finished_at)}</dd>
        </div>
      </dl>
    {/if}
  </div>
</section>
<UnknownOutcomeDialog
  open={reviewOpen}
  busy={busyAction !== null}
  onclose={() => (reviewOpen = false)}
  onconfirm={() => void retry(true)}
/>
<style>
  .detail-empty {
    min-height: 150px;
    display: grid;
    align-content: center;
    color: var(--muted);
  }

  .detail-empty p {
    margin: 0;
  }

  .detail-loading {
    display: grid;
    gap: 14px;
    padding: 28px 0;
  }

  .detail-loading .skeleton {
    height: 14px;
  }

  .detail-state {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 9px;
    padding: 14px 0;
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
    color: var(--muted);
    font-size: 12px;
  }

  .detail-actions-main {
    margin: 16px 0;
  }

  .detail-fields {
    display: grid;
    gap: 0;
    margin: 0;
  }

  .detail-fields > div {
    display: grid;
    grid-template-columns: 118px minmax(0, 1fr);
    gap: 14px;
    padding: 10px 0;
    border-bottom: 1px solid var(--line);
  }

  .detail-fields dt {
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
  }

  .detail-fields dd {
    min-width: 0;
    margin: 0;
    overflow-wrap: anywhere;
    font-size: 12px;
  }

  code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.95em;
  }

  .caption-value {
    white-space: pre-wrap;
  }

  .code-danger,
  .code-danger code {
    color: var(--danger);
  }
</style>
