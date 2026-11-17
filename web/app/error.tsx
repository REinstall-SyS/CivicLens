'use client';

import { Button } from '@/components/ui';

export default function ErrorPage({ reset }: { reset: () => void }) {
  return <div className="container content-page narrow">
    <header className="page-heading"><h1>Records unavailable</h1>
      <p>CivicLens could not load this page from the records service.</p></header>
    <Button onClick={reset}>Try again</Button>
  </div>;
}
