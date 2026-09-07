<script lang="ts">
  import { statusLabel } from "../format";
  import type { AccountStatus, JobState } from "../types";

  let { status } = $props<{ status: AccountStatus | JobState }>();
</script>

<span class={`status-chip status-${status}`}>
  {statusLabel(status)}
</span>
