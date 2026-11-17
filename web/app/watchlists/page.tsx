'use client';

import { Bell, Bookmark, Plus, Trash2 } from 'lucide-react';
import { FormEvent, useEffect, useState } from 'react';
import Link from 'next/link';
import { Button, Empty, ItemCard, SectionHeading } from '@/components/ui';
import { clientApi, Item, localDate, Meeting, topics } from '@/lib/api';

type Watch = { id: string; label: string; enabled: boolean; filters: Record<string, string | number> };
type Alert = { id: string; item_id: string; title: string; watch: string; message: string; type: string;
  source: string; meeting: Meeting; created_at: string };
type Inbox = { watchlists: Watch[]; alerts: Alert[]; upcoming: { item: Item; watchlists: string[] }[] };

export default function Page() {
  const [data, setData] = useState<Inbox>();
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmDeletion, setConfirmDeletion] = useState(false);
  async function reload() { setData(await clientApi<Inbox>('watchlists')); }
  useEffect(() => { void reload().catch(() => setNotice('Could not load your watchlists.')); }, []);
  async function mutate(operation: () => Promise<unknown>, message: string) {
    setBusy(true);
    setNotice('');
    try { await operation(); await reload(); setNotice(message); }
    catch (error) { setNotice(error instanceof Error ? error.message : 'The request failed.'); }
    finally { setBusy(false); }
  }
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = Object.fromEntries([...new FormData(form)].filter(([, value]) => String(value).trim()));
    void mutate(async () => {
      await clientApi('watchlists', { method: 'POST', body: JSON.stringify(fields) });
      form.reset();
    }, 'Watchlist saved.');
  }
  return <div className="container content-page">
    <header className="page-heading"><span className="eyebrow">Your public record</span><h1>Watchlists</h1>
      <p>Follow a local issue and see matching proposals and recorded outcomes in your alert inbox.</p></header>
    <div className="home-columns">
      <section><SectionHeading title="Followed issues" />
        {notice && <p className="notice" role="status">{notice}</p>}
        {data?.watchlists.length ? data.watchlists.map(watch => <article className="watch-row" key={watch.id}>
          <Bookmark size={20} aria-hidden="true" /><div><h3>{watch.label}</h3>
            <p>{Object.entries(watch.filters).filter(([key]) => key !== 'item_id')
              .map(([key, value]) => key === 'q' ? value : `${key} ${value}`).join(' · ') || 'Following a specific item'}</p></div>
          <button className="text-link" disabled={busy} onClick={() => mutate(() => clientApi(`watchlists/${watch.id}`, {
            method: 'PATCH', body: JSON.stringify({ enabled: !watch.enabled }),
          }), watch.enabled ? 'Alerts paused.' : 'Alerts resumed.')}>{watch.enabled ? 'Pause' : 'Resume'}</button>
          <button className="icon-button" disabled={busy} aria-label={`Remove ${watch.label}`} onClick={() =>
            mutate(() => clientApi(`watchlists/${watch.id}`, { method: 'DELETE' }), 'Watchlist removed.')}><Trash2 size={17} /></button>
        </article>) : <Empty>{data ? 'Create your first watchlist or follow an item from its timeline.' : 'Loading watchlists…'}</Empty>}
        <section className="stacked-section"><SectionHeading title="Upcoming matches" />
          {data?.upcoming.length ? data.upcoming.map(({ item, watchlists }) => <div key={item.id}>
            <p className="record-id">Matches {watchlists.join(', ')}</p><ItemCard item={item} /></div>) :
            <Empty>No upcoming matches.</Empty>}
        </section>
        <section className="stacked-section"><SectionHeading title="Alert inbox" />
          {data?.alerts.length ? data.alerts.map(alert => <article className="watch-row" key={alert.id}>
            <Bell size={20} aria-hidden="true" /><div><h3><Link href={`/items/${alert.item_id}`}>{alert.title}</Link></h3>
            <p>{alert.watch} · {alert.message} · Meeting {localDate(alert.meeting.starts_at)}</p>
            <a className="source-link" href={alert.source} target="_blank" rel="noreferrer">View official evidence ↗</a></div>
          </article>) : <Empty>No alerts yet.</Empty>}
        </section>
      </section>
      <aside><form onSubmit={save} className="filter-panel">
        <h2><Plus size={20} aria-hidden="true" /> New watchlist</h2>
        <label>Name<input name="label" required maxLength={140} placeholder="e.g. Neighborhood streets" /></label>
        <label>Keyword or project<input name="q" maxLength={180} placeholder="e.g. bridge repair" /></label>
        <label>Topic<select name="topic"><option value="">Any topic</option>{topics.map(topic => <option key={topic}>{topic}</option>)}</select></label>
        <label>Government body<input name="body" maxLength={140} placeholder="e.g. City Council" /></label>
        <label>Ward<select name="ward"><option value="">Any ward</option>
          {[1, 2, 3, 4, 5].map(ward => <option key={ward} value={ward}>Ward {ward}</option>)}</select></label>
        <label>Address mentioned<input name="location" maxLength={180} placeholder="e.g. 301 Lurty Avenue" /></label>
        <Button disabled={busy}>Save watchlist <Bookmark size={16} /></Button>
        <p className="muted">Watchlists live in this browser. Alerts appear here.</p>
      </form>
      {Boolean(data?.watchlists.length || data?.alerts.length) && <div className="side-card profile">
        <h3>Watchlist data</h3>
        {confirmDeletion ? <><p>This removes your saved watches and alert history.</p>
          <Button className="danger" disabled={busy} onClick={() => mutate(async () => {
            await clientApi('profile', { method: 'DELETE' });
            setConfirmDeletion(false);
          }, 'Watchlist data deleted.')}>Delete data</Button>
          <button className="text-link" onClick={() => setConfirmDeletion(false)}>Cancel</button></> :
          <button className="text-link" onClick={() => setConfirmDeletion(true)}>Delete watchlist data</button>}
      </div>}</aside>
    </div>
  </div>;
}
