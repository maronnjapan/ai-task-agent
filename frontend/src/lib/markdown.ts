import { marked } from 'marked';
import DOMPurify from 'dompurify';

marked.setOptions({ gfm: true, breaks: false, async: false });

let hooksInstalled = false;

function installHooks(): void {
  if (hooksInstalled || typeof window === 'undefined') return;
  hooksInstalled = true;
  // Open links in a new tab without leaking the opener (local app, external URLs).
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName === 'A') {
      node.setAttribute('target', '_blank');
      node.setAttribute('rel', 'noopener noreferrer');
    }
  });
}

/** Render Markdown to sanitized HTML. Safe to bind with {@html}. */
export function renderMarkdown(source: string): string {
  installHooks();
  const html = marked.parse(source ?? '', { async: false }) as string;
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed', 'form', 'input'],
    ADD_ATTR: ['target']
  });
}

/** Escape text for an {@html} context (used for small inline highlights). */
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch] ?? ch);
}
