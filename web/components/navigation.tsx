'use client';

import { Bookmark, Compass, Landmark } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

const links = [
  { path: '/', title: 'Home' }, { path: '/explore', title: 'Explore', icon: Compass },
  { path: '/meetings', title: 'Meetings' }, { path: '/watchlists', title: 'Watchlists', icon: Bookmark },
];

export function Navigation() {
  const pathname = usePathname();
  return <header className="site-header"><div className="container header-inner">
    <Link href="/" className="brand" aria-label="CivicLens home">
      <span className="brand-symbol"><Landmark size={21} strokeWidth={1.8} aria-hidden="true" /></span>
      <span>CivicLens</span>
    </Link>
    <nav aria-label="Main navigation">
      {links.map(({ path, title, icon: Icon }) => {
        const current = path === '/' ? pathname === '/' : pathname.startsWith(path);
        return <Link key={path} href={path} aria-current={current ? 'page' : undefined}>
          {Icon && <Icon size={15} aria-hidden="true" />}{title}
        </Link>;
      })}
    </nav>
  </div></header>;
}
