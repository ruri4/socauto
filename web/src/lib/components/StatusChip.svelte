<script lang="ts">
  import { statusLabel } from "../format";
  import type { AccountStatus, JobState } from "../types";
  import InfoTip from "./InfoTip.svelte";

  let { status } = $props<{ status: AccountStatus | JobState }>();
</script>

{#if status === "posted"}
  <InfoTip
    trigger="chip"
    triggerText={statusLabel(status)}
    chipClass={`status-chip status-${status}`}
    label="Posted status information"
    text="Posted means acknowledged, not confirmed visible."
  />
{:else}
  <span class={`status-chip status-${status}`}>
    {statusLabel(status)}
  </span>
{/if}
