<script lang="ts">
  import { api, ApiError, errorMessage } from "../api";
  import { accountName, utf16CodeUnits } from "../format";
  import type { Account, CaptionMode, CaptionTemplate, Job, JobVisibility } from "../types";

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
  let visibility = $state<JobVisibility>("private");
  let captionMode = $state<CaptionMode>("source");
  let overrideCaption = $state("");
  let customTemplate = $state("");
  let templates = $state<CaptionTemplate[]>([]);
  let templatesLoading = $state(false);
  let templatesError = $state<string | null>(null);
  let templateId = $state("");
  let submitting = $state(false);
  let error = $state<string | null>(null);
  let duplicateJobId = $state<string | null>(null);
  let sourceUrlInput = $state<HTMLInputElement>();
  let lastOpen = false;

  const activeAccounts = $derived(
    accounts.filter((account: Account) => account.status === "active"),
  );
  const overrideCaptionCodeUnits = $derived(utf16CodeUnits(overrideCaption));
  const customTemplateCodeUnits = $derived(utf16CodeUnits(customTemplate));
  const captionTooLong = $derived(
    (captionMode === "override" && overrideCaptionCodeUnits > 2200) ||
      (captionMode === "custom_template" && customTemplateCodeUnits > 2200),
  );
  const selectedTemplate = $derived(templates.find((template) => template.id === templateId));

  function reset(): void {
    sourceUrl = "";
    accountId = activeAccounts[0]?.id ?? "";
    visibility = "private";
    captionMode = "source";
    overrideCaption = "";
    customTemplate = "";
    templateId = "";
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

  $effect(() => {
    if (!open) return;
    templatesLoading = true;
    templatesError = null;
    void api.listTemplates().then(
      (page) => {
        templates = page.items;
        if (!templateId) templateId = page.items[0]?.id ?? "";
      },
      (caught: unknown) => (templatesError = errorMessage(caught)),
    ).finally(() => (templatesLoading = false));
  });

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
    if (captionMode === "saved_template" && !templateId) {
      error = "Select a saved template or create one in Templates.";
      return;
    }

    submitting = true;
    try {
      const job = await api.createJob({
        source_url: sourceUrl.trim(),
        destination_account_id: accountId,
        caption_override: captionMode === "override" ? overrideCaption : null,
        caption_mode: captionMode,
        caption_template_id: captionMode === "saved_template" ? templateId : null,
        caption_template: captionMode === "custom_template" ? customTemplate : null,
        visibility,
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
      <p>Queue one X video for the selected TikTok visibility. Private is the default; public can be viewed by anyone. The separate worker handles media work.</p>
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

        <div class="field">
          <label for="visibility">TikTok visibility</label>
          <select id="visibility" bind:value={visibility} aria-describedby="visibility-help" disabled={submitting}>
            <option value="private">Only you (private)</option>
            <option value="public">Public</option>
          </select>
          <p id="visibility-help" class="field-help">Private is the default. Public can be viewed by anyone.</p>
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
          <label class="choice-row">
            <input type="radio" bind:group={captionMode} value="saved_template" disabled={submitting} />
            <span>Use a saved template</span>
          </label>
          <label class="choice-row">
            <input type="radio" bind:group={captionMode} value="custom_template" disabled={submitting} />
            <span>Use a one-off custom template</span>
          </label>
        </fieldset>

        {#if captionMode === "override"}
          <div class="field">
            <label for="caption">Caption override</label>
            <textarea
              id="caption"
              bind:value={overrideCaption}
              aria-invalid={overrideCaptionCodeUnits > 2200}
              disabled={submitting}
              placeholder="Leave blank to publish without a caption"
            ></textarea>
            <p class:over-limit={overrideCaptionCodeUnits > 2200} class="field-help caption-count">
              {overrideCaptionCodeUnits.toLocaleString()} / 2,200 UTF-16 code units
            </p>
          </div>
        {/if}

        {#if captionMode === "saved_template"}
          <div class="field">
            <label for="saved-template">Saved template</label>
            {#if templatesLoading}
              <p class="field-help">Loading saved templates.</p>
            {:else if templatesError}
              <p class="text-danger field-help">{templatesError}</p>
            {:else if templates.length === 0}
              <p class="field-help">No saved templates. Open Templates in the panel to create one.</p>
            {:else}
              <select id="saved-template" bind:value={templateId} disabled={submitting} required>
                {#each templates as template}
                  <option value={template.id}>{template.name}</option>
                {/each}
              </select>
              <p class="template-preview">{selectedTemplate?.body ?? ""}</p>
            {/if}
          </div>
        {:else if captionMode === "custom_template"}
          <div class="field">
            <label for="custom-template">Custom template</label>
            <textarea id="custom-template" bind:value={customTemplate} aria-invalid={customTemplateCodeUnits > 2200} disabled={submitting}></textarea>
            <p class:over-limit={customTemplateCodeUnits > 2200} class="field-help caption-count">{customTemplateCodeUnits.toLocaleString()} / 2,200 UTF-16 code units</p>
          </div>
        {/if}
        {#if captionMode === "saved_template" || captionMode === "custom_template"}
          <p class="field-help">Use exact <code>{"{{caption}}"}</code> to insert the normalized X caption. Other double braces are invalid; custom templates are not saved.</p>
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

  .template-preview {
    margin: 0;
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 10px;
    background: var(--surface-soft);
    white-space: pre-wrap;
  }
</style>
