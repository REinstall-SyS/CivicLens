import Link from 'next/link';
import { Filter, Search } from 'lucide-react';
import { Button, Empty, ItemCard } from '@/components/ui';
import { fetchApi, Item, statusLabels, topics } from '@/lib/api';

export const metadata = { title: 'Explore' };

const fields = ['q', 'topic', 'body', 'state', 'kind', 'ward', 'location', 'start', 'end'] as const;

export default async function Explore({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const input = await searchParams;
  const filters = new URLSearchParams();
  for (const field of fields) {
    const value = input[field];
    if (typeof value === 'string' && value.trim()) filters.set(field, value.trim());
  }
  let items: Item[] = [];
  let error = false;
  try {
    ({ items } = await fetchApi<{ items: Item[] }>(`items?${filters}`));
  } catch {
    error = true;
  }
  return <div className="container content-page">
    <header className="page-heading"><span className="eyebrow">Public records</span><h1>Explore Hattiesburg</h1>
      <p>Search proposals and recorded decisions. Open any item to see the evidence and its history.</p></header>
    <div className="explore-layout">
      <form className="filter-panel" action="/explore">
        <h2><Filter size={19} aria-hidden="true" /> Search and filter</h2>
        <label>Keywords<input name="q" defaultValue={filters.get('q') ?? ''} placeholder="Project, location, item ID" maxLength={180} /></label>
        <label>Topic<select name="topic" defaultValue={filters.get('topic') ?? ''}><option value="">All topics</option>
          {topics.map(topic => <option key={topic}>{topic}</option>)}</select></label>
        <label>Record type<select name="kind" defaultValue={filters.get('kind') ?? ''}><option value="">All records</option>
          <option value="proposal">Proposals</option><option value="decision">Verified decisions</option></select></label>
        <label>Status<select name="state" defaultValue={filters.get('state') ?? ''}><option value="">Any status</option>
          {Object.entries(statusLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
        <label>Body<input name="body" defaultValue={filters.get('body') ?? ''} placeholder="e.g. City Council" maxLength={140} /></label>
        <label>Ward as recorded<select name="ward" defaultValue={filters.get('ward') ?? ''}><option value="">Any ward</option>
          {[1, 2, 3, 4, 5].map(ward => <option key={ward} value={ward}>Ward {ward}</option>)}</select></label>
        <label>Address mentioned<input name="location" defaultValue={filters.get('location') ?? ''} placeholder="e.g. Lurty Avenue" maxLength={180} /></label>
        <label>Meeting on or after<input type="date" name="start" defaultValue={filters.get('start') ?? ''} /></label>
        <label>Meeting on or before<input type="date" name="end" defaultValue={filters.get('end') ?? ''} /></label>
        <Button type="submit"><Search size={16} /> Apply filters</Button>
        {filters.size > 0 && <Link href="/explore" className="text-link">Clear filters</Link>}
      </form>
      <section className="results" aria-label="Search results">
        <div className="result-heading"><h2>{filters.get('q') ? <>Results for “{filters.get('q')}”</> : 'Public record items'}</h2>
          {!error && <span>{items.length} {items.length === 1 ? 'item' : 'items'} shown</span>}</div>
        {error ? <div className="error-banner" role="alert">Search could not be completed. Check the date range or try again.</div> :
          items.length ? <div className="result-list">{items.map(item => <ItemCard key={item.id} item={item} />)}</div> :
          <Empty>No records match these filters.</Empty>}
      </section>
    </div>
  </div>;
}
