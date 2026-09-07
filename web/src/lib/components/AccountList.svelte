<script lang="ts">
  import { api, ApiError, errorMessage } from "../api";
  import { formatDate } from "../format";
  import type { Account } from "../types";
  import StatusChip from "./StatusChip.svelte";

  let {
    accounts,
    total,
    offset,
    limit,
    loading,
    error,
    onrefresh,
    onaccountchange,
    onprevious,
    onnext,
  } = $props<{
    accounts: Account[];
    total: number;
    offset: number;
    limit: number;
    loading: boolean;
    error: string | null;
    onrefresh: () => void;
    onaccountchange: () => void;
    onprevious: () => void;
    onnext: () => void;
  }>();

  let deleteDialog: HTMLDialogElement;
  let keepAccountButton = $state<HTMLButtonElement>();
  let accountToDelete = $state<Account | null>(null);
  let deleteError = $state<string | null>(null);
  let actionBusy = $state<string | null>(null);
  let actionError = $state<string | null>(null);

  const rangeStart = $derived(total === 0 ? 0 : offset + 1);
  const rangeEnd = $derived(Math.min(offset + accounts.length, total));

  $effect(() => {
    if (!deleteDialog) return;
    if (accountToDelete && !deleteDialog.open) {
      deleteDialog.showModal();
      keepAccountButton?.focus();
    } else if (!accountToDelete && deleteDialog.open) {
      deleteDialog.close();
    }
  });

  function askDelete(account: Account): void {
    deleteError = null;
    accountToDelete = account;
  }

  function closeDelete(): void {
    accountToDelete = null;
    deleteError = null;
  }

  async function validate(account: Account): Promise<void> {
    actionBusy = account.id;
    actionError = null;
    try {
      await api.validateAccount(account.id);
    } catch (caught) {
      actionError = `${account.handle ? `@${account.handle}` : "Account"}: ${errorMessage(caught)}`;
    } finally {
      actionBusy = null;
      onaccountchange();
    }
  }

  async function confirmDelete(): Promise<void> {
    if (!accountToDelete) return;
    actionBusy = accountToDelete.id;
    deleteError = null;
    try {
      await api.deleteAccount(accountToDelete.id);
      closeDelete();
      onaccountchange();
    } catch (caught) {
      deleteError =
        caught instanceof ApiError && caught.code === "account_in_use"
          ? "This account is referenced by existing jobs and cannot be removed."
          : errorMessage(caught);
    } finally {
      actionBusy = null;
    }
  }
</script>

<section class="accounts-list" aria-labelledby="accounts-list-title">
  <div class="section-heading">
    <div>
      <h2 id="accounts-list-title">Connected accounts</h2>
      <p>Stored account metadata only. Session files and cookie values never appear here.</p>
    </div>
    <button class="button button-small" type="button" disabled={loading} onclick={onrefresh}>
      {loading ? "Loading" : "Refresh accounts"}
    </button>
  </div>

  {#if error}
    <div class="inline-error" role="alert">{error}</div>
  {/if}
  {#if actionError}
    <div class="inline-error" role="alert">{actionError}</div>
  {/if}

  {#if loading}
    <div class="skeleton-list" aria-label="Loading accounts" aria-busy="true">
      {#each [1, 2] as item}
        <div class="skeleton-row" aria-hidden="true">
          <span class="skeleton short"></span>
          <span class="skeleton medium"></span>
          <span class="skeleton"></span>
        </div>
      {/each}
    </div>
  {:else if accounts.length === 0}
    <div class="empty-state">
      <h3>No TikTok accounts connected</h3>
      <p>Import a cookie export from an already authenticated browser. The export is sensitive and is not retained.</p>
    </div>
  {:else}
    <div class="account-list" aria-label="Connected accounts">
      {#each accounts as account (account.id)}
        <article class="account-row">
          <div class="account-main">
            <div class="row-topline">
              <StatusChip status={account.status} />
              <span class="account-platform">{account.platform}</span>
            </div>
            <h3>{account.handle ? `@${account.handle}` : "Handle unavailable"}</h3>
            <dl class="account-meta">
              <div><dt>Account ID</dt><dd><code>{account.id}</code></dd></div>
              <div><dt>User ID</dt><dd><code>{account.platform_user_id ?? "Not available"}</code></dd></div>
              <div><dt>Updated</dt><dd>{formatDate(account.updated_at)}</dd></div>
              <div><dt>Created</dt><dd>{formatDate(account.created_at)}</dd></div>
            </dl>
          </div>
          <div class="row-actions account-actions">
            <button class="button button-small" type="button" disabled={actionBusy !== null} onclick={() => void validate(account)}>
              {actionBusy === account.id ? "Checking" : "Validate session"}
            </button>
            <button class="button button-danger button-small" type="button" disabled={actionBusy !== null} onclick={() => askDelete(account)}>
              Remove account
            </button>
          </div>
        </article>
      {/each}
    </div>
  {/if}

  <div class="pagination">
    <span>{rangeStart} to {rangeEnd} of {total} accounts</span>
    <div class="pagination-buttons">
      <button class="button button-small" type="button" disabled={offset === 0 || loading} onclick={onprevious}>Newer</button>
      <button class="button button-small" type="button" disabled={offset + limit >= total || loading} onclick={onnext}>Older</button>
    </div>
  </div>
</section>

<dialog bind:this={deleteDialog} aria-labelledby="delete-account-title" oncancel={(event) => { event.preventDefault(); closeDelete(); }} onclose={closeDelete}>
  <div class="dialog-inner">
    <div class="dialog-heading">
      <h2 id="delete-account-title">Remove account?</h2>
      <p>This removes the account record and its stored session file. Existing jobs keep their history and may block deletion.</p>
    </div>
    {#if deleteError}
      <div class="inline-error" role="alert">{deleteError}</div>
    {/if}
    <div class="delete-target">
      <strong>{accountToDelete?.handle ? `@${accountToDelete.handle}` : "This TikTok account"}</strong>
      <span>{accountToDelete?.id}</span>
    </div>
    <div class="dialog-actions">
      <button bind:this={keepAccountButton} class="button" type="button" disabled={actionBusy !== null} onclick={closeDelete}>Keep account</button>
      <button class="button button-danger" type="button" disabled={actionBusy !== null} onclick={() => void confirmDelete()}>
        {actionBusy ? "Removing" : "Remove account"}
      </button>
    </div>
  </div>
</dialog>

<style>
  .accounts-list {
    min-width: 0;
  }

  .account-list {
    border-top: 1px solid var(--line);
  }

  .account-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 20px;
    min-height: 146px;
    padding: 20px 0;
    border-bottom: 1px solid var(--line);
  }

  .account-main h3 {
    margin: 9px 0 10px;
    font-size: 17px;
    letter-spacing: -0.025em;
  }

  .account-platform {
    color: var(--muted);
    font-size: 12px;
    text-transform: uppercase;
  }

  .account-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 7px 18px;
    margin: 0;
    color: var(--muted);
    font-size: 12px;
  }

  .account-meta div {
    display: flex;
    gap: 5px;
  }

  .account-meta dt {
    font-weight: 700;
  }

  .account-meta dd {
    margin: 0;
  }

  .account-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .delete-target {
    display: grid;
    gap: 5px;
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
    padding: 15px 0;
  }

  .delete-target span {
    color: var(--muted);
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11px;
    overflow-wrap: anywhere;
  }
</style>
