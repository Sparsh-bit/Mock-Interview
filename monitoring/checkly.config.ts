import { defineConfig } from 'checkly';
import { Frequency } from 'checkly/constructs';

/**
 * Uptime monitoring as code. The prose that explains every choice here is docs/UPTIME.md.
 *
 * WHY THE CHECKS LIVE IN THE REPOSITORY RATHER THAN IN A DASHBOARD. A threshold widened in a
 * UI leaves no trace, no diff and no reviewer. The whole point of this project's CI work is
 * that a guard which cannot fail is worse than no guard, and a monitor quietly loosened to
 * stop paging is the same shape.
 *
 * NOT INSTALLED AS A DEPENDENCY. Run it with `npx checkly@latest`. The CLI is needed a few
 * times a year and adding it to package.json would make every CI run download it — see
 * docs/UPTIME.md for the exact commands.
 *
 * EVERY HOSTNAME AND ADDRESS COMES FROM THE ENVIRONMENT. There is deliberately no default: a
 * fallback URL would let `checkly deploy` succeed against the wrong host and create three
 * checks that monitor nothing, which is the failure this file most needs to avoid.
 */

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set. See docs/UPTIME.md — export HOTSEAT_API_URL, HOTSEAT_APP_URL and ` +
        `HOTSEAT_ALERT_EMAIL before running checkly test or deploy.`
    );
  }
  return value.replace(/\/$/, '');
}

export const config = defineConfig({
  projectName: 'Hotseat uptime',
  logicalId: 'hotseat-uptime',
  repoUrl: 'https://github.com/Sparsh-bit/Mock-Interview',

  checks: {
    /*
     * Mumbai first, Singapore second. This product is for Indian campus placement, so a check
     * from Frankfurt would measure a latency no candidate experiences — and would keep
     * reporting "up" from a region whose route to Render is healthy while India's is not.
     */
    locations: ['ap-south-1', 'ap-southeast-1'],
    runtimeId: '2024.02',
    tags: ['hotseat', 'production'],

    /*
     * ONE RETRY BEFORE AN ALERT, and it is the difference between a useful pager and one
     * people mute. Render's free tier sleeps after 15 minutes idle and the next request pays
     * a ~37-second boot; alerting on a single failure would fire most nights on a cold start
     * that recovered by itself.
     */
    retryStrategy: {
      type: 'FIXED',
      baseBackoffSeconds: 30,
      maxRetries: 1,
      maxDurationSeconds: 120,
      sameRegion: false,
    },

    checkMatch: '**/checks/**/*.check.ts',
  },

  cli: {
    runLocation: 'ap-south-1',
  },
});

export const endpoints = {
  api: () => required('HOTSEAT_API_URL'),
  app: () => required('HOTSEAT_APP_URL'),
  alertEmail: () => required('HOTSEAT_ALERT_EMAIL'),
};

export const EVERY_3_MINUTES = Frequency.EVERY_3M;
export const EVERY_5_MINUTES = Frequency.EVERY_5M;

export default config;
