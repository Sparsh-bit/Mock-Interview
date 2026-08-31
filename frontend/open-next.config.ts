/**
 * Cloudflare adapter configuration — open-next.config.ts
 *
 * WHAT REPLACED WHAT. This project deployed through `@cloudflare/next-on-pages`, which
 * Cloudflare has deprecated in favour of `@opennextjs/cloudflare`. The move was forced rather
 * than chosen: next-on-pages pinned `next` at `<=15.5.2`, and every fix for the ~26 advisories
 * against 15.3.x/15.5.x lands at `>=15.5.21`. There was no version of Next that both satisfied
 * the old adapter and was patched, so the adapter had to go.
 *
 * THE ONE BEHAVIOURAL DIFFERENCE THAT MATTERS. next-on-pages ran every server-rendered route
 * on the EDGE runtime and failed the build if a route did not opt in — which is why 36 route
 * files carried `export const runtime = 'edge'` and why `app/edge-runtime.test.ts` existed to
 * enforce it. This adapter runs Next on the NODE.JS runtime inside a Worker, and edge-runtime
 * routes are not supported. So those exports were removed, and that test now asserts the
 * opposite: no route may declare the edge runtime.
 *
 * Empty config is deliberate. Incremental cache, tag cache and queue bindings are all
 * opt-in, and none of them is needed yet: this frontend server-renders against the FastAPI
 * backend and holds no ISR pages. Adding a cache binding before there is anything to cache
 * would be configuration for its own sake — and each one is a Cloudflare resource to create,
 * pay for and reason about.
 */
import { defineCloudflareConfig } from '@opennextjs/cloudflare';

export default defineCloudflareConfig({});
