import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * No route may declare the Edge Runtime — app/edge-runtime.test.ts
 *
 * THIS FILE USED TO ASSERT THE EXACT OPPOSITE, and the reversal is the whole story.
 *
 * Under `@cloudflare/next-on-pages` every server-rendered route HAD to export
 * `runtime = 'edge'`, and a route that forgot broke the Pages build:
 *
 *     ERROR: Failed to produce a Cloudflare Pages build from the project.
 *         The following routes were not configured to run with the Edge Runtime:
 *           - /admin/offers
 *
 * That adapter is gone. It pinned `next` at `<=15.5.2` while every fix for the advisories
 * against 15.x lands at `>=15.5.21`, so no patched version of Next could satisfy it.
 * `@opennextjs/cloudflare` replaced it, runs Next on the NODE.JS runtime inside a Worker, and
 * does NOT support edge-runtime routes — so the 34 exports were removed and the requirement
 * inverted rather than deleted.
 *
 * WHY THE CHECK SURVIVES THE REVERSAL INSTEAD OF BEING DELETED. The failure mode is identical
 * and it is the expensive kind: `next build` passes either way. Type-checking passes, lint
 * passes, every test passes, the commit merges — and the frontend silently stops deploying,
 * so the symptom is "none of my changes are live" rather than "the build failed". The only
 * thing that changed is which direction is wrong. A copied-in page from an old branch, or a
 * habit from the previous setup, puts the export back; this fails first.
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
describe('no route declares the edge runtime', () => {
  it('finds the routes at all', () => {
    // Guards the guard: a moved directory would make every assertion below pass vacuously,
    // which is the same silent failure this whole file exists to prevent.
    expect(ROUTES.length).toBeGreaterThan(20);
  });

  it.each(ROUTES.map((f) => relative(APP, f)))('%s runs on the Node.js runtime', (rel) => {
    const src = readFileSync(join(APP, rel), 'utf8');
    expect(
      src,
      `${rel} exports \`runtime = 'edge'\`. @opennextjs/cloudflare runs Next on the Node.js ` +
        'runtime and does not support edge routes, so next build will pass and the Worker ' +
        'build will fail — the frontend stops deploying while every later commit looks shipped.',
    ).not.toMatch(/export const runtime = ['"]edge['"]/);
  });

  it('no adapter that requires the edge runtime is installed', () => {
    /*
     * The root cause, asserted directly. Reinstalling @cloudflare/next-on-pages would make
     * every assertion above wrong again — and it caps `next` below the patched versions, which
     * is why it was removed in the first place.
     */
    const pkg = JSON.parse(readFileSync(join(process.cwd(), 'package.json'), 'utf8'));
    const deps = { ...pkg.dependencies, ...pkg.devDependencies };
    expect(deps['@cloudflare/next-on-pages']).toBeUndefined();
    expect(deps['@opennextjs/cloudflare']).toBeDefined();
  });
});
