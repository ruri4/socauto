<script lang="ts">
  import { api, errorMessage } from "../api";
  import type { AccountImportResponse } from "../types";

  const maxFileBytes = 1024 * 1024;

  let {
    open = false,
    onclose,
    onimported,
  } = $props<{
    open?: boolean;
    onclose: () => void;
    onimported: (response: AccountImportResponse) => void;
  }>();

  let dialog: HTMLDialogElement;
  let fileInput: HTMLInputElement;
  let selectedFile = $state<File | null>(null);
  let userAgent = $state("");
  let submitting = $state(false);
  let error = $state<string | null>(null);
  let lastOpen = false;

  function reset(): void {
    selectedFile = null;
    userAgent = "";
    submitting = false;
    error = null;
    if (fileInput) fileInput.value = "";
  }

  function close(): void {
    if (!submitting) onclose();
  }

  function showDialog(): void {
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      fileInput?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }

  $effect(() => {
    if (open && !lastOpen) reset();
    lastOpen = open;
  });

  $effect(showDialog);

  function selectFile(event: Event): void {
    error = null;
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    if (file && file.size > maxFileBytes) {
      selectedFile = null;
      input.value = "";
      error = "Cookie export files must be 1 MiB or smaller.";
      return;
    }
    selectedFile = file;
  }

  async function importAccount(): Promise<void> {
    error = null;
    if (!selectedFile) {
      error = "Choose a cookie export file.";
      return;
    }

    submitting = true;
    const formData = new FormData();
    formData.append("file", selectedFile, selectedFile.name);
    if (userAgent.trim()) formData.append("user_agent", userAgent.trim());

    try {
      const response = await api.importTikTok(formData);
      onimported(response);
    } catch (caught) {
      error = errorMessage(caught);
    } finally {
      selectedFile = null;
      userAgent = "";
      if (fileInput) fileInput.value = "";
      submitting = false;
    }
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    void importAccount();
  }
</script>

<dialog bind:this={dialog} aria-labelledby="import-account-title" oncancel={(event) => { event.preventDefault(); close(); }}>
  <div class="dialog-inner">
    <div class="dialog-heading">
      <h2 id="import-account-title">Import TikTok account</h2>
      <p>Cookie exports are sensitive credentials. socauto verifies the file and does not retain the upload or expose cookie contents.</p>
    </div>

    {#if error}
      <div class="inline-error" role="alert">{error}</div>
    {/if}

    <form class="dialog-form" onsubmit={submit}>
      <div class="field">
        <label for="cookie-file">Cookie export file</label>
        <input
          id="cookie-file"
          bind:this={fileInput}
          type="file"
          accept=".txt,.json,application/json,text/plain"
          onchange={selectFile}
          disabled={submitting}
          required
        />
        <p class="field-help">Netscape text or browser JSON, maximum 1 MiB. The file is held only for this submission.</p>
        {#if selectedFile}
          <p class="selected-file">Selected: {selectedFile.name}</p>
        {/if}
      </div>

      <div class="field">
        <label for="user-agent">Browser user agent <span class="optional">Optional</span></label>
        <input id="user-agent" bind:value={userAgent} maxlength="512" type="text" disabled={submitting} />
        <p class="field-help">Use the exporting browser's value when it differs from the server setting.</p>
      </div>

      <div class="dialog-actions">
        <button class="button" type="button" disabled={submitting} onclick={close}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={submitting || !selectedFile}>
          {submitting ? "Verifying" : "Verify and import"}
        </button>
      </div>
    </form>
  </div>
</dialog>

<style>
  .optional {
    color: var(--faint);
    font-weight: 500;
  }

  .selected-file {
    margin: 8px 0 0;
    overflow-wrap: anywhere;
    color: var(--text);
    font-size: 12px;
    font-weight: 650;
  }
</style>
