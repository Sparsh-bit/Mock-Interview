import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Every non-static route must opt into the Edge Runtime — app/edge-runtime.test.ts
 *
 * WHY THIS EXISTS. Adding `app/(dashboard)/admin/offers/page.tsx` without
 * `export const runtime = 'edge'` broke the Cloudflare Pages build:
 *
 *     ERROR: Failed to produce a Cloudflare Pages build from the project.
 *         The following routes were not configured to run with the Edge Runtime:
 *           - /admin/offers
 *
 * THE PART THAT MADE IT EXPENSIVE: `next build` passes without it. Type-checking passes,
 * lint passes, every test passes, the commit merges — and the frontend silently stops
 * deploying. Every fix pushed afterwards looked shipped and was not, so the symptom was
 * "none of your changes are live" rather than "the build failed", and it took looking at
 * the Pages log to find out why.
 *
 * @cloudflare/next-on-pages requires this on anything server-rendered. Layouts and purely
 * static pages are exempt, which is why the check is scoped to `page.tsx` and `route.ts`
 * rather than every file.
 */

const APP = join(process.cwd(), 'src/app');

function routeFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...routeFiles(full));
    } else if (entry === 'page.tsx' || entry === 'route.ts') {
      out.push(full);
    }
  }
  return out;
}

const ROUTES = routeFiles(APP);

/**
 * Routes that legitimately do not need it.
 *
 * `app/page.tsx` is the landing page and is fully static — it is prerendered, so there is no
 * runtime to configure. Anything added here needs a reason next to it, because the default
 * being wrong is a broken deploy rather than a broken page.
 */
const STATIC_ROUTES = new Set(['page.tsx']);

describe('Cloudflare Pages edge runtime', () => {
  it('finds the routes at all', () => {
    // Guards the guard: a moved directory would make every assertion below pass vacuously,
    // which is the same silent failure this whole file exists to prevent.
    expect(ROUTES.length).toBeGreaterThan(20);
  });

  it.each(ROUTES.map((f) => relative(APP, f)))(
    '%s exports the edge runtime',
    (rel) => {
      if (STATIC_ROUTES.has(rel)) return;
      const src = readFileSync(join(APP, rel), 'utf8');
      expect(
        src,
        `${rel} is missing \`export const runtime = 'edge'\`. next build will pass and the ` +
          'Cloudflare Pages build will fail, so the frontend stops deploying while every ' +
          'later commit looks shipped.',
      ).toMatch(/export const runtime = 'edge'/);
    },
  );
});
