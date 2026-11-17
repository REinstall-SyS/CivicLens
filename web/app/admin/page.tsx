'use client';

import { Activity, Check, FileText, KeyRound } from 'lucide-react';
import { FormEvent, useState } from 'react';
import { Button, Empty, EvidenceLink, SectionHeading } from '@/components/ui';
import { clientApi, History, localDate, localTime } from '@/lib/api';

type Run = { key: string; status: string; started_at: string; duration_ms: number | null; detail: string | null };
type Review = { id: string; code: string; resolved: boolean; detail: string; event: History | null; document_url: string | null };
type Pipeline = { runs: Run[]; reviews: Review[]; mean_processing_ms: number | null; item_count: number };
type Evaluation = { evaluation: string; sample_label_count: number; pdfs_processed: number;
  metrics: Record<string, number | null> };
type AuditEntry = { at: string; actor: string; action: string; reason: string };

export default function Page() {
  const [token, setToken] = useState('');
  const [pipeline, setPipeline] = useState<Pipeline>();
  const [evaluation, setEvaluation] = useState<Evaluation>();
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [audit, setAudit] = useState<Record<string, AuditEntry[]>>({});
  const headers = { Authorization: `Bearer ${token}` };
  async function run(operation: () => Promise<void>) {
    setBusy(true);
    setMessage('');
    try { await operation(); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'The request failed.'); }
    finally { setBusy(false); }
  }
  async function reload() {
    const [status, report] = await Promise.all([
      clientApi<Pipeline>('admin/health', { headers }),
      clientApi<Evaluation>('admin/evaluation', { headers }).catch(() => undefined),
    ]);
    setPipeline(status);
    setEvaluation(report);
  }
  function importPdf(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    void run(async () => {
      const result = await clientApi<{ status: string }>('admin/import', { method: 'POST', headers, body: data });
      form.reset();
      await reload();
      setMessage('PDF import ' + result.status + '.');
    });
  }
  function saveReview(event: FormEvent<HTMLFormElement>, id: string) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const values = Object.fromEntries([...fields].filter(([, value]) => String(value).trim()));
    void run(async () => {
      await clientApi(`admin/reviews/${id}`, { method: 'POST', headers, body: JSON.stringify(values) });
      await reload();
      setMessage('Review recorded.');
    });
  }
  return <div className="container content-page">
    <header className="page-heading"><span className="eyebrow">Operations</span><h1>Pipeline health</h1>
      <p>Inspect imports and review claims alongside the source material.</p></header>
    {message && <p className="notice" role="status">{message}</p>}
    {!pipeline ? <form className="filter-panel auth-panel" onSubmit={event => { event.preventDefault(); void run(reload); }}>
      <h2><KeyRound size={19} /> Reviewer sign-in</h2>
      <label>Reviewer token<input type="password" required value={token} onChange={event => setToken(event.target.value)} /></label>
      <Button disabled={busy}>Open dashboard</Button>
    </form> : <>
      <div className="stats">
        <div><Activity size={19} /><strong>{pipeline.runs.length}</strong><span>Recent import attempts</span></div>
        <div><FileText size={19} /><strong>{pipeline.item_count}</strong><span>Published items</span></div>
        <div><Check size={19} /><strong>{pipeline.mean_processing_ms === null ? '—' : `${pipeline.mean_processing_ms} ms`}</strong><span>Mean import latency</span></div>
      </div>
      {evaluation && <section className="side-card evaluation-card">
        <SectionHeading title="Extraction evaluation">{evaluation.evaluation} · {evaluation.sample_label_count} items · {evaluation.pdfs_processed} PDFs</SectionHeading>
        <div className="stats">
          {[['Agenda item recall', 'agenda_item_recall'], ['Disposition precision', 'verified_disposition_precision'],
            ['Disposition recall', 'verified_disposition_recall']].map(([label, key]) => <div key={key}>
            <strong>{evaluation.metrics[key] === null ? '—' : Math.round(100 * Number(evaluation.metrics[key])) + '%'}</strong>
            <span>{label}</span>
          </div>)}
        </div>
      </section>}
      <details className="side-card manual-import">
        <summary><strong>Import a public PDF</strong></summary>
        <form className="review-form" onSubmit={importPdf}>
          <label>Meeting metadata JSON<textarea name="meeting" rows={4} required
            placeholder='{"key":"…","body":"City Council","title":"…","starts_at":"…","source_url":"https://…"}' /></label>
          <label>Official document metadata JSON<textarea name="document" rows={4} required
            placeholder='{"key":"…","kind":"agenda","url":"https://…","authoritative":false}' /></label>
          <label>Original PDF<input type="file" name="pdf_file" accept="application/pdf,.pdf" required /></label>
          <Button disabled={busy}>Import PDF</Button>
        </form>
      </details>
      <div className="home-columns admin-columns">
        <section><SectionHeading title="Review queue" />
          {!pipeline.reviews.length && <Empty>No reviews have been queued.</Empty>}
          {pipeline.reviews.map(review => <details key={review.id} className="admin-review">
            <summary><strong>{review.code.replaceAll('_', ' ')}</strong><span>{review.resolved ? 'Resolved' : 'Open'}</span></summary>
            <p>{review.detail}</p>
            {review.event && <><h3>{review.event.title}</h3>{review.event.evidence.map(source => <blockquote className="evidence-block" key={source.segment_id}>
              <EvidenceLink source={source} /><p>{source.quote.replace(/\s+/g, ' ')}</p>
            </blockquote>)}</>}
            {review.document_url && <a className="source-link" href={review.document_url} target="_blank" rel="noreferrer">Open official PDF ↗</a>}
            {review.resolved ? <div>
              <button className="text-link" onClick={() => run(async () => {
                const entries = await clientApi<AuditEntry[]>(`admin/reviews/${review.id}/audit`, { headers });
                setAudit(current => ({ ...current, [review.id]: entries }));
              })}>Show audit history</button>
              {audit[review.id]?.map(entry => <p key={entry.at}>{localDate(entry.at)} · {entry.actor} · {entry.action} · {entry.reason}</p>)}
            </div> : <form className="review-form" onSubmit={event => saveReview(event, review.id)}>
              <label>Action<select name="action"><option value="acknowledge">Acknowledge</option>
                {review.event && <><option value="reject">Reject observation</option><option value="correct">Correct observation</option></>}</select></label>
              <label>Reason<textarea name="reason" required minLength={8} maxLength={1400} /></label>
              {review.event && <details><summary>Correction fields</summary>
                <label>Corrected title<input name="title" /></label>
                <label>Disposition<select name="outcome"><option value="">Retain</option><option value="unknown">Unknown</option>
                  <option value="approved">Approved</option><option value="rejected">Rejected</option><option value="tabled">Tabled</option><option value="discussed">Discussed</option></select></label>
                <label>PDF page<input name="page" type="number" min={1} /></label>
                <label>Verbatim quote<textarea name="quote" maxLength={1800} /></label>
              </details>}
              <Button disabled={busy}>Record review</Button>
            </form>}
          </details>)}
        </section>
        <aside><SectionHeading title="Recent ingestion" />
          {pipeline.runs.map((item, index) => <article className="run" key={`${item.started_at}-${index}`}>
            <h3>{item.key}</h3><p>{item.status} · {item.duration_ms ?? '—'} ms</p>
            <p>{localDate(item.started_at)} · {localTime(item.started_at)}</p>{item.detail && <p>{item.detail}</p>}
          </article>)}
        </aside>
      </div>
    </>}
  </div>;
}
