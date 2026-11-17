'use client';

import { Bookmark, Check } from 'lucide-react';
import { useState } from 'react';
import { clientApi } from '@/lib/api';
import { Button } from './ui';

export function FollowItem({ item, officialId }: { item: string; officialId: string }) {
  const [status, setStatus] = useState<'idle' | 'saving' | 'followed' | 'error'>('idle');
  async function follow() {
    setStatus('saving');
    try {
      await clientApi('watchlists', { method: 'POST', body: JSON.stringify({ label: `Item ${officialId}`, item_id: item }) });
      setStatus('followed');
    } catch {
      setStatus('error');
    }
  }
  return <div><Button className="secondary" onClick={follow} disabled={status === 'saving' || status === 'followed'}>
    {status === 'followed' ? <Check size={17} /> : <Bookmark size={17} />}{status === 'followed' ? 'Following item' : 'Follow this item'}
  </Button>{status === 'error' && <p role="alert">Could not follow this item. Please retry.</p>}</div>;
}
