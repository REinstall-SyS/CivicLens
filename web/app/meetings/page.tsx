import Link from 'next/link';
import { Empty, MeetingRow } from '@/components/ui';
import { fetchApi, Meeting } from '@/lib/api';

export const metadata = { title: 'Meetings' };

export default async function Page({ searchParams }: { searchParams: Promise<{ upcoming?: string }> }) {
  const upcoming = (await searchParams).upcoming === 'true';
  const meetings = await fetchApi<Meeting[]>(`meetings?upcoming=${upcoming}`);
  return <div className="container content-page narrow">
    <header className="page-heading"><span className="eyebrow">Hattiesburg, Mississippi</span><h1>Public meetings</h1>
      <p>Find recorded meeting times, agendas, minutes and associated items.</p></header>
    <div className="meeting-tabs" aria-label="Meeting date filter">
      <Link href="/meetings" aria-current={!upcoming ? 'page' : undefined}>Meeting archive</Link>
      <Link href="/meetings?upcoming=true" aria-current={upcoming ? 'page' : undefined}>Upcoming</Link>
    </div>
    {meetings.length ? <div className="document-list">{meetings.map(meeting => <MeetingRow key={meeting.key} meeting={meeting} />)}</div> :
      <Empty>No meetings available for this view.</Empty>}
  </div>;
}
