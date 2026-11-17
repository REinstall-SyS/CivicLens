import type { Metadata } from 'next';
import Link from 'next/link';
import { Navigation } from '@/components/navigation';
import './globals.css';

export const metadata: Metadata = {
  title: { default: 'CivicLens · Hattiesburg', template: '%s · CivicLens' },
  description: 'Explore Hattiesburg public meetings, proposals, and verified decisions with original source evidence.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <Navigation />
    <main id="main-content">{children}</main>
    <footer><div className="container site-footer">
      <div><strong>CivicLens</strong><p>CivicLens is an independent civic information application. It is not an official government website.</p></div>
      <div className="footer-links">
        <a href="https://www.hattiesburgms.com/council/">City records ↗</a>
        <Link href="/admin">Pipeline health</Link>
      </div>
    </div></footer>
  </body></html>;
}
