// Where the assistant's chat history lives. Chats quote patients (names, call and text details), so they
// must not outlive the staff session on a shared computer:
// - sessionStorage, not localStorage: gone when the tab closes, never shared with other tabs;
// - tagged with the signed-in staff member: another user in the same tab starts with nothing;
// - cleared on sign-out and on an expired session (dashboardFetch's 401).
// The old build kept chats in localStorage under LEGACY_KEY; that copy is deleted on load.

export type ChatMessage = { role: 'user' | 'assistant'; content: string; error?: boolean };
export type Chat = { id: string; title: string; leadIds: string[]; messages: ChatMessage[]; updated: number };

const KEY = 'rpt-assistant-session-chats';
export const LEGACY_KEY = 'rpt-assistant-chats';
const MAX_CHATS = 50;

type Stored = { owner: string; chats: Chat[] };

function session(): Storage | null {
  try { return typeof sessionStorage === 'undefined' ? null : sessionStorage; } catch { return null; }
}

/** Removes the chat history older builds left in localStorage. */
export function purgeLegacyChats(): void {
  try { if (typeof localStorage !== 'undefined') localStorage.removeItem(LEGACY_KEY); } catch { /* storage unavailable */ }
}

/** This staff member's chats in this tab; anything stored for someone else is deleted. */
export function loadChats(owner: string): Chat[] {
  purgeLegacyChats();
  const storage = session();
  if (!storage) return [];
  try {
    const stored = JSON.parse(storage.getItem(KEY) ?? 'null') as Stored | null;
    if (!stored) return [];
    if (stored.owner !== owner || !Array.isArray(stored.chats)) {
      storage.removeItem(KEY);
      return [];
    }
    return stored.chats;
  } catch {
    clearChats();
    return [];
  }
}

export function saveChats(owner: string, chats: Chat[]): void {
  try { session()?.setItem(KEY, JSON.stringify({ owner, chats: chats.slice(0, MAX_CHATS) } satisfies Stored)); } catch { /* storage unavailable */ }
}

/** Sign-out and expired sessions: forget every chat in this tab (and any legacy copy). */
export function clearChats(): void {
  try { session()?.removeItem(KEY); } catch { /* storage unavailable */ }
  purgeLegacyChats();
}
