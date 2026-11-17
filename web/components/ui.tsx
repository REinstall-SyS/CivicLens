import { Slot } from '@radix-ui/react-slot';
import {
  ArrowDownRight, ArrowRight, ArrowUpRight, CalendarDays, FileText, MapPin, Search,
} from 'lucide-react';
import Link from 'next/link';
import { ComponentProps, ReactNode } from 'react';
import { Evidence, Item, localDate, localTime, Meeting, statusLabels } from '@/lib/api';

export function Button({ asChild, className = '', ...props }: ComponentProps<'button'> & { asChild?: boolean }) {
  const Component = asChild ? Slot : 'button';
  return <Component className={`button ${className}`} {...props} />;
}

export function Badge({ status }: { status: string }) {
  return <span className={`badge badge-${status}`}><span aria-hidden="true" />{statusLabels[status] ?? status}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty"><FileText size={20} aria-hidden="true" /><p>{children}</p></div>;
}

export function SearchBar({ initial = '', dark = false }: { initial?: string; dark?: boolean }) {
  return <form action="/explore" className={`search-bar ${dark ? 'search-on-dark' : ''}`}>
    <label className="search-field">
      <Search size={20} aria-hidden="true" />
      <span className="sr-only">Search the public record</span>
      <input name="q" defaultValue={initial} placeholder="Try “road repairs” or “public hearings”" maxLength={180} />
    </label>
    <Button type="submit">Search <ArrowRight size={16} aria-hidden="true" /></Button>
  </form>;
}

export function SectionHeading({ title, href, label, children }: {
  title: string; href?: string; label?: string; children?: ReactNode;
}) {
  return <div className="section-heading">
    <div><h2>{title}</h2>{children && <p>{children}</p>}</div>
    {href && <Link className="text-link" href={href}>{label} <ArrowRight size={16} aria-hidden="true" /></Link>}
  </div>;
}

export function EvidenceLink({ source }: { source: Evidence }) {
  return <a href={source.source_url} className="source-link" target="_blank" rel="noreferrer">
    <FileText size={15} aria-hidden="true" /> {source.kind} · PDF page {source.page} <ArrowUpRight size={14} aria-hidden="true" />
  </a>;
}

export function ItemCard({ item }: { item: Item }) {
  return <article className="item-card">
    <div className="item-meta"><span>{item.topic}</span><Badge status={item.status} /></div>
    <h3><Link href={`/items/${item.id}`}>{item.title} <ArrowDownRight size={16} aria-hidden="true" /></Link></h3>
    <div className="record-id">{item.official_id} <span aria-hidden="true">·</span> {localDate(item.meeting.starts_at)}</div>
    <div className="card-foot">
      {item.source && <EvidenceLink source={item.source} />}
      <Link href={`/items/${item.id}`} className="text-link">Timeline <ArrowRight size={14} aria-hidden="true" /></Link>
    </div>
  </article>;
}

export function MeetingRow({ meeting }: { meeting: Meeting }) {
  return <article className="meeting-row">
    <CalendarDays size={21} aria-hidden="true" />
    <div><h3><Link href={`/meetings/${meeting.key}`}>{meeting.title}</Link></h3>
      <p>{localDate(meeting.starts_at)} · {localTime(meeting.starts_at)}
        {meeting.status === 'cancelled' && ' · Cancelled'}</p>
      {meeting.location && <p className="location"><MapPin size={14} aria-hidden="true" /> {meeting.location}</p>}</div>
    <Link href={`/meetings/${meeting.key}`} aria-label={`Open ${meeting.title}`}><ArrowRight size={18} /></Link>
  </article>;
}
