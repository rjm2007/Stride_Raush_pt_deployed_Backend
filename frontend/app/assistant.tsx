'use client';

import { DragEvent, FormEvent, KeyboardEvent, ReactNode, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Lead } from './dashboard-data';
import { displayEnum } from './display';
import { dashboardFetch } from './dashboard-client';

// The backend assistant only ever sees leads the staff member has explicitly
// loaded (at most three), so loading a lead is the first thing the UI does.
export const MAX_LEADS = 3;
const LEAD_MIME = 'application/x-rpt-lead';
const CHATS_KEY = 'rpt-assistant-chats';

export type ChatMessage = { role: 'user' | 'assistant'; content: string; error?: boolean };
export type Chat = { id: string; title: string; leadIds: string[]; messages: ChatMessage[]; updated: number };

export function setLeadDragData(event: DragEvent, leadId: string) {
  event.dataTransfer.setData(LEAD_MIME, leadId);
  event.dataTransfer.effectAllowed = 'copyMove';
}
export function leadIdFromDrag(event: DragEvent) {
  return event.dataTransfer.getData(LEAD_MIME) || null;
}
export function isLeadDrag(event: DragEvent) {
  return Array.from(event.dataTransfer.types).includes(LEAD_MIME);
}

// Stamps updated outside any component so render stays pure.
export function touch(chat: Chat, patch: Partial<Chat> = {}): Chat {
  return { ...chat, ...patch, updated: Date.now() };
}

export function newChat(leadIds: string[] = []): Chat {
  return { id: crypto.randomUUID(), title: 'New chat', leadIds, messages: [], updated: Date.now() };
}

export function loadChats(): Chat[] {
  try { return JSON.parse(localStorage.getItem(CHATS_KEY) ?? '[]') as Chat[]; } catch { return []; }
}
export function saveChats(chats: Chat[]) {
  try { localStorage.setItem(CHATS_KEY, JSON.stringify(chats.slice(0, 50))); } catch { /* storage unavailable */ }
}

// Streams one answer from the backend. onDelta receives text as it arrives.
export async function askAssistant(
  messages: ChatMessage[], leadIds: string[], currentPath: string, onDelta: (text: string) => void, signal?: AbortSignal,
): Promise<void> {
  const response = await dashboardFetch('/api/dashboard/assistant/stream', {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: messages.slice(-12).map(({ role, content }) => ({ role, content })), lead_ids: leadIds, current_path: currentPath }),
  });
  if (!response.ok || !response.body) {
    throw new Error(response.status === 401
      ? 'Your session has expired. Sign in again.'
      : response.status === 429
        ? 'The assistant is busy. Please wait a moment and try again.'
        : 'The assistant is temporarily unavailable. Please try again.');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, index); buffer = buffer.slice(index + 2);
      const event = frame.match(/^event: (\w+)/m)?.[1];
      const data = frame.match(/^data: (.*)$/m)?.[1];
      if (event === 'delta' && data) onDelta((JSON.parse(data) as { content: string }).content);
      if (event === 'error') throw new Error('The assistant stopped before finishing. Try again.');
    }
  }
}

// With no lead loaded the backend only answers questions it recognises as being
// about the dashboard itself (keyword gate), so these are phrased to match.
const APP_PROMPTS = ['How does the outreach cadence work on this dashboard?', 'What does the Needs Attention column on the Leads page mean?', 'How do I resend a booking link?'];
const LEAD_PROMPTS = ['Which step is this lead on and when does the cadence end?', 'What did they say on the last answered call?', 'Did the booking link text deliver?'];

// The model answers in light Markdown (bold, lists). Enough of it is rendered
// here for emphasis and structure; anything else stays as typed text.
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\n]+\*)/g;
function inline(text: string, key: number): ReactNode {
  const parts = text.split(INLINE).filter(Boolean);
  return <span key={key}>{parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) return <em key={index}>{part.slice(1, -1)}</em>;
    return part;
  })}</span>;
}

export function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((item, index) => <li key={index}>{inline(item, index)}</li>);
    blocks.push(list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    list = null;
  };
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const number = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || number) {
      const ordered = Boolean(number);
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] }; }
      list.items.push((bullet ?? number)![1]);
      continue;
    }
    flush();
    if (!line.trim()) continue;
    const heading = line.match(/^#{1,3}\s+(.*)$/);
    blocks.push(heading
      ? <strong key={blocks.length} className="rt-heading">{inline(heading[1], 0)}</strong>
      : <p key={blocks.length}>{inline(line, 0)}</p>);
  }
  flush();
  return <>{blocks}</>;
}

function SparkIcon() {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /><path d="M19 17l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" /></svg>;
}
function ControlIcon({ name }: { name: 'plus' | 'external' | 'close' | 'stop' | 'send' }) {
  const path = name === 'plus' ? <path d="M12 5v14M5 12h14" />
    : name === 'external' ? <><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 13v6H5V6h6" /></>
    : name === 'close' ? <path d="m6 6 12 12M18 6 6 18" />
    : name === 'stop' ? <rect x="7" y="7" width="10" height="10" rx="1" />
    : <path d="m5 12 14-7-4 14-3-6zM12 13l7-8" />;
  return <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{path}</svg>;
}

export function AssistantChat({ chat, leads, currentPath, onChange, compact = false, header }: {
  chat: Chat; leads: Lead[]; currentPath: string; onChange: (chat: Chat) => void; compact?: boolean; header?: ReactNode;
}) {
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);
  const byId = new Map(leads.map((lead) => [lead.id, lead]));
  const loaded = chat.leadIds.map((id) => byId.get(id) ?? { id, full_name: 'Lead', display_id: id.slice(0, 8).toUpperCase(), stage: 'cadence' } as Lead);

  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight }); }, [chat.messages]);
  useEffect(() => () => abort.current?.abort(), []);

  function addLead(id: string) {
    if (chat.leadIds.includes(id) || chat.leadIds.length >= MAX_LEADS) return;
    onChange(touch(chat, { leadIds: [...chat.leadIds, id] }));
  }
  function removeLead(id: string) {
    // The backend refuses questions about a lead that is no longer loaded, so
    // the history about it goes too.
    onChange(touch(chat, { leadIds: chat.leadIds.filter((item) => item !== id), messages: [] }));
  }

  async function send(question: string) {
    const content = question.trim();
    if (!content || busy) return;
    setDraft('');
    setBusy(true);
    const history: ChatMessage[] = [...chat.messages, { role: 'user', content }];
    let current: Chat = touch(chat, { messages: [...history, { role: 'assistant', content: '' }], title: chat.messages.length ? chat.title : content.slice(0, 60) });
    onChange(current);
    abort.current = new AbortController();
    try {
      await askAssistant(history, chat.leadIds, currentPath, (text) => {
        const messages = current.messages.slice();
        messages[messages.length - 1] = { role: 'assistant', content: messages[messages.length - 1].content + text };
        current = { ...current, messages };
        onChange(current);
      }, abort.current.signal);
      if (!current.messages[current.messages.length - 1].content) throw new Error('No answer came back. Try again.');
    } catch (error) {
      if ((error as Error).name === 'AbortError') return;
      const messages = current.messages.slice();
      messages[messages.length - 1] = { role: 'assistant', content: (error as Error).message, error: true };
      onChange({ ...current, messages });
    } finally { setBusy(false); }
  }

  function submit(event: FormEvent) { event.preventDefault(); void send(draft); }
  function key(event: KeyboardEvent<HTMLTextAreaElement>) { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(draft); } }
  function drop(event: DragEvent) { event.preventDefault(); setOver(false); const id = leadIdFromDrag(event); if (id) addLead(id); }

  const prompts = chat.leadIds.length ? LEAD_PROMPTS : APP_PROMPTS;
  const full = chat.leadIds.length >= MAX_LEADS;
  return <div className={`assistant-chat ${compact ? 'compact' : ''} ${over ? 'is-over' : ''}`} onDragOver={(event) => { if (isLeadDrag(event)) { event.preventDefault(); setOver(true); } }} onDragLeave={() => setOver(false)} onDrop={drop}>
    {header}
    <div className="assistant-leads" aria-label="Loaded leads">
      {loaded.map((lead) => <span className="assistant-lead" key={lead.id}><Link href={`/leads/${lead.id}`} target={compact ? undefined : '_blank'}>{lead.full_name}</Link><button type="button" aria-label={`Remove ${lead.full_name}`} onClick={() => removeLead(lead.id)}><ControlIcon name="close" /></button></span>)}
      {!full && <span className="assistant-dropzone">{over ? 'Drop to load this lead' : loaded.length ? `Drag another lead here (${loaded.length} of ${MAX_LEADS})` : 'Drag a lead card here to ask about it'}</span>}
    </div>
    <div className="assistant-messages" ref={scroller}>
      {!chat.messages.length && <div className="assistant-empty">
        <p>{chat.leadIds.length ? `Ask anything about ${loaded.map((lead) => lead.full_name).join(', ')}.` : 'No lead loaded, so I can answer questions about how the dashboard works. Drag a lead in to ask about a patient.'}</p>
        <div className="assistant-prompts">{prompts.map((prompt) => <button type="button" key={prompt} onClick={() => void send(prompt)}>{prompt}</button>)}</div>
      </div>}
      {chat.messages.map((message, index) => <div className={`assistant-message ${message.role} ${message.error ? 'error' : ''}`} key={index}>
        {message.content ? (message.role === 'assistant' && !message.error ? <RichText text={message.content} /> : message.content) : (busy && index === chat.messages.length - 1 ? <span className="assistant-typing"><i /><i /><i /></span> : '')}
        {message.role === 'assistant' && message.content && !message.error && chat.leadIds.length > 0 && index === chat.messages.length - 1 && !busy && <div className="assistant-links">{loaded.map((lead) => <Link key={lead.id} href={`/leads/${lead.id}/conversations/calls`} target={compact ? undefined : '_blank'}>Open {lead.full_name.split(' ')[0]}&rsquo;s transcripts →</Link>)}</div>}
      </div>)}
    </div>
    <form className="assistant-composer" onSubmit={submit}>
      <label className="sr-only" htmlFor={`assistant-input-${chat.id}`}>Message the Outreach Assistant</label><textarea id={`assistant-input-${chat.id}`} value={draft} rows={1} maxLength={4000} placeholder={chat.leadIds.length ? 'Ask about this lead…' : 'Ask how the dashboard works, or drag a lead in…'} onChange={(event) => setDraft(event.target.value)} onKeyDown={key} disabled={busy} />
      {busy ? <button type="button" className="assistant-send" aria-label="Stop response" onClick={() => abort.current?.abort()}><ControlIcon name="stop" /></button> : <button type="submit" className="assistant-send" aria-label="Send message" disabled={!draft.trim()}><ControlIcon name="send" /></button>}
    </form>
    <p className="assistant-foot">Read-only. Answers come from this lead&rsquo;s records; nothing is changed or sent.</p>
  </div>;
}

// Floating button + popover. Drag a lead card over the button and it opens.
export function AssistantDock({ leads, currentPath, currentLeadId }: { leads: Lead[]; currentPath: string; currentLeadId?: string }) {
  const [open, setOpen] = useState(false);
  const [armed, setArmed] = useState(false);
  const [chat, setChat] = useState<Chat>(() => newChat());
  useEffect(() => {
    // Body-level listener so the button lights up as soon as a card is picked up.
    const on = (event: globalThis.DragEvent) => { if (event.dataTransfer && Array.from(event.dataTransfer.types).includes(LEAD_MIME)) setArmed(true); };
    const off = () => setArmed(false);
    document.addEventListener('dragstart', on); document.addEventListener('dragend', off); document.addEventListener('drop', off);
    return () => { document.removeEventListener('dragstart', on); document.removeEventListener('dragend', off); document.removeEventListener('drop', off); };
  }, []);
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setOpen((current) => !current); } if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', onKey); return () => document.removeEventListener('keydown', onKey);
  }, []);
  function dropOnButton(event: DragEvent) {
    event.preventDefault(); setArmed(false);
    const id = leadIdFromDrag(event);
    if (id && !chat.leadIds.includes(id) && chat.leadIds.length < MAX_LEADS) setChat((current) => touch(current, { leadIds: [...current.leadIds, id] }));
    setOpen(true);
  }
  function loadCurrent() { if (currentLeadId && !chat.leadIds.includes(currentLeadId) && chat.leadIds.length < MAX_LEADS) setChat((current) => touch(current, { leadIds: [...current.leadIds, currentLeadId] })); }
  function openFullPage() {
    // Hand the popover's chat to the full page so nothing is lost.
    saveChats([{ ...chat, title: chat.messages[0]?.content.slice(0, 60) ?? chat.title }, ...loadChats().filter((item) => item.id !== chat.id)]);
    window.open(`/assistant?chat=${chat.id}`, '_blank', 'noopener');
  }
  return <>
    {open && <div className="assistant-pop" role="dialog" aria-label="Outreach Assistant">
      <AssistantChat chat={chat} leads={leads} currentPath={currentPath} onChange={setChat} compact header={<div className="assistant-head">
        <button type="button" className="assistant-logo" aria-label="Open the assistant in a new tab" title="Open the assistant in a new tab" onClick={openFullPage}><SparkIcon /></button>
        <div><strong>Outreach Assistant</strong><small>Reads live data · read-only</small></div>
        <div className="assistant-head-actions">
          {currentLeadId && !chat.leadIds.includes(currentLeadId) && chat.leadIds.length < MAX_LEADS && <button type="button" onClick={loadCurrent}>Load this lead</button>}
          <button type="button" onClick={() => setChat(newChat())} title="New chat" aria-label="New chat"><ControlIcon name="plus" /></button>
          <button type="button" onClick={openFullPage} title="Open in new tab" aria-label="Open in new tab"><ControlIcon name="external" /></button>
          <button type="button" onClick={() => setOpen(false)} title="Close" aria-label="Close assistant"><ControlIcon name="close" /></button>
        </div>
      </div>} />
    </div>}
    <button type="button" className={`assistant-fab ${open ? 'is-open' : ''} ${armed ? 'is-armed' : ''}`} aria-label="Outreach Assistant (Ctrl+K)" title="Outreach Assistant (Ctrl+K)" onClick={() => setOpen((current) => !current)}
      onDragOver={(event) => { if (isLeadDrag(event)) event.preventDefault(); }} onDrop={dropOnButton}>
      <SparkIcon />{armed && <span className="assistant-fab-hint">Drop lead here</span>}{chat.leadIds.length > 0 && !open && <b>{chat.leadIds.length}</b>}
    </button>
  </>;
}

// Full page: chat history on the left, lead picker, and the same chat body.
export function AssistantPage({ leads, initialChatId }: { leads: Lead[]; initialChatId: string | null }) {
  const [chats, setChats] = useState<Chat[]>([]);
  const [activeId, setActiveId] = useState<string>('');
  const [search, setSearch] = useState('');
  useEffect(() => {
    // localStorage exists only in the browser: read it after hydration.
    const stored = loadChats();
    const first = stored.find((chat) => chat.id === initialChatId) ?? stored[0] ?? newChat();
    setChats(stored.some((chat) => chat.id === first.id) ? stored : [first, ...stored]); // eslint-disable-line react-hooks/set-state-in-effect
    setActiveId(first.id);
  }, [initialChatId]);
  const active = chats.find((chat) => chat.id === activeId);
  function update(next: Chat) { setChats((current) => { const list = [next, ...current.filter((chat) => chat.id !== next.id)]; saveChats(list); return list; }); }
  function create() { const chat = newChat(); setChats((current) => { const list = [chat, ...current]; saveChats(list); return list; }); setActiveId(chat.id); }
  function remove(id: string) { setChats((current) => { const remaining = current.filter((chat) => chat.id !== id); const list = remaining.length ? remaining : [newChat()]; saveChats(list); if (id === activeId) setActiveId(list[0].id); return list; }); }
  const matches = search.trim() ? leads.filter((lead) => lead.full_name.toLowerCase().includes(search.trim().toLowerCase())).slice(0, 8) : [];
  if (!active) return null;
  return <div className="assistant-page">
    <h1 className="sr-only">Outreach Assistant</h1>
    <aside className="assistant-history">
      <button type="button" className="primary icon-label" onClick={create}><ControlIcon name="plus" />New chat</button>
      <div className="assistant-history-list">{chats.map((chat) => <div className={`assistant-history-item ${chat.id === activeId ? 'selected' : ''}`} key={chat.id}><button type="button" aria-pressed={chat.id === activeId} onClick={() => setActiveId(chat.id)}><strong>{chat.title}</strong><small>{chat.leadIds.length ? `${chat.leadIds.length} lead${chat.leadIds.length > 1 ? 's' : ''} · ` : ''}{new Date(chat.updated).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</small></button><button type="button" aria-label={`Delete ${chat.title}`} onClick={() => remove(chat.id)}><ControlIcon name="close" /></button></div>)}</div>
    </aside>
    <section className="assistant-main">
      <div className="assistant-picker">
        <label className="sr-only" htmlFor="assistant-lead-search">Add a lead to this chat</label><input id="assistant-lead-search" value={search} placeholder={active.leadIds.length >= MAX_LEADS ? `Up to ${MAX_LEADS} leads per chat` : 'Add a lead by name…'} disabled={active.leadIds.length >= MAX_LEADS} onChange={(event) => setSearch(event.target.value)} />
        {matches.length > 0 && <div className="assistant-picker-results">{matches.map((lead) => <button type="button" key={lead.id} disabled={active.leadIds.includes(lead.id)} onClick={() => { update(touch(active, { leadIds: [...active.leadIds, lead.id] })); setSearch(''); }}><strong>{lead.full_name}</strong><small>{lead.location ?? ''} · {displayEnum(lead.status)}</small></button>)}</div>}
      </div>
      <AssistantChat chat={active} leads={leads} currentPath="/assistant" onChange={update} header={<div className="assistant-head"><span className="assistant-logo" aria-hidden="true"><SparkIcon /></span><div><strong>Outreach Assistant</strong><small>Reads live data · read-only</small></div></div>} />
    </section>
  </div>;
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  // The theme is stamped on <html> before hydration by the layout script; read it once mounted.
  useEffect(() => { setTheme(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'); }, []); // eslint-disable-line react-hooks/set-state-in-effect
  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('rpt-theme', next); } catch { /* storage unavailable */ }
    setTheme(next);
  }
  return <button type="button" className="theme-toggle" onClick={toggle} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
    {theme === 'dark'
      ? <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
      : <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>}
  </button>;
}
