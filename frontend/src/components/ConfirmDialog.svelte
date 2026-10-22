<script lang="ts">
  // Accessible confirm dialog built on <dialog>. Usage:
  //   let dialog: ConfirmDialog; ... const ok = await dialog.confirm({ title, message });
  import { tick } from 'svelte';

  interface Options {
    title: string;
    message?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
    /** When set, the user must type this text to enable the confirm button. */
    requireText?: string;
  }

  let dialog: HTMLDialogElement | undefined = $state();
  let options: Options = $state({ title: '' });
  let typed = $state('');
  let resolver: ((value: boolean) => void) | null = null;

  const canConfirm = $derived(!options.requireText || typed === options.requireText);

  export async function confirm(opts: Options): Promise<boolean> {
    options = { confirmLabel: 'OK', cancelLabel: 'キャンセル', ...opts };
    typed = '';
    await tick();
    if (!dialog) return false;
    if (!dialog.open) dialog.showModal();
    return new Promise<boolean>((resolve) => {
      resolver = resolve;
    });
  }

  function close(result: boolean) {
    dialog?.close();
    resolver?.(result);
    resolver = null;
  }

  function onCancel(event: Event) {
    event.preventDefault();
    close(false);
  }
</script>

<dialog bind:this={dialog} class="confirm" oncancel={onCancel} aria-labelledby="confirm-title">
  <form method="dialog" onsubmit={(e) => { e.preventDefault(); if (canConfirm) close(true); }}>
    <h3 id="confirm-title">{options.title}</h3>
    {#if options.message}
      <p class="prewrap muted">{options.message}</p>
    {/if}
    {#if options.requireText}
      <label class="field">
        <span>確認のため「{options.requireText}」と入力してください</span>
        <input type="text" bind:value={typed} autocomplete="off" />
      </label>
    {/if}
    <div class="form-actions" style="justify-content:flex-end">
      <button type="button" class="btn" onclick={() => close(false)}>{options.cancelLabel}</button>
      <button type="submit" class="btn {options.danger ? 'btn-danger' : 'btn-primary'}" disabled={!canConfirm}>{options.confirmLabel}</button>
    </div>
  </form>
</dialog>

<style>
  dialog.confirm {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--bg-elevated);
    color: var(--text);
    padding: 1.25rem;
    width: min(92vw, 440px);
    box-shadow: var(--shadow-lg);
  }
  dialog.confirm::backdrop {
    background: rgba(0, 0, 0, 0.45);
  }
</style>
