import { ApiCheck, AssertionBuilder, EmailAlertChannel } from 'checkly/constructs';

import { BRAND } from '../../frontend/src/lib/brand';
import { EVERY_3_MINUTES, EVERY_5_MINUTES, endpoints } from '../checkly.config';

/**
 * The three checks. docs/UPTIME.md explains each one and what to do when it fires.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * THE REASON EVERY CHECK BELOW ASSERTS ON THE BODY:
 *
 *   `GET /api/v1/health` RETURNS HTTP 200 WHEN THE DATABASE IS DOWN.
 *
 * That is deliberate in the API — it reports each dependency in the body and lets the caller
 * decide, so a Redis outage does not make a load balancer pull a working service out of
 * rotation. The consequence for monitoring is that a status-code-only check shows a green
 * tick through a total outage: nobody can sign in, start an interview or read a report, and
 * the dashboard says the service is up.
 * ═══════════════════════════════════════════════════════════════════════════
 */

const email = new EmailAlertChannel('hotseat-email', {
  address: endpoints.alertEmail(),
  // RECOVERY NOTIFICATIONS ON. Without them nobody can answer "how long was it down?", which
  // is the first question asked after every incident.
  sendRecovery: true,
  sendFailure: true,
  sendDegraded: false,
});

/**
 * Is the API process alive?
 *
 * `$.status` USED TO BE THE LITERAL 'ok' ON EVERY RESPONSE, so this check could only ever
 * fail on a timeout or a non-200 — it could not see a database outage at all, which is why
 * the comment above calls it the shallow one. It now reads 'degraded' whenever
 * `dependencies_healthy` is false, so this check fires on a dependency outage too, ~9
 * minutes sooner than the one below (2 failures at 3 minutes, against 3 at 5).
 *
 * The check below is still the one worth having: it is what tells you WHICH dependency
 * broke, and docs/UPTIME.md routes the alert differently for each.
 */
new ApiCheck('api-liveness', {
  name: 'API — process alive',
  frequency: EVERY_3_MINUTES,
  alertChannels: [email],
  degradedResponseTime: 20000,
  // 45s, above the measured ~37s free-tier cold start. A tighter limit would report an
  // outage every time the container had been idle.
  maxResponseTime: 45000,
  request: {
    method: 'GET',
    url: `${endpoints.api()}/api/v1/health`,
    followRedirects: true,
    skipSSL: false,
    assertions: [
      AssertionBuilder.statusCode().equals(200),
      AssertionBuilder.jsonBody('$.status').equals('ok'),
    ],
  },
});

/** Are the dependencies actually healthy? The one that catches what liveness cannot. */
new ApiCheck('api-dependencies', {
  name: 'API — database, Redis and Supabase reachable',
  frequency: EVERY_5_MINUTES,
  alertChannels: [email],
  maxResponseTime: 45000,
  request: {
    method: 'GET',
    url: `${endpoints.api()}/api/v1/health`,
    followRedirects: true,
    skipSSL: false,
    assertions: [
      AssertionBuilder.statusCode().equals(200),
      /*
       * The whole point of this check. `dependencies_healthy` is the AND of all three, so
       * this one assertion catches any of them failing — and the alert body carries the
       * response, which names which.
       *
       * The three are NOT equally serious and docs/UPTIME.md says so: database or Supabase
       * down means nothing works; Redis down means the app keeps serving while rate limiting
       * fails OPEN, the AI spend cap goes per-process, and the plan cache misses at ~$0.065
       * each. That last one is a money problem that announces itself nowhere else.
       */
      AssertionBuilder.jsonBody('$.dependencies_healthy').equals(true),
    ],
  },
});

/** Can a browser load the site at all? */
new ApiCheck('frontend-reachable', {
  name: 'Frontend — the site loads',
  frequency: EVERY_5_MINUTES,
  alertChannels: [email],
  maxResponseTime: 20000,
  request: {
    method: 'GET',
    url: `${endpoints.app()}/`,
    followRedirects: true,
    skipSSL: false,
    assertions: [
      AssertionBuilder.statusCode().equals(200),
      // A SEPARATE CHECK BECAUSE IT IS A SEPARATE PROVIDER. The frontend is Cloudflare Pages
      // and the API is Render; both API checks pass happily while a failed Pages deploy
      // leaves candidates with nothing to load.
      //
      // `BRAND.name` IMPORTED, NOT TYPED OUT. CLAUDE.md: the name lives in exactly one file
      // because it was once written into 33 and has since been renamed twice. A literal here
      // would survive the next rename and turn this check red on a perfectly healthy site —
      // an alert that fires for a reason nobody can find is how a pager gets muted.
      AssertionBuilder.textBody().contains(BRAND.name),
    ],
  },
});
