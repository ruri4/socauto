<script lang="ts">
  let {
    open = false,
    busy = false,
    onclose,
    onconfirm,
  } = $props<{
    open?: boolean;
    busy?: boolean;
    onclose: () => void;
    onconfirm: () => void;
  }>();

  let dialog: HTMLDialogElement;
  let checkbox: HTMLInputElement;
  let inspected = $state(false);

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      checkbox?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  });

  $effect(() => {
    if (!open) inspected = false;
  });

  function confirm(): void {
    if (inspected && !busy) onconfirm();
  }
</script>

<dialog
  bind:this={dialog}
  aria-labelledby="unknown-outcome-title"
  oncancel={(event) => { event.preventDefault(); onclose(); }}
  onclose={onclose}
>
  <div class="dialog-inner">
    <div class="dialog-heading">
      <h2 id="unknown-outcome-title">Review TikTok before retrying</h2>
      <p>The original upload outcome is unknown. If TikTok accepted it, retrying can create a duplicate publication.</p>
    </div>
    <label class="review-choice">
      <input bind:this={checkbox} bind:checked={inspected} type="checkbox" />
      <span>I inspected TikTok and understand the duplicate risk.</span>
    </label>
    <div class="dialog-actions">
      <button class="button" type="button" onclick={onclose}>Keep job failed</button>
      <button class="button button-primary" type="button" disabled={!inspected || busy} onclick={confirm}>
        {busy ? "Retrying" : "Acknowledge and retry"}
      </button>
    </div>
  </div>
</dialog>

<style>
  .review-choice {
    display: flex;
    align-items: start;
    gap: 10px;
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 12px;
    font-size: 13px;
  }

  .review-choice input {
    flex: 0 0 auto;
    margin: 3px 0 0;
    accent-color: var(--accent);
  }
</style>
