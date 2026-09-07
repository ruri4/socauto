<script lang="ts">
  import { api, ApiError, errorMessage } from "../api";
  import { accountName, utf16CodeUnits } from "../format";
  import type { Account, Job } from "../types";

  let {
    open = false,
    accounts,
    onclose,
    oncreated,
    onopenexisting,
    onaccounts,
  } = $props<{
    open?: boolean;
    accounts: Account[];
    onclose: () => void;
    oncreated: (job: Job) => void;
    onopenexisting: (id: string) => void;
    onaccounts: () => void;
  }>();

  let dialog: HTMLDialogElement;
  let sourceUrl = $state("");
  let accountId = $state("");
  let captionMode = $state<"source" | "override">("source");
  let caption = $state("");
  let submitting = $state(false);
  let error = $state<string | null>(null);
  let duplicateJobId = $state<string | null>(null);
  let sourceUrlInput = $state<HTMLInputElement>();
  let lastOpen = false;

  const activeAccounts = $derived(
    accounts.filter((account: Account) => account.status === "active"),
  );
  const captionCodeUnits = $derived(utf16CodeUnits(caption));
  const captionTooLong = $derived(captionCodeUnits > 2200);

  function reset(): void {
    sourceUrl = "";
    accountId = activeAccounts[0]?.id ?? "";
    captionMode = "source";
    caption = "";
    submitting = false;
    error = null;
    duplicateJobId = null;
  }

  function close(): void {
    if (!submitting) onclose();
  }

  function showDialog(): void {
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      sourceUrlInput?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }

  $effect(() => {
    if (open && !lastOpen) reset();
    lastOpen = open;
  });

  $effect(showDialog);

  async function createJob(): Promise<void> {
    error = null;
    duplicateJobId = null;
    if (!sourceUrl.trim()) {
      error = "Enter an X video URL.";
      return;
    }
    if (!accountId) {
      error = "Select an active TikTok account before creating a job.";
      return;
    }
    if (captionTooLong) {
      error = "The caption exceeds 2,200 UTF-16 code units.";
      return;
    }

    submitting = true;
    try {
      const job = await api.createJob({
        source_url: sourceUrl.trim(),
        destination_account_id: accountId,
        caption_override: captionMode === "source" ? null : caption,
      });
      oncreated(job);
    } catch (caught) {
      error = errorMessage(caught);
      if (caught instanceof ApiError && caught.code === "duplicate_job" && caught.existingJobId) {
        duplicateJobId = caught.existingJobId;
      }
    } finally {
      submitting = false;
    }
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    void createJob();
  }
</script>

<dialog bind:this={dialog} aria-labelledby="create-job-title" oncancel={(event) => { event.preventDefault(); close(); }}>
  <div class="dialog-inner">
    <div class="dialog-heading">
      <h2 id="create-job-title">Create job</h2>
      <p>Queue one X video for private-only TikTok publication. The separate worker handles media work.</p>
    </div>

    {#if error}
      <div class="inline-error" role="alert">
        <div>{error}</div>
        {#if duplicateJobId}
          <button class="button button-small duplicate-action" type="button" onclick={() => onopenexisting(duplicateJobId!)}>
            Open existing job
          </button>
        {/if}
      </div>
    {/if}

    {#if activeAccounts.length === 0}
      <div class="empty-state compact-empty">
        <h3>No active TikTok account</h3>
        <p>Import a sensitive cookie export before queueing a publication.</p>
        <button class="button button-primary button-small" type="button" onclick={() => { close(); onaccounts(); }}>
          Go to Accounts
        </button>
      </div>
    {:else}
      <form class="dialog-form" onsubmit={submit}>
        <div class="field">
          <label for="source-url">X video URL</label>
          <input
            id="source-url"
            bind:this={sourceUrlInput}
            bind:value={sourceUrl}
            type="url"
            autocomplete="url"
            placeholder="https://x.com/account/status/123"
            required
            disabled={submitting}
          />
          <p class="field-help">Only supported X post URLs are accepted by the API.</p>
        </div>

        <div class="field">
          <label for="destination-account">Destination account</label>
          <select id="destination-account" bind:value={accountId} disabled={submitting} required>
            <option value="" disabled>Select an active account</option>
            {#each activeAccounts as account}
              <option value={account.id}>{accountName(account)}</option>
            {/each}
          </select>
        </div>

        <fieldset class="caption-fieldset">
          <legend>Caption</legend>
          <label class="choice-row">
            <input type="radio" bind:group={captionMode} value="source" disabled={submitting} />
            <span>Use the source caption</span>
          </label>
          <label class="choice-row">
            <input type="radio" bind:group={captionMode} value="override" disabled={submitting} />
            <span>Use an override, including an intentionally blank caption</span>
          </label>
        </fieldset>

        {#if captionMode === "override"}
          <div class="field">
            <label for="caption">Caption override</label>
            <textarea
              id="caption"
              bind:value={caption}
              aria-invalid={captionTooLong}
              disabled={submitting}
              placeholder="Leave blank to publish without a caption"
            ></textarea>
            <p class:over-limit={captionTooLong} class="field-help caption-count">
              {captionCodeUnits.toLocaleString()} / 2,200 UTF-16 code units
            </p>
          </div>
        {/if}

        <div class="dialog-actions">
          <button class="button" type="button" disabled={submitting} onclick={close}>Cancel</button>
          <button class="button button-primary" type="submit" disabled={submitting || captionTooLong}>
            {submitting ? "Queueing" : "Queue job"}
          </button>
        </div>
      </form>
    {/if}
  </div>
</dialog>

<style>
  .caption-fieldset {
    display: grid;
    gap: 9px;
    margin: 0;
    border: 0;
    padding: 0;
  }

  .caption-fieldset legend {
    margin-bottom: 1px;
    color: var(--muted);
    font-size: 12px;
    font-weight: 720;
  }

  .choice-row {
    display: flex;
    align-items: start;
    gap: 9px;
    color: var(--text);
    font-size: 13px;
  }

  .choice-row input {
    flex: 0 0 auto;
    margin: 3px 0 0;
    accent-color: var(--accent);
  }

  .caption-count {
    text-align: right;
  }

  .over-limit {
    color: var(--danger);
    font-weight: 700;
  }

  .duplicate-action {
    margin-top: 9px;
  }

  .compact-empty {
    padding: 24px 0 8px;
  }
</style>
