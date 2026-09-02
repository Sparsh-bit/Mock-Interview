/**
 * Where a login is allowed to send somebody — lib/auth/safe-redirect.ts
 *
 * THE HOLE THIS CLOSES. `/login?redirectTo=…` was read from the query string and handed
 * straight to `router.push`, so `?redirectTo=https://hotseat-login.example` bounced the
 * candidate to somebody else's site the instant their password was accepted.
 *
 * That is the useful shape of an open redirect rather than the theoretical one. The victim
 * arrives on the REAL domain, sees the real certificate, types their real password into the
 * real form — every signal they have been taught to check is genuine — and is then delivered
 * to a copy that asks them to "confirm" it. The link is shareable, survives a paste into
 * WhatsApp, and looks like ours because up to the query string it is ours.
 *
 * A LIST OF ALLOWED PATHS WOULD BE WRONG, and it is worth saying why, because it is the
 * obvious first answer. The middleware sets `redirectTo` to whatever protected path was asked
 * for, and that set grows every time a route is added — an allowlist would silently start
 * dumping people on /dashboard instead of where they were going, which reads as a bug in the
 * router rather than as a security control doing its job. The rule that actually matches the
 * requirement is "somewhere on this site", so that is the rule.
 */

/** Where anybody with no valid destination ends up. */
/*
 * `/dashboard`, and it used to be `/welcome`. The reasoning for the wizard was that it
 * forwards to the dashboard by itself for anyone already set up, so an established account
 * paid only one client-side redirect. That is true only for accounts that FINISHED setup:
 * `/welcome` self-skips on `target_company && resume`, which is "has completed onboarding",
 * not "has been here before". Anybody who skipped it, or who set a target and never uploaded
 * a resume, was handed the four-step wizard again on every single login — and because the
 * skip flag is `localStorage`, skipping on a laptop did nothing for the same person on their
 * phone.
 *
 * A login is somebody who already has an account saying so with their password. It goes to
 * the dashboard. The wizard belongs to the signup flow and is now reached from there
 * explicitly, via `emailRedirectTo` in `hooks/useAuth.ts`.
 *
 * This is also the value `safeRedirect` falls back to when it rejects a hostile
 * `?redirectTo=`, which is a second reason for it to be the plain landing page.
 *
 * An explicit `?redirectTo=` still wins — somebody deep-linked to a report is going to the
 * report.
 */
export const DEFAULT_REDIRECT = '/dashboard';

/**
 * A same-origin path, or `DEFAULT_REDIRECT`.
 *
 * EVERY REJECTED CASE BELOW IS A REAL BYPASS, not a hypothetical one:
 *
 *   `https://evil.com`      the plain absolute URL.
 *   `//evil.com`            PROTOCOL-RELATIVE, and the one most often missed. It has no
 *                           scheme, so a naive "does it start with http" check passes it, and
 *                           the browser resolves it against the current scheme and goes there.
 *   `/\evil.com`            backslash. Chrome and Safari normalise `\` to `/` in URLs, so this
 *                           becomes `//evil.com` inside the browser AFTER any check that
 *                           compared the raw string.
 *   `javascript:…`          not a navigation but a script URL. `router.push` will not execute
 *                           it, but this value has a habit of being reused in an `href`.
 *   `\\evil.com`            the same trick with both slashes flipped.
 *   ` //evil.com`           leading whitespace, which browsers strip before parsing.
 *
 * The check is a positive one — "starts with exactly one slash and nothing that can be
 * re-parsed into an authority" — because a blocklist of the above will always be one browser
 * quirk short.
 */
export function safeRedirect(raw: string | null | undefined): string {
  if (!raw) return DEFAULT_REDIRECT;

  // Browsers strip leading and trailing C0 control characters and spaces before parsing a URL,
  // so a check that runs on the untrimmed string is checking something the browser will never
  // see. Tab, newline and carriage return are stripped from ANYWHERE in a URL, which is why
  // they are removed rather than trimmed.
  const value = raw.replace(/[\t\n\r]/g, '').trim();

  // Must be a path. One leading slash, and the next character must not be another slash or a
  // backslash — either of those makes it an authority once the browser normalises it.
  if (!value.startsWith('/')) return DEFAULT_REDIRECT;
  if (value.length > 1 && (value[1] === '/' || value[1] === '\\')) return DEFAULT_REDIRECT;

  // A scheme cannot appear in a path, and `:` before the first `/` is how one starts. Checked
  // even though the string already begins with `/`, because `/foo:bar` is a legal path while
  // anything containing `://` is a URL somebody is trying to smuggle through.
  if (value.includes('://')) return DEFAULT_REDIRECT;

  return value;
}
