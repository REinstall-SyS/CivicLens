import { ArrowLeft, ArrowUpRight, CalendarDays, FileText, MapPin } from 'lucide-react';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Button, Empty, ItemCard, SectionHeading } from '@/components/ui';
import { ApiError, fetchApi, localDate, localTime, MeetingDetail } from '@/lib/api';

export default async function Page({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  let meeting: MeetingDetail;
  try {
    meeting = await fetchApi<MeetingDetail>(`meetings/${encodeURIComponent(key.replace(/%3A/ig, ':'))}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  return <div className="container content-page">
    <Link className="back-link" href="/meetings"><ArrowLeft size={16} /> Meetings</Link>
    <header className="page-heading"><span className="eyebrow">{meeting.body}</span><h1>{meeting.title}</h1>
      <div className="detail-meta"><span><CalendarDays size={17} /> {localDate(meeting.starts_at)} · {localTime(meeting.starts_at)}</span>
        {meeting.location && <span><MapPin size={17} /> {meeting.location}</span>}{meeting.status === 'cancelled' && <span>Cancelled</span>}</div>
      <Button asChild className="secondary"><a href={meeting.source_url} target="_blank" rel="noreferrer">Official meeting record <ArrowUpRight size={16} /></a></Button>
    </header>
    <div className="home-columns">
      <section><SectionHeading title="Meeting items" />
        <div className="result-list">{meeting.items.length ? meeting.items.map(item => <ItemCard key={item.id} item={item} />) :
          <Empty>No structured items have been extracted from this meeting.</Empty>}</div></section>
      <aside><SectionHeading title="Official documents" />
        {!meeting.documents.length && <Empty>No PDF records have been imported.</Empty>}
        {meeting.documents.map(document => <article className="document-card" key={document.id ?? document.url}>
          <FileText size={20} aria-hidden="true" /><div><h3 className="capitalize">{document.kind}</h3>
            <p>{document.revision ? 'Revision ' + document.revision : 'Official link'}{document.authoritative ? ' · Official outcome record' : ''}</p>
            {document.published_at && <p>Published {localDate(document.published_at)}</p>}
            <div className="document-links"><a href={document.url} target="_blank" rel="noreferrer">Original <ArrowUpRight size={13} /></a>
              {document.id && <a href={`/api/civic/documents/${document.id}/pdf`} target="_blank" rel="noreferrer">Archived PDF <ArrowUpRight size={13} /></a>}</div>
          </div>
        </article>)}
      </aside>
    </div>
  </div>;
}
