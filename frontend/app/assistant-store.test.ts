import assert from 'node:assert/strict';
import test from 'node:test';
import { clearChats, LEGACY_KEY, loadChats, saveChats, type Chat } from './assistant-store.ts';

class MemoryStorage {
  private items = new Map<string, string>();
  getItem(key: string) { return this.items.get(key) ?? null; }
  setItem(key: string, value: string) { this.items.set(key, String(value)); }
  removeItem(key: string) { this.items.delete(key); }
  get size() { return this.items.size; }
}

const chat = (id: string): Chat => ({ id, title: 'Chat', leadIds: [], messages: [{ role: 'user', content: 'hi' }], updated: 1 });

function withStorage(run: (local: MemoryStorage, session: MemoryStorage) => void) {
  const local = new MemoryStorage();
  const session = new MemoryStorage();
  Object.assign(globalThis, { localStorage: local, sessionStorage: session });
  try { run(local, session); } finally {
    delete (globalThis as { localStorage?: unknown }).localStorage;
    delete (globalThis as { sessionStorage?: unknown }).sessionStorage;
  }
}

test('chats are kept per tab for the signed-in staff member only', () => withStorage((local, session) => {
  saveChats('alice', [chat('a')]);
  assert.equal(local.size, 0, 'nothing goes to localStorage');
  assert.deepEqual(loadChats('alice').map((item) => item.id), ['a']);
  assert.deepEqual(loadChats('bob'), [], 'another user sees nothing');
  assert.equal(session.size, 0, "and alice's chats are deleted");
}));

test('sign-out / expired session clears chats, and the legacy localStorage copy is removed', () => withStorage((local, session) => {
  local.setItem(LEGACY_KEY, JSON.stringify([chat('old')]));
  local.setItem('rpt-theme', 'dark');
  assert.deepEqual(loadChats('alice'), []);
  assert.equal(local.getItem(LEGACY_KEY), null);
  assert.equal(local.getItem('rpt-theme'), 'dark');
  saveChats('alice', [chat('a')]);
  clearChats();
  assert.equal(session.size, 0);
}));

test('broken or missing storage never throws', () => {
  assert.deepEqual(loadChats('alice'), []);
  saveChats('alice', [chat('a')]);
  clearChats();
  withStorage((_local, session) => {
    session.setItem('rpt-assistant-session-chats', '{not json');
    assert.deepEqual(loadChats('alice'), []);
  });
});
