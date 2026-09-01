/**
 * The canonical origin of the public site — lib/seo/site-url.ts
 *
 * WHY THIS IS NOT JUST `process.env.NEXT_PUBLIC_APP_URL`. That variable is the DEPLOYMENT URL,
 * and in production it was set to the Cloudflare Pages subdomain (`mock-interview-bqu.pages.dev`)
 * while the site people actually visit is a custom domain. Everything derived from it inherited
 * the wrong host: `metadataBase` in the root layout, so every canonical, OpenGraph and Twitter
 * URL named the subdomain. Two hosts serving identical content with no canonical signal is the
 * textbook duplicate-content split, and the share cards pointed at the wrong site.
 *
 * `NEXT_PUBLIC_SITE_URL` therefore exists separately and wins when set: the canonical identity
 * of the site is a product decision, not a property of wherever the build happens to run.
 * Falling back to the deployment URL keeps preview builds self-consistent, which is what you
 * want there — a preview should link to itself, not to production.
 *
 * The trailing slash is stripped because every caller appends a path.
 */
export function siteUrl(): string {
  const raw =
    process.env.NEXT_PUBLIC_SITE_URL ||
    process.env.NEXT_PUBLIC_APP_URL ||
    'https://interviewos.net.in';
  const trimmed = raw.trim().replace(/\/+$/, '');
  return /^https?:\/\//.test(trimmed) ? trimmed : `https://${trimmed}`;
}
