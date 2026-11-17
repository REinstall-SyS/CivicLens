import Link from 'next/link';
import { Button } from '@/components/ui';

export default function NotFound() {
  return <div className="container content-page narrow">
    <header className="page-heading"><h1>Record not found</h1><p>This link may refer to a removed or revised item.</p></header>
    <Button asChild><Link href="/explore">Explore records</Link></Button>
  </div>;
}
