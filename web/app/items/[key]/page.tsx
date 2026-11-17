import { ArrowLeft, ArrowUpRight, CalendarDays, FileText, MapPin } from 'lucide-react';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { FollowItem } from '@/components/follow-item';
import { Badge, EvidenceLink, SectionHeading } from '@/components/ui';
import { ApiError, Evidence, fetchApi, History, Item, localDate, localTime } from '@/lib/api';

function EvidenceBlock({ record }: { record: Evidence }) {
  return <blockquote className="evidence-block">
    <div><EvidenceLink source={record} />
      <a href={`/api/civic/documents/${record.document_id}/pdf#page=${record.page}`} target="_blank" rel="noreferrer">
        Archived page <ArrowUpRight size={13} />
      </a></div>
    <p>{record.quote.replace(/\s+/g, ' ')}</p>
    {record.method === 'ocr' && <small>Text recovered with OCR</small>}
  </blockquote>;
}

export default async function Page({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  let item: Item & { timeline: History[] };
  try {
    item = await fetchApi<Item & { timeline: History[] }>(`items/${encodeURIComponent(key)}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  return <div className="container content-page">
    <Link className="back-link" href="/explore"><ArrowLeft size={16} /> Explore records</Link>
    <header className="page-heading item-heading">
      <div className="item-meta"><span>{item.topic} · {item.official_id}</span><Badge status={item.status} /></div>
      <h1>{item.title}</h1>
      <div className="detail-meta"><span><CalendarDays size={17} /> {localDate(item.meeting.starts_at)} · {localTime(item.meeting.starts_at)}</span>
        {item.meeting.location && <span><MapPin size={17} /> {item.meeting.location}</span>}</div>
      <FollowItem item={item.id} officialId={item.official_id} />
    </header>
    <div className="home-columns timeline-columns">
      <section>
        <SectionHeading title="Decision timeline">{item.verified ? 'The original proposal and the recorded action.' :
          'Outcome not yet verified. The records below show what CivicLens has been able to establish.'}</SectionHeading>
        <ol className="timeline">
          {item.timeline.map(event => <li key={event.id}>
            <div className="timeline-card"><div className="item-meta">
              <span>{event.kind} · Revision {event.revision}</span>
              <Badge status={event.status} />
            </div><h3>{event.title}</h3>
              <p className="record-id">{localDate(event.meeting.starts_at)} · Item {event.number}
                {!event.current && ' · Superseded or withdrawn observation'}</p>
              {event.details.motion && <p className="motion"><strong>Motion</strong> {event.details.motion}</p>}
              {event.details.vote && <p className="vote">Recorded vote · {event.details.vote.yeas} yeas, {event.details.vote.nays} nays
                {event.details.yeas_as_recorded && <small>Yeas as recorded · {event.details.yeas_as_recorded}</small>}</p>}
              {event.evidence.map(record => <EvidenceBlock key={record.segment_id} record={record} />)}
            </div>
          </li>)}
        </ol>
      </section>
      <aside><SectionHeading title="Record details" />
        <div className="side-card"><dl>
          <dt>Official item ID</dt><dd>{item.official_id}</dd>
          <dt>Government body</dt><dd>{item.meeting.body}</dd>
          {Boolean(item.details.wards?.length) && <><dt>Ward as recorded</dt><dd>{item.details.wards?.join(', ')}</dd></>}
          {Boolean(item.details.locations?.length) && <><dt>Addresses mentioned</dt><dd>{item.details.locations?.join(' · ')}</dd></>}
          {Boolean(item.details.amounts?.length) && <><dt>Amounts in item wording</dt><dd>{item.details.amounts?.map(amount =>
            new Intl.NumberFormat('en-US', { style: 'currency', currency: amount.currency }).format(Number(amount.value))).join(' · ')}</dd></>}
          {Boolean(item.details.references?.length) && <><dt>Ordinance or resolution references</dt><dd>{item.details.references?.join(' · ')}</dd></>}
        </dl><Link className="text-link" href={`/meetings/${item.meeting.key}`}><FileText size={16} /> Meeting details</Link></div>
      </aside>
    </div>
  </div>;
}
