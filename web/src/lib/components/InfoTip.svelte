<script module lang="ts">
  let nextId = 0;
</script>

<script lang="ts">
  import { onMount } from "svelte";

  let {
    text,
    label = "More information",
    align = "start",
    trigger = "icon",
    triggerText = "",
    chipClass = "",
  } = $props<{
    text: string;
    label?: string;
    align?: "start" | "end";
    trigger?: "icon" | "chip";
    triggerText?: string;
    chipClass?: string;
  }>();

  let open = $state(false);
  let clickOpen = $state(false);
  let root = $state<HTMLSpanElement>();
  const tooltipId = `info-tip-${nextId++}`;

  function toggle(): void {
    clickOpen = !clickOpen;
    open = clickOpen;
  }

  function openOnHover(): void {
    open = true;
  }

  function closeOnHoverLeave(): void {
    if (!clickOpen) open = false;
  }

  function closeOnFocusLeave(event: FocusEvent): void {
    if (!root?.contains(event.relatedTarget as Node | null)) {
      open = false;
      clickOpen = false;
    }
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      open = false;
      clickOpen = false;
      (event.currentTarget as HTMLButtonElement).focus();
    }
  }

  onMount(() => {
    const closeOnOutsidePointer = (event: PointerEvent): void => {
      if (!root?.contains(event.target as Node)) {
        open = false;
        clickOpen = false;
      }
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  });
</script>

<span class:align-end={align === "end"} class="info-tip" bind:this={root} role="group" aria-label={label} onfocusout={closeOnFocusLeave} onpointerenter={openOnHover} onpointerleave={closeOnHoverLeave}>
  {#if trigger === "chip"}
    <button
      class={`info-button info-chip ${chipClass}`}
      type="button"
      aria-label={label}
      aria-expanded={open}
      aria-controls={tooltipId}
      aria-describedby={open ? tooltipId : undefined}
      onclick={toggle}
      onfocus={() => (open = true)}
      onkeydown={onKeydown}
    >
      {triggerText}<span class="info-chip-indicator" aria-hidden="true">(i)</span>
    </button>
  {:else}
    <button
      class="info-button"
      type="button"
      aria-label={label}
      aria-expanded={open}
      aria-controls={tooltipId}
      aria-describedby={open ? tooltipId : undefined}
      onclick={toggle}
      onfocus={() => (open = true)}
      onkeydown={onKeydown}
    >
      <span aria-hidden="true">i</span>
    </button>
  {/if}
  {#if open}
    <span id={tooltipId} class="info-copy" role="tooltip">{text}</span>
  {/if}
</span>

<style>
  .info-tip {
    position: relative;
    display: inline-flex;
    vertical-align: middle;
  }

  .info-button {
    display: inline-grid;
    width: 32px;
    height: 32px;
    place-items: center;
    border: 1px solid var(--line-strong);
    border-radius: 50%;
    background: var(--surface-raised);
    color: var(--muted);
    font-family: "JetBrains Mono Variable", ui-monospace, monospace;
    font-size: 12px;
    font-weight: 700;
    line-height: 1;
  }

  .info-button:hover,
  .info-button[aria-expanded="true"] {
    border-color: var(--accent);
    color: var(--accent-strong);
  }

  .info-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: max-content;
    height: auto;
    gap: 4px;
    border-color: var(--status-border, var(--line));
    border-radius: 999px;
    padding: 3px 8px;
    background: var(--status-background, transparent);
    color: var(--status-color, var(--text));
    font-family: inherit;
    font-size: 11px;
    font-weight: 760;
  }

  .info-chip:hover,
  .info-chip[aria-expanded="true"] {
    border-color: var(--accent);
    color: var(--accent-strong);
  }

  .info-chip-indicator {
    font-family: "JetBrains Mono Variable", ui-monospace, monospace;
    font-size: 0.9em;
    font-weight: 700;
  }

  .info-copy {
    position: absolute;
    z-index: 3;
    top: calc(100% + 7px);
    left: 0;
    width: min(300px, calc(100vw - 32px));
    padding: 10px 12px;
    border: 1px solid var(--line-strong);
    border-radius: 9px;
    background: var(--surface-raised);
    box-shadow: var(--shadow);
    color: var(--text);
    font-size: 12px;
    font-weight: 500;
    line-height: 1.45;
  }

  .align-end .info-copy {
    right: 0;
    left: auto;
  }

  @media (max-width: 680px) {
    .info-button:not(.info-chip) {
      width: 40px;
      height: 40px;
    }
  }
</style>
