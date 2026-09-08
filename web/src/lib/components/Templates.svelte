<script lang="ts">
  import { api, errorMessage } from "../api";
  import { utf16CodeUnits } from "../format";
  import type { CaptionTemplate } from "../types";

  let templates = $state<CaptionTemplate[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let dialog = $state<HTMLDialogElement>();
  let editing = $state<CaptionTemplate | null>(null);
  let name = $state("");
  let body = $state("");
  let busy = $state(false);
  let deletingId = $state<string | null>(null);
  let formError = $state<string | null>(null);
  const units = $derived(utf16CodeUnits(body));
  const tooLong = $derived(units > 2200);

  async function load(): Promise<void> {
    loading = true;
    error = null;
    try {
      templates = (await api.listTemplates()).items;
    } catch (caught) {
      error = errorMessage(caught);
    } finally {
      loading = false;
    }
  }

  function openCreate(): void {
    editing = null;
    name = "";
    body = "";
    formError = null;
    dialog?.showModal();
  }

  function openEdit(template: CaptionTemplate): void {
    editing = template;
    name = template.name;
    body = template.body;
    formError = null;
    dialog?.showModal();
  }

  function close(): void {
    if (!busy) dialog?.close();
  }

  async function save(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    formError = null;
    if (!name.trim()) {
      formError = "Enter a template name.";
      return;
    }
    if (tooLong) {
      formError = "The template exceeds 2,200 UTF-16 code units.";
      return;
    }
    busy = true;
    try {
      if (editing) {
        await api.updateTemplate(editing.id, { name: name.trim(), body });
      } else {
        await api.createTemplate({ name: name.trim(), body });
      }
      dialog?.close();
      await load();
    } catch (caught) {
      formError = errorMessage(caught);
    } finally {
      busy = false;
    }
  }

  async function remove(template: CaptionTemplate): Promise<void> {
    if (!window.confirm(`Delete template “${template.name}”? Existing job snapshots remain unchanged.`)) {
      return;
    }
    deletingId = template.id;
    error = null;
    try {
      await api.deleteTemplate(template.id);
      await load();
    } catch (caught) {
      error = errorMessage(caught);
    } finally {
      deletingId = null;
    }
  }

  void load();
</script>

<section class="workspace-column" aria-labelledby="templates-title">
  <div class="section-heading">
    <div>
      <h2 id="templates-title">Caption templates</h2>
      <p>Reusable local patterns. Jobs keep an immutable name and body snapshot.</p>
    </div>
    <div class="heading-actions">
      <button class="button button-small" type="button" disabled={loading} onclick={() => void load()}>
        Refresh
      </button>
      <button class="button button-primary button-small" type="button" onclick={openCreate}>New template</button>
    </div>
  </div>

  {#if error}
    <div class="inline-error" role="alert">{error}</div>
  {/if}
  {#if loading}
    <div class="skeleton-list" aria-label="Loading templates" aria-busy="true">
      {#each Array(3) as _}
        <div class="skeleton-row"><span class="skeleton medium"></span><span class="skeleton"></span></div>
      {/each}
    </div>
  {:else if templates.length === 0}
    <div class="empty-state">
      <h3>No saved templates</h3>
      <p>Create a reusable caption shape, then select it when queueing a job.</p>
      <button class="button button-primary button-small" type="button" onclick={openCreate}>Create template</button>
    </div>
  {:else}
    <div class="template-list">
      {#each templates as template (template.id)}
        <article class="template-row">
          <div>
            <h3>{template.name}</h3>
            <pre>{template.body}</pre>
          </div>
          <div class="row-actions">
            <button class="button button-small" type="button" onclick={() => openEdit(template)}>Edit</button>
            <button class="button button-danger button-small" type="button" disabled={deletingId !== null} onclick={() => void remove(template)}>
              {deletingId === template.id ? "Deleting" : "Delete"}
            </button>
          </div>
        </article>
      {/each}
    </div>
  {/if}
</section>

<dialog bind:this={dialog} aria-labelledby="template-dialog-title" oncancel={(event) => { event.preventDefault(); close(); }}>
  <div class="dialog-inner">
    <div class="dialog-heading">
      <h2 id="template-dialog-title">{editing ? "Edit template" : "Create template"}</h2>
      <p>Only exact <code>{"{{caption}}"}</code> is replaced. Its source caption is inserted literally.</p>
    </div>
    {#if formError}<div class="inline-error" role="alert">{formError}</div>{/if}
    <form class="dialog-form" onsubmit={(event) => void save(event)}>
      <div class="field">
        <label for="template-name">Template name</label>
        <input id="template-name" bind:value={name} maxlength="80" disabled={busy} required />
      </div>
      <div class="field">
        <label for="template-body">Template body</label>
        <textarea id="template-body" bind:value={body} aria-invalid={tooLong} disabled={busy}></textarea>
        <p class:over-limit={tooLong} class="field-help caption-count">{units.toLocaleString()} / 2,200 UTF-16 code units</p>
        <p class="field-help">Single braces are literal. Whitespace in or unknown double braces is invalid. Empty bodies are valid.</p>
      </div>
      <div class="dialog-actions">
        <button class="button" type="button" disabled={busy} onclick={close}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={busy || tooLong}>{busy ? "Saving" : "Save template"}</button>
      </div>
    </form>
  </div>
</dialog>

<style>
  .template-list { border-top: 1px solid var(--line); }
  .template-row { display: flex; justify-content: space-between; gap: 20px; padding: 18px 0; border-bottom: 1px solid var(--line); }
  .template-row > div:first-child { min-width: 0; }
  .template-row h3 { margin: 0; font-size: 15px; }
  .template-row pre { margin: 8px 0 0; color: var(--muted); font: inherit; white-space: pre-wrap; overflow-wrap: anywhere; }
  .row-actions { display: flex; align-items: start; gap: 8px; flex: 0 0 auto; }
  .caption-count { text-align: right; }
  .over-limit { color: var(--danger); font-weight: 700; }
  @media (max-width: 680px) { .template-row { display: grid; } .row-actions { justify-content: flex-start; } }
</style>
