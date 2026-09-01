import type { MetadataRoute } from 'next';

import { siteUrl } from '@/lib/seo/site-url';

/**
 * sitemap.xml — app/sitemap.ts
 *
 * PUBLIC PAGES ONLY, listed explicitly rather than discovered. A generated crawl of the route
 * tree would sweep in the twenty-odd authenticated pages, and a sitemap that advertises paths
 * which answer with a redirect is worse than no sitemap: it spends crawl budget and teaches the
 * crawler that this site's URLs are unreliable.
 *
 * `priority` and `changeFrequency` are hints and search engines are free to ignore them. They
 * are set anyway because they cost nothing and they encode something true: the landing and
 * pricing pages change with the product, while the legal pages change when the law or a
 * processor does — which is rarely, and never on a schedule.
 */
const PAGES: Array<{ path: string; priority: number; changeFrequency: 'weekly' | 'monthly' | 'yearly' }> = [
  { path: '/', priority: 1.0, changeFrequency: 'weekly' },
  { path: '/pricing', priority: 0.9, changeFrequency: 'weekly' },
  { path: '/demo', priority: 0.8, changeFrequency: 'monthly' },
  { path: '/privacy', priority: 0.3, changeFrequency: 'monthly' },
  { path: '/terms', priority: 0.3, changeFrequency: 'monthly' },
  { path: '/refund', priority: 0.3, changeFrequency: 'yearly' },
  { path: '/grievance', priority: 0.3, changeFrequency: 'yearly' },
];

export default function sitemap(): MetadataRoute.Sitemap {
  const base = siteUrl();
  // ONE TIMESTAMP FOR THE WHOLE BUILD. Per-page dates would need a real content date to be
  // honest, and `new Date()` per entry claims every page changed at slightly different times,
  // which is false. A build time is at least true: this is when the deployed copy was made.
  const lastModified = new Date();
  return PAGES.map(({ path, priority, changeFrequency }) => ({
    url: `${base}${path === '/' ? '' : path}` || base,
    lastModified,
    changeFrequency,
    priority,
  }));
}
