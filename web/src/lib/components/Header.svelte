<script lang="ts">
  type Workspace = "jobs" | "accounts" | "templates";
  import InfoTip from "./InfoTip.svelte";

  let {
    workspace,
    apiOnline,
    refreshing = false,
    onworkspace,
    onrefresh,
  } = $props<{
    workspace: Workspace;
    apiOnline: boolean | null;
    refreshing?: boolean;
    onworkspace: (workspace: Workspace) => void;
    onrefresh: () => void;
  }>();
</script>

<header class="topbar">
  <div class="brand" aria-label="socauto operator panel">
    <span class="brand-mark" aria-hidden="true"></span>
    <span>socauto</span>
  </div>

  <nav class="primary-nav" aria-label="Primary workspace">
    <button
      class:tab-active={workspace === "jobs"}
      class="nav-button"
      type="button"
      aria-current={workspace === "jobs" ? "page" : undefined}
      onclick={() => onworkspace("jobs")}
    >
      Jobs
    </button>
    <button
      class:tab-active={workspace === "accounts"}
      class="nav-button"
      type="button"
      aria-current={workspace === "accounts" ? "page" : undefined}
      onclick={() => onworkspace("accounts")}
    >
      Accounts
    </button>
    <button
      class:tab-active={workspace === "templates"}
      class="nav-button"
      type="button"
      aria-current={workspace === "templates" ? "page" : undefined}
      onclick={() => onworkspace("templates")}
    >
      Templates
    </button>
  </nav>

  <div class="api-status" aria-live="polite">
    <span class:online={apiOnline === true} class:offline={apiOnline === false} class="status-dot"></span>
    <span>{apiOnline === true ? "API online" : apiOnline === false ? "API offline" : "Checking API"}</span>
    <span class="api-qualifier">API only</span>
    <InfoTip align="end" label="API status information" text="This checks only the local API. It does not confirm worker activity, account sessions, or TikTok availability." />
  </div>
  <button class="button button-small" type="button" disabled={refreshing} onclick={onrefresh}>
    {refreshing ? "Refreshing" : "Refresh"}
  </button>
</header>
