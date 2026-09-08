<script lang="ts">
  import { onMount } from "svelte";
  import { api, errorMessage } from "./lib/api";
  import { accountName, isActiveJob, visibilityLabel } from "./lib/format";
  import type {
    Account,
    AccountImportResponse,
    Job,
    JobFilters,
    Workspace,
  } from "./lib/types";
  import AccountImport from "./lib/components/AccountImport.svelte";
  import AccountList from "./lib/components/AccountList.svelte";
  import Header from "./lib/components/Header.svelte";
  import JobCreate from "./lib/components/JobCreate.svelte";
  import JobDetail from "./lib/components/JobDetail.svelte";
  import JobList from "./lib/components/JobList.svelte";

  const pageSize = 50;

  type Notice = { kind: "success" | "error"; message: string };

  let workspace = $state<Workspace>("jobs");
  let apiOnline = $state<boolean | null>(null);
  let refreshing = $state(false);
  let jobs = $state<Job[]>([]);
  let jobsTotal = $state(0);
  let jobsOffset = $state(0);
  let jobsLoading = $state(true);
  let jobsError = $state<string | null>(null);
  let jobsFilters = $state<JobFilters>({ state: "", destinationAccountId: "" });
  let accounts = $state<Account[]>([]);
  let accountsTotal = $state(0);
  let accountsOffset = $state(0);
  let accountsLoading = $state(true);
  let accountsError = $state<string | null>(null);
  let selectedJob = $state<Job | null>(null);
  let detailLoading = $state(false);
  let detailError = $state<string | null>(null);
  let createJobOpen = $state(false);
  let importAccountOpen = $state(false);
  let notice = $state<Notice | null>(null);
  let pollTimer: number | undefined;
  let pollBusy = false;
  let mounted = false;

  const hasActiveJobs = $derived(
    jobs.some((job) => isActiveJob(job)) || isActiveJob(selectedJob),
  );
  function setNotice(kind: Notice["kind"], message: string): void {
    notice = { kind, message };
  }

  async function checkHealth(): Promise<void> {
    try {
      const response = await api.health();
      apiOnline = response.status === "ok";
    } catch {
      apiOnline = false;
    }
  }

  async function loadAccounts(showLoading = true): Promise<void> {
    if (showLoading) accountsLoading = true;
    accountsError = null;
    try {
      const page = await api.listAccounts(accountsOffset, pageSize);
      accounts = page.items;
      accountsTotal = page.total;
    } catch (caught) {
      accountsError = errorMessage(caught);
    } finally {
      accountsLoading = false;
    }
  }

  async function loadJobs(showLoading = true): Promise<void> {
    if (showLoading) jobsLoading = true;
    jobsError = null;
    try {
      const page = await api.listJobs(jobsOffset, pageSize, jobsFilters);
      jobs = page.items;
      jobsTotal = page.total;
      if (selectedJob) {
        const listedJob = page.items.find((job) => job.id === selectedJob?.id);
        if (listedJob) selectedJob = listedJob;
      }
    } catch (caught) {
      jobsError = errorMessage(caught);
    } finally {
      jobsLoading = false;
      schedulePolling();
    }
  }

  async function openJob(id: string): Promise<void> {
    const listedJob = jobs.find((job) => job.id === id);
    selectedJob = listedJob ?? null;
    detailLoading = true;
    detailError = null;
    try {
      selectedJob = await api.getJob(id);
    } catch (caught) {
      detailError = errorMessage(caught);
    } finally {
      detailLoading = false;
      schedulePolling();
    }
  }

  function closeJob(): void {
    selectedJob = null;
    detailError = null;
    schedulePolling();
  }

  function updateJob(next: Job): void {
    selectedJob = next;
    jobs = jobs.map((job) => (job.id === next.id ? next : job));
    schedulePolling();
  }

  async function refreshSelectedJob(): Promise<void> {
    if (!selectedJob) return;
    await openJob(selectedJob.id);
  }

  async function refreshAll(): Promise<void> {
    if (refreshing) return;
    refreshing = true;
    await Promise.all([checkHealth(), loadJobs(), loadAccounts(), refreshSelectedJob()]);
    refreshing = false;
    schedulePolling();
  }

  function changeJobFilters(next: JobFilters): void {
    jobsFilters = next;
    jobsOffset = 0;
    void loadJobs();
  }

  function moveJobsPage(direction: number): void {
    jobsOffset = Math.max(0, jobsOffset + direction * pageSize);
    void loadJobs();
  }

  function moveAccountsPage(direction: number): void {
    accountsOffset = Math.max(0, accountsOffset + direction * pageSize);
    void loadAccounts();
  }

  function handleCreated(job: Job): void {
    createJobOpen = false;
    setNotice("success", `Job queued for ${visibilityLabel(job.visibility)} TikTok publication.`);
    jobsOffset = 0;
    void loadJobs().then(() => openJob(job.id));
  }

  function handleImported(response: AccountImportResponse): void {
    importAccountOpen = false;
    accountsOffset = 0;
    setNotice("success", `Imported ${accountName(response.account)}. The cookie file was not retained.`);
    void loadAccounts();
  }

  function schedulePolling(): void {
    if (pollTimer !== undefined) {
      window.clearTimeout(pollTimer);
      pollTimer = undefined;
    }
    if (!mounted || document.visibilityState === "hidden" || !hasActiveJobs) return;
    pollTimer = window.setTimeout(() => void pollActiveJobs(), 5000);
  }

  async function pollActiveJobs(): Promise<void> {
    if (pollBusy || document.visibilityState === "hidden" || !hasActiveJobs) {
      schedulePolling();
      return;
    }
    pollBusy = true;
    try {
      await loadJobs(false);
      if (selectedJob && isActiveJob(selectedJob) && !jobs.some((job) => job.id === selectedJob?.id)) {
        try {
          updateJob(await api.getJob(selectedJob.id));
        } catch (caught) {
          detailError = errorMessage(caught);
        }
      }
    } finally {
      pollBusy = false;
      schedulePolling();
    }
  }

  async function onVisible(): Promise<void> {
    if (document.visibilityState === "hidden") {
      schedulePolling();
      return;
    }
    await checkHealth();
    await loadJobs(false);
    schedulePolling();
  }

  onMount(() => {
    mounted = true;
    const visibilityHandler = () => void onVisible();
    document.addEventListener("visibilitychange", visibilityHandler);
    void Promise.all([checkHealth(), loadJobs(), loadAccounts()]).then(schedulePolling);

    return () => {
      mounted = false;
      if (pollTimer !== undefined) window.clearTimeout(pollTimer);
      document.removeEventListener("visibilitychange", visibilityHandler);
    };
  });
</script>

<div class="app-shell">
  <Header
    {workspace}
    {apiOnline}
    {refreshing}
    onworkspace={(next) => (workspace = next)}
    onrefresh={() => void refreshAll()}
  />

  <main class="shell-main">
    <div class="intro">
      <div>
        <h1>Operator panel</h1>
        <p>Local control for account sessions and the TikTok publication queue. Private is the default; public is explicit per job. API status here does not represent worker or TikTok health.</p>
      </div>
      <div class="intro-actions">
        {#if workspace === "jobs"}
          <button class="button button-primary" type="button" onclick={() => (createJobOpen = true)}>New job</button>
        {:else}
          <button class="button button-primary" type="button" onclick={() => (importAccountOpen = true)}>Import cookies</button>
        {/if}
      </div>
    </div>

    {#if notice}
      <div class:inline-success={notice.kind === "success"} class:inline-error={notice.kind === "error"} class="notice" role={notice.kind === "error" ? "alert" : "status"}>
        <span>{notice.message}</span>
        <button class="button button-quiet button-small" type="button" onclick={() => (notice = null)}>Dismiss</button>
      </div>
    {/if}

    {#if workspace === "jobs"}
      <div class="workspace-layout">
        <JobList
          {jobs}
          {accounts}
          total={jobsTotal}
          offset={jobsOffset}
          limit={pageSize}
          selectedJobId={selectedJob?.id ?? null}
          filters={jobsFilters}
          loading={jobsLoading}
          error={jobsError}
          onfilterschange={changeJobFilters}
          onrefresh={() => void loadJobs()}
          onopen={(id) => void openJob(id)}
          oncreate={() => (createJobOpen = true)}
          onprevious={() => moveJobsPage(-1)}
          onnext={() => moveJobsPage(1)}
        />
        <JobDetail
          job={selectedJob}
          {accounts}
          loading={detailLoading}
          error={detailError}
          onclose={closeJob}
          onrefresh={() => void refreshSelectedJob()}
          onjobchanged={updateJob}
        />
      </div>
    {:else}
      <AccountList
        {accounts}
        total={accountsTotal}
        offset={accountsOffset}
        limit={pageSize}
        loading={accountsLoading}
        error={accountsError}
        onrefresh={() => void loadAccounts()}
        onaccountchange={() => void loadAccounts(false)}
        onprevious={() => moveAccountsPage(-1)}
        onnext={() => moveAccountsPage(1)}
      />
      <p class="security-callout">Cookie files are sensitive credentials. Import happens locally through the loopback API, the upload is not retained, and this panel never reads or logs cookie contents.</p>
    {/if}
  </main>

  <JobCreate
    open={createJobOpen}
    {accounts}
    onclose={() => (createJobOpen = false)}
    oncreated={handleCreated}
    onopenexisting={(id) => { createJobOpen = false; void openJob(id); }}
    onaccounts={() => { createJobOpen = false; workspace = "accounts"; }}
  />
  <AccountImport
    open={importAccountOpen}
    onclose={() => (importAccountOpen = false)}
    onimported={handleImported}
  />
</div>

<style>
  .notice {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin: -8px 0 26px;
  }

  .notice .button {
    flex: 0 0 auto;
  }

  .security-callout {
    max-width: 780px;
    margin: 26px 0 0;
    border-top: 1px solid var(--line);
    padding-top: 16px;
    color: var(--muted);
    font-size: 12px;
  }

  @media (max-width: 680px) {
    .notice {
      align-items: flex-start;
    }
  }
</style>
