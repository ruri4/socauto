<script lang="ts">
  import { accountName, formatDate } from "../format";
  import type { Account, Job, JobFilters, JobState } from "../types";
  import StatusChip from "./StatusChip.svelte";

  const states: JobState[] = [
    "pending",
    "downloading",
    "downloaded",
    "uploading",
    "posted",
    "failed",
    "cancelled",
  ];

  let {
    jobs,
    accounts,
    total,
    offset,
    limit,
    selectedJobId = null,
    filters,
    loading,
    error,
    onfilterschange,
    onrefresh,
    onopen,
    oncreate,
    onprevious,
    onnext,
  } = $props<{
    jobs: Job[];
    accounts: Account[];
    total: number;
    offset: number;
    limit: number;
    selectedJobId?: string | null;
    filters: JobFilters;
    loading: boolean;
    error: string | null;
    onfilterschange: (filters: JobFilters) => void;
    onrefresh: () => void;
    onopen: (id: string) => void;
    oncreate: () => void;
    onprevious: () => void;
    onnext: () => void;
  }>();

  const accountById = $derived(
    new Map<string, Account>(accounts.map((account: Account) => [account.id, account])),
  );
  const hasFilters = $derived(Boolean(filters.state || filters.destinationAccountId));
  const rangeStart = $derived(total === 0 ? 0 : offset + 1);
  const rangeEnd = $derived(Math.min(offset + jobs.length, total));

  function updateState(event: Event): void {
    onfilterschange({
      ...filters,
      state: (event.currentTarget as HTMLSelectElement).value as JobState | "",
    });
  }

  function updateAccount(event: Event): void {
    onfilterschange({
      ...filters,
      destinationAccountId: (event.currentTarget as HTMLSelectElement).value,
    });
  }
</script>

<section class="workspace-column" aria-labelledby="jobs-heading">
  <div class="section-heading">
    <div>
      <h2 id="jobs-heading">Jobs</h2>
      <p>Queue, review, and control private TikTok publications.</p>
    </div>
    <div class="heading-actions">
      <button class="button button-small" type="button" disabled={loading} onclick={onrefresh}>
        {loading ? "Loading" : "Refresh jobs"}
      </button>
      <button class="button button-primary button-small" type="button" onclick={oncreate}>
        New job
      </button>
    </div>
  </div>

  <div class="filter-bar" aria-label="Job filters">
    <div class="field filter-field">
      <label for="job-state">State</label>
      <select id="job-state" value={filters.state} onchange={updateState}>
        <option value="">All states</option>
        {#each states as state}
          <option value={state}>{state[0].toUpperCase() + state.slice(1)}</option>
        {/each}
      </select>
    </div>
    <div class="field filter-field account-filter">
      <label for="job-account">Destination account</label>
      <select id="job-account" value={filters.destinationAccountId} onchange={updateAccount}>
        <option value="">All accounts</option>
        {#each accounts as account}
          <option value={account.id}>{accountName(account)} · {account.status}</option>
        {/each}
      </select>
    </div>
    {#if hasFilters}
      <button
        class="button button-quiet button-small clear-filter"
        type="button"
        onclick={() => onfilterschange({ state: "", destinationAccountId: "" })}
      >
        Clear filters
      </button>
    {/if}
  </div>

  {#if error}
    <div class="inline-error" role="alert">{error}</div>
  {/if}

  {#if loading}
    <div class="skeleton-list" aria-label="Loading jobs" aria-busy="true">
      {#each [1, 2, 3] as item}
        <div class="skeleton-row" aria-hidden="true">
          <span class="skeleton short"></span>
          <span class="skeleton medium"></span>
          <span class="skeleton"></span>
        </div>
      {/each}
    </div>
  {:else if jobs.length === 0}
    <div class="empty-state">
      <h3>{hasFilters ? "No matching jobs" : "No jobs yet"}</h3>
      <p>
        {hasFilters
          ? "Try another state or destination account."
          : "Create a job from an X video URL once an active TikTok account is connected."}
      </p>
      {#if !hasFilters}
        <button class="button button-primary button-small" type="button" onclick={oncreate}>
          Create first job
        </button>
      {/if}
    </div>
  {:else}
    <div class="job-list" aria-label="Jobs">
      {#each jobs as job (job.id)}
        <article class:job-selected={job.id === selectedJobId} class="job-row">
          <div class="job-main">
            <div class="row-topline">
              <StatusChip status={job.state} />
              <span class="row-time">Updated {formatDate(job.updated_at)}</span>
            </div>
            <a class="source-link" href={job.source_url} target="_blank" rel="noreferrer">{job.canonical_url}</a>
            <p class="job-destination">TikTok · {accountName(accountById.get(job.destination_account_id))}</p>
            {#if job.error_code}
              <p class="job-error-code">{job.error_code}</p>
            {/if}
          </div>
          <div class="row-actions">
            <span class="attempt-count">Attempt {job.attempt_count}</span>
            <button class="button button-small" type="button" onclick={() => onopen(job.id)}>
              Open detail
            </button>
          </div>
        </article>
      {/each}
    </div>
  {/if}

  <div class="pagination">
    <span>{rangeStart} to {rangeEnd} of {total} jobs</span>
    <div class="pagination-buttons">
      <button class="button button-small" type="button" disabled={offset === 0 || loading} onclick={onprevious}>
        Newer
      </button>
      <button
        class="button button-small"
        type="button"
        disabled={offset + limit >= total || loading}
        onclick={onnext}
      >
        Older
      </button>
    </div>
  </div>
  <p class="private-note list-note">Posted means the API acknowledged a publication, not that it is confirmed visible.</p>
</section>

<style>
  .filter-field {
    width: min(180px, 100%);
  }

  .account-filter {
    width: min(260px, 100%);
  }

  .clear-filter {
    margin-left: auto;
  }

  .job-list {
    border-top: 1px solid var(--line);
  }

  .job-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 18px;
    min-height: 116px;
    padding: 17px 0;
    border-bottom: 1px solid var(--line);
    transition: transform 160ms cubic-bezier(0.2, 0.8, 0.2, 1);
  }

  .job-row.job-selected {
    margin-inline: -10px;
    padding-inline: 10px;
    border-radius: 10px;
    background: var(--surface-soft);
  }

  .job-main {
    min-width: 0;
  }

  .row-topline,
  .row-actions {
    display: flex;
    align-items: center;
    gap: 9px;
  }

  .row-time,
  .attempt-count {
    color: var(--muted);
    font-size: 12px;
  }

  .source-link {
    display: block;
    max-width: 100%;
    margin-top: 9px;
    overflow: hidden;
    font-weight: 720;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .job-destination,
  .job-error-code {
    margin: 5px 0 0;
    color: var(--muted);
    font-size: 12px;
  }

  .job-error-code {
    color: var(--danger);
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }

  .row-actions {
    justify-content: flex-end;
    flex-wrap: wrap;
  }

  .pagination-buttons {
    display: flex;
    gap: 8px;
  }

  .list-note {
    margin-top: 20px;
  }
</style>
