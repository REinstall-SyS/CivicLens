import { ArrowRight, ArrowUpRight, CalendarDays, FileSearch, MapPin, ShieldCheck } from 'lucide-react';
import Link from 'next/link';
import { Badge, Empty, EvidenceLink, ItemCard, MeetingRow, SearchBar, SectionHeading } from '@/components/ui';
import { fetchApi, Home, localDate } from '@/lib/api';

export default async function Page() {
  let data: Home | null = null;
  try {
    data = await fetchApi<Home>('home');
  } catch {
    // Keep the entry points available while the API is starting.
  }
  const featured = data?.decisions[0];
  return <>
    <section className="hero">
      <div className="container hero-inner">
        <div className="hero-copy">
          <span className="locality"><MapPin size={15} aria-hidden="true" /> Hattiesburg, Mississippi</span>
          <h1>Follow the decisions<br className="wide-break" /> shaping <em>Hattiesburg.</em></h1>
          <p>Find local proposals, follow the issues you care about, and see what the city decided in the original public record.</p>
          <SearchBar dark />
          <div className="quick-search"><span>Explore</span>
            <Link href="/explore?topic=Transportation">Transportation <ArrowUpRight size={13} /></Link>
            <Link href="/explore?topic=Land+use">Land use <ArrowUpRight size={13} /></Link>
            <Link href="/explore?topic=Budget+%26+finance">City spending <ArrowUpRight size={13} /></Link>
          </div>
        </div>
        <aside className="hero-record" aria-label="From the public record">
          <div className="hero-record-heading"><FileSearch size={17} aria-hidden="true" /> From the public record</div>
          {featured ? <>
            <div className="hero-record-meta"><span>{featured.topic}</span><Badge status={featured.status} /></div>
            <h2><Link href={`/items/${featured.id}`}>{featured.title}</Link></h2>
            <p>{featured.official_id} · {localDate(featured.meeting.starts_at)}</p>
            {featured.source && <EvidenceLink source={featured.source} />}
            <Link href={`/items/${featured.id}`} className="hero-record-next">View decision timeline <ArrowRight size={16} /></Link>
          </> : <>
            <h2>Every decision starts with a public record.</h2>
            <p>{data ? 'Verified decisions will appear here as official minutes are processed.' : 'The records service is temporarily unavailable.'}</p>
            <Link href="/meetings" className="hero-record-next">Browse meetings <ArrowRight size={16} /></Link>
          </>}
        </aside>
      </div>
    </section>
    <div className="coverage"><div className="container coverage-inner">
      <span><ShieldCheck size={17} aria-hidden="true" /> Cited to official records</span>
      <span><CalendarDays size={16} aria-hidden="true" />
        {data?.latest_record ? `Latest meeting with records · ${localDate(data.latest_record)}` : 'Hattiesburg public meeting archive'}
      </span>
      {data && !data.llm_configured && <span className="coverage-model">Advanced extraction unavailable</span>}
    </div></div>
    <div className="container home-content">
      {!data && <p className="error-banner" role="alert">The records service is unavailable. Reload to try again.</p>}
      <div className="home-columns">
        <section><SectionHeading title="Verified decisions" href="/explore?kind=decision" label="All decisions">
          Recorded outcomes with evidence from official minutes.
        </SectionHeading>
        <div className="card-grid">
          {data?.decisions.length ? data.decisions.slice(0, 4).map(item => <ItemCard key={item.id} item={item} />) :
            <Empty>No verified decisions available.</Empty>}
        </div></section>
        <section className="meeting-aside"><SectionHeading title="Upcoming meetings" />
          {data?.upcoming.length ? data.upcoming.map(meeting => <MeetingRow key={meeting.key} meeting={meeting} />) :
            <Empty>No upcoming meetings have been imported.</Empty>}
          <Link className="text-link" href="/meetings">View meeting archive <ArrowRight size={16} /></Link>
        </section>
      </div>
      <section className="proposals"><SectionHeading title="Recent proposals" href="/explore?kind=proposal" label="All proposals">
        Items on official records awaiting a verified outcome.
      </SectionHeading>
      <div className="card-grid proposal-grid">
        {data?.proposals.length ? data.proposals.map(item => <ItemCard key={item.id} item={item} />) :
          <Empty>No proposals awaiting verification.</Empty>}
      </div></section>
    </div>
  </>;
}
