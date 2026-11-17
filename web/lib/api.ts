export type Meeting = {
  key: string; title: string; body: string; starts_at: string; location: string | null;
  source_url: string; status: string;
};
export type Evidence = {
  segment_id: string; document_id: string; page: number; start: number; end: number; quote: string;
  method: string; kind: string; source_url: string; revision: number;
};
export type Details = {
  amounts?: { value: string; currency: string }[]; wards?: number[]; locations?: string[];
  references?: string[]; motion?: string; vote?: { yeas: number; nays: number };
  yeas_as_recorded?: string;
};
export type Item = {
  id: string; official_id: string; title: string; topic: string; status: string; verified: boolean;
  source: Evidence | null; meeting: Meeting; details: Details;
};
export type History = {
  id: string; kind: string; number: string; title: string; status: string; authoritative: boolean;
  published_at: string | null; recorded_at: string; meeting: Meeting; revision: number; method: string;
  confidence: number; extraction_version: string; current: boolean; suppressed: boolean;
  details: Details; evidence: Evidence[];
};
export type Home = {
  decisions: Item[]; proposals: Item[]; upcoming: Meeting[]; latest_record: string | null;
  llm_configured: boolean;
};
export type MeetingDetail = Meeting & {
  items: Item[];
  documents: { id: string | null; kind: string; url: string; revision: number | null; authoritative: boolean;
    published_at: string | null; sha256: string | null }[];
};

export const topics = [
  'Budget & finance', 'Government', 'Housing', 'Land use', 'Parks & recreation',
  'Public hearings', 'Public safety', 'Transportation', 'Water & utilities',
];

export const statusLabels: Record<string, string> = {
  approved: 'Approved', rejected: 'Rejected', tabled: 'Tabled', scheduled: 'Scheduled',
  proposed: 'Proposed', discussed: 'Discussed', unknown: 'Outcome not yet verified',
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function fetchApi<T>(path: string): Promise<T> {
  const url = process.env.API_INTERNAL_URL ?? 'http://127.0.0.1:8000';
  const response = await fetch(`${url}/v1/${path}`, { cache: 'no-store' });
  if (!response.ok) throw new ApiError(response.status, 'CivicLens could not retrieve this record.');
  return response.json() as Promise<T>;
}

export async function clientApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/civic/${path}`, {
    cache: 'no-store', ...init,
    headers: { ...(!(init?.body instanceof FormData) && init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = Array.isArray(body.detail) ? body.detail[0]?.msg : body.detail;
    throw new ApiError(response.status, typeof detail === 'string' ? detail : 'The request could not be completed.');
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function localDate(value: string, options: Intl.DateTimeFormatOptions = {}) {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Chicago', month: 'short', day: 'numeric', year: 'numeric', ...options,
  }).format(new Date(value));
}

export function localTime(value: string) {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Chicago', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  }).format(new Date(value));
}
