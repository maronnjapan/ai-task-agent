<script lang="ts">
  // チャット: multiple chats per task, keyset paging, typing indicator, "決定として記録".
  import { onMount, tick } from 'svelte';
  import { api } from '../../api/client';
  import type { ChatOut, MessageOut } from '../../api/types';
  import { onEvent } from '../../stores/events.svelte';
  import { toast } from '../../stores/toasts.svelte';
  import ConfirmDialog from '../ConfirmDialog.svelte';
  import MarkdownView from '../MarkdownView.svelte';
  import Loading from '../Loading.svelte';
  import { AUTHOR_LABELS, formatDateTime, formatRelative, formatTime, label } from '../../lib/format';

  let { taskId }: { taskId: string } = $props();

  const PAGE = 40;

  let chats: ChatOut[] = $state([]);
  let chatsLoading = $state(true);
  let currentId: string | null = $state(null);
  let messages: MessageOut[] = $state([]);
  let hasMore = $state(false);
  let nextBefore: string | null = $state(null);
  let messagesLoading = $state(false);
  let loadingMore = $state(false);
  let typing = $state(false);
  let draft = $state('');
  let sending = $state(false);
  let newChatTitle = $state('');
  let creatingChat = $state(false);
  let scroller: HTMLDivElement | undefined = $state();
  let dialog: ConfirmDialog | undefined = $state();

  const current = $derived(chats.find((c) => c.id === currentId) ?? null);

  async function loadChats(selectFirst = true) {
    chatsLoading = true;
    try {
      chats = await api.tasks.chats(taskId);
      if (selectFirst && !currentId && chats.length > 0) await selectChat(chats[0].id);
      if (currentId && !chats.some((c) => c.id === currentId)) {
        currentId = null;
        messages = [];
      }
    } catch {
      // banner
    } finally {
      chatsLoading = false;
    }
  }

  async function selectChat(id: string) {
    if (currentId === id) return;
    currentId = id;
    messages = [];
    hasMore = false;
    nextBefore = null;
    typing = false;
    messagesLoading = true;
    try {
      const page = await api.chats.messages(id, { limit: PAGE });
      if (currentId !== id) return;
      messages = page.items;
      hasMore = page.has_more;
      nextBefore = page.next_before ?? null;
      await scrollToBottom();
    } catch {
      // banner
    } finally {
      if (currentId === id) messagesLoading = false;
    }
  }

  async function loadMore() {
    if (!currentId || !hasMore || loadingMore || !nextBefore) return;
    loadingMore = true;
    const id = currentId;
    const prevHeight = scroller?.scrollHeight ?? 0;
    try {
      const page = await api.chats.messages(id, { before: nextBefore, limit: PAGE });
      if (currentId !== id) return;
      const known = new Set(messages.map((m) => m.id));
      messages = [...page.items.filter((m) => !known.has(m.id)), ...messages];
      hasMore = page.has_more;
      nextBefore = page.next_before ?? null;
      await tick();
      if (scroller) scroller.scrollTop = scroller.scrollHeight - prevHeight;
    } catch {
      // banner
    } finally {
      loadingMore = false;
    }
  }

  /** Fetch the newest page and merge unseen messages (used after chat.message events). */
  async function refreshLatest() {
    if (!currentId) return;
    const id = currentId;
    try {
      const page = await api.chats.messages(id, { limit: PAGE });
      if (currentId !== id) return;
      const known = new Set(messages.map((m) => m.id));
      const fresh = page.items.filter((m) => !known.has(m.id));
      if (fresh.length > 0) {
        const atBottom = !scroller || scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
        messages = [...messages, ...fresh];
        if (atBottom) await scrollToBottom();
      }
    } catch {
      // banner
    }
  }

  async function scrollToBottom() {
    await tick();
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }

  async function send() {
    const content = draft.trim();
    if (!content || !currentId || sending) return;
    sending = true;
    const id = currentId;
    try {
      const message = await api.chats.send(id, { content });
      if (currentId === id && !messages.some((m) => m.id === message.id)) messages = [...messages, message];
      draft = '';
      await scrollToBottom();
      chats = chats.map((c) => (c.id === id ? { ...c, message_count: (c.message_count ?? 0) + 1, last_message_at: message.created_at } : c));
    } catch {
      // banner
    } finally {
      sending = false;
    }
  }

  function onDraftKey(event: KeyboardEvent) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      void send();
    }
  }

  async function createChat() {
    if (creatingChat) return;
    creatingChat = true;
    try {
      const chat = await api.tasks.createChat(taskId, newChatTitle.trim() || null);
      newChatTitle = '';
      chats = [...chats, chat];
      await selectChat(chat.id);
    } catch {
      // banner
    } finally {
      creatingChat = false;
    }
  }

  async function deleteChat(chat: ChatOut) {
    const ok = await dialog?.confirm({ title: `チャット「${chat.title}」を削除しますか？`, message: 'メッセージ履歴も削除されます。', confirmLabel: '削除', danger: true });
    if (!ok) return;
    try {
      await api.chats.remove(chat.id);
      chats = chats.filter((c) => c.id !== chat.id);
      if (currentId === chat.id) {
        currentId = null;
        messages = [];
        if (chats.length > 0) await selectChat(chats[0].id);
      }
    } catch {
      // banner
    }
  }

  async function recordDecision(message: MessageOut) {
    const ok = await dialog?.confirm({ title: 'このメッセージを決定事項として記録しますか？', message: message.content.slice(0, 300), confirmLabel: '記録する' });
    if (!ok) return;
    try {
      await api.tasks.addDecision(taskId, { content: message.content, source_message_id: message.id });
      toast.success('決定事項として記録しました');
    } catch {
      // banner
    }
  }

  onMount(() => {
    void loadChats();
    const offMessage = onEvent('chat.message', (event) => {
      const data = event.data as { chat_id?: string; task_id?: string };
      if (data.task_id === taskId) {
        chats = chats.map((c) => (c.id === data.chat_id ? { ...c, message_count: (c.message_count ?? 0) + 1, last_message_at: event.created_at } : c));
      }
      if (data.chat_id && data.chat_id === currentId) void refreshLatest();
    });
    const offTyping = onEvent('chat.typing', (event) => {
      const data = event.data as { chat_id?: string; typing?: boolean };
      if (data.chat_id === currentId) {
        typing = !!data.typing;
        if (typing) void scrollToBottom();
      }
    });
    const offCreated = onEvent('chat.created', (event) => {
      const data = event.data as { task_id?: string };
      if (data.task_id === taskId) void loadChats(false);
    });
    return () => {
      offMessage();
      offTyping();
      offCreated();
    };
  });
</script>

<ConfirmDialog bind:this={dialog} />

<div class="chat-layout">
  <aside class="chat-list card" aria-label="チャット一覧">
    <form class="row" onsubmit={(e) => { e.preventDefault(); void createChat(); }}>
      <input type="text" placeholder="新しいチャットのタイトル (任意)" aria-label="新しいチャットのタイトル" bind:value={newChatTitle} style="flex:1;min-width:120px" />
      <button type="submit" class="btn btn-primary btn-sm" disabled={creatingChat}>作成</button>
    </form>
    {#if chatsLoading && chats.length === 0}
      <Loading inline />
    {:else if chats.length === 0}
      <div class="empty">チャットはまだありません</div>
    {:else}
      <ul class="list-plain" role="listbox" aria-label="チャット">
        {#each chats as chat (chat.id)}
          <li>
            <button type="button" class="chat-item" class:active={chat.id === currentId} role="option" aria-selected={chat.id === currentId} onclick={() => void selectChat(chat.id)}>
              <span class="chat-title">{chat.title}</span>
              <span class="small faint">{chat.message_count ?? 0} 件 · {chat.last_message_at ? formatRelative(chat.last_message_at) : formatDateTime(chat.created_at)}</span>
            </button>
            <button type="button" class="btn btn-ghost btn-sm text-danger" aria-label="チャット「{chat.title}」を削除" onclick={() => void deleteChat(chat)}>×</button>
          </li>
        {/each}
      </ul>
    {/if}
  </aside>

  <section class="chat-main card" aria-label="メッセージ">
    {#if !current}
      <div class="empty">左の一覧からチャットを選ぶか、新しく作成してください</div>
    {:else}
      <div class="card-title"><h3>{current.title}</h3></div>
      <div class="messages" bind:this={scroller}>
        {#if hasMore}
          <div style="text-align:center;padding:0.25rem">
            <button type="button" class="btn btn-sm" disabled={loadingMore} onclick={() => void loadMore()}>{loadingMore ? '読み込み中…' : '以前のメッセージを読み込む'}</button>
          </div>
        {/if}
        {#if messagesLoading}
          <Loading />
        {:else if messages.length === 0}
          <div class="empty">メッセージはまだありません。AI に質問や相談をしてみましょう。</div>
        {/if}
        {#each messages as m (m.id)}
          <article class="msg msg-{m.author_type}">
            <header class="row small muted">
              <strong>{label(AUTHOR_LABELS, m.author_type)}</strong>
              <time datetime={m.created_at} title={formatDateTime(m.created_at)}>{formatTime(m.created_at)}</time>
              <span class="spacer"></span>
              <button type="button" class="btn btn-ghost btn-sm" onclick={() => void recordDecision(m)}>決定として記録</button>
            </header>
            <div class="bubble">
              {#if m.author_type === 'user'}<div class="prewrap">{m.content}</div>{:else}<MarkdownView source={m.content} />{/if}
            </div>
          </article>
        {/each}
        {#if typing}
          <div class="typing small muted" role="status" aria-live="polite"><span class="dot dot-accent dot-pulse"></span> AI が入力中…</div>
        {/if}
      </div>
      <form class="composer" onsubmit={(e) => { e.preventDefault(); void send(); }}>
        <label class="field" style="flex:1">
          <span class="sr-only">メッセージ</span>
          <textarea rows="2" bind:value={draft} onkeydown={onDraftKey} placeholder="メッセージを入力 (Ctrl+Enter で送信)" disabled={sending}></textarea>
        </label>
        <button type="submit" class="btn btn-primary" disabled={sending || !draft.trim()}>{sending ? '送信中…' : '送信'}</button>
      </form>
    {/if}
  </section>
</div>

<style>
  .chat-layout {
    display: grid;
    grid-template-columns: 260px 1fr;
    gap: 1rem;
    align-items: start;
  }
  .chat-list {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    max-height: 70vh;
    overflow: auto;
  }
  .chat-list li {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.2rem 0;
  }
  .chat-item {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.1rem;
    padding: 0.4rem 0.5rem;
    font: inherit;
    text-align: left;
    color: var(--text);
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .chat-item:hover {
    background: var(--bg-hover);
  }
  .chat-item.active {
    background: var(--accent-soft);
    border-color: var(--accent);
  }
  .chat-title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
  }
  .chat-main {
    display: flex;
    flex-direction: column;
    min-height: 50vh;
  }
  .messages {
    flex: 1;
    overflow: auto;
    max-height: 60vh;
    padding: 0.25rem 0.25rem 0.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  .msg {
    max-width: 92%;
  }
  .msg-user {
    align-self: flex-end;
  }
  .msg-user .bubble {
    background: var(--accent-soft);
  }
  .bubble {
    background: var(--bg-muted);
    border-radius: var(--radius);
    padding: 0.5rem 0.75rem;
    word-break: break-word;
  }
  .msg-system .bubble {
    background: var(--warning-soft);
    font-size: 0.85rem;
  }
  .composer {
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
    margin-top: 0.5rem;
  }
  .typing {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.2rem 0.25rem;
  }
  @media (max-width: 860px) {
    .chat-layout {
      grid-template-columns: 1fr;
    }
    .chat-list {
      max-height: 30vh;
    }
  }
</style>
