import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The consent controls, asserted against the source.
 *
 * WHY SOURCE ASSERTIONS RATHER THAN A RENDERED FORM. Every rule here is about something being
 * ABSENT — no default, no second copy of the vendor list, no upload before the explanation —
 * and rendering the component proves the current behaviour without preventing the change that
 * would break it. A `defaultChecked` added later renders identically until somebody looks.
 *
 * The backend enforces all of this independently (`tests/test_data_protection.py`); these
 * assertions are about the part a candidate actually sees.
 */

const read = (rel: string) => readFileSync(join(process.cwd(), rel), 'utf8');

/**
 * Source with comments stripped — a rule's own explanation must not read as a violation of
 * it. The same trap `src/lib/security-headers.test.ts` records, and a character scanner
 * rather than a regex for the reason that file gives.
 */
function stripComments(source: string): string {
  let out = '';
  let i = 0;
  while (i < source.length) {
    const two = source.slice(i, i + 2);
    if (two === '//') {
      const nl = source.indexOf('\n', i);
      if (nl < 0) break;
      i = nl;
    } else if (two === '/*') {
      const end = source.indexOf('*/', i + 2);
      i = end < 0 ? source.length : end + 2;
    } else if (source[i] === "'" || source[i] === '"' || source[i] === '`') {
      const quote = source[i];
      out += source[i];
      i += 1;
      while (i < source.length && source[i] !== quote) {
        if (source[i] === '\\') {
          out += source.slice(i, i + 2);
          i += 2;
          continue;
        }
        out += source[i];
        i += 1;
      }
      out += quote;
      i += 1;
    } else {
      out += source[i];
      i += 1;
    }
  }
  return out;
}

const REGISTER = stripComments(read('src/app/(auth)/register/page.tsx'));
const CHECKBOX = stripComments(read('src/components/legal/ConsentCheckbox.tsx'));
const GATE = stripComments(read('src/components/legal/ResumeConsentGate.tsx'));
const UPLOAD = stripComments(read('src/components/resume/ResumeUploadCard.tsx'));
const BODY = stripComments(read('src/components/legal/DisclosureBody.tsx'));

describe('signup consent', () => {
  it('asks the three questions separately', () => {
    /*
     * §5 notice, §6 consent and §9 age are three distinct obligations. One "I agree to
     * everything" box makes it impossible to show afterwards which one was actually
     * answered — and the ledger stores them as three rows for exactly that reason.
     */
    for (const field of ['privacy_notice', 'terms', 'age_18_plus']) {
      expect(REGISTER).toContain(field);
    }
  });

  it('never pre-ticks a consent box', () => {
    // A pre-ticked box is the one thing §6 names explicitly as not consent.
    expect(REGISTER).not.toMatch(/defaultChecked/);
    expect(CHECKBOX).not.toMatch(/defaultChecked/);
    expect(CHECKBOX).not.toMatch(/checked=\{true\}/);
    // `literal(true)` rather than `boolean()`: an unticked box must fail validation with a
    // message, not submit a `false` the server has to interpret.
    expect(REGISTER).toMatch(/z\.literal\(true/);
  });

  it('requires all three to submit', () => {
    // Three separate literal(true) schema entries — one per question.
    expect(REGISTER.match(/z\.literal\(true/g)?.length).toBe(3);
  });

  it('records what was agreed to, and against which version of the notice', () => {
    // Consent you cannot evidence is consent you do not have, and a version stamp is what
    // stops a later rewrite silently re-characterising what everybody agreed to.
    expect(REGISTER).toContain('/api/v1/legal/consent/signup');
    expect(REGISTER).toContain('notice_version');
    // Read from the server rather than hardcoded, so a stale tab records what it showed.
    expect(REGISTER).toContain('/api/v1/legal/disclosure');
  });

  it('does not silently swallow a failure to record consent', () => {
    // An account that exists with no evidence of consent is exactly the state §6 is about.
    // The profile call above it is allowed to fail quietly; this one is not.
    const block = REGISTER.split('/api/v1/legal/consent/signup')[1];
    expect(block).toMatch(/toast\.(warning|error)/);
  });

  it('links the notice from the form', () => {
    // Informed means reachable at the moment of deciding, not findable later in a footer.
    expect(REGISTER).toContain('/privacy');
  });
});

describe('the resume gate', () => {
  it('holds the file until the explanation has been shown', () => {
    /*
     * The bytes must not leave the browser before the person has seen who receives them.
     * Reacting only to the server's 428 would mean the resume had already been sent once.
     */
    expect(UPLOAD).toContain('setAwaitingConsent(file)');
    expect(UPLOAD).toMatch(/hasConsented !== true/);
  });

  it('treats a still-loading consent state as not consented', () => {
    // `undefined` must not fall through as permission. Failing towards the explanation
    // costs a moment; failing the other way sends a resume nobody agreed to send.
    expect(UPLOAD).toMatch(/hasConsented !== true/);
    expect(UPLOAD).not.toMatch(/hasConsented === false/);
  });

  it('opens the disclosure on a 428 rather than showing an error', () => {
    // 428 is not a failure — it is "there is something to do first". A red toast is a
    // dead end.
    expect(UPLOAD).toContain('428');
  });

  it('does not record consent optimistically', () => {
    // Proceeding as though it were recorded would send the resume with no evidence
    // anybody agreed, which is the state the gate exists to prevent.
    expect(GATE).toContain('onGranted()');
    const catchBlock = GATE.split('} catch {')[1] ?? '';
    expect(catchBlock).not.toContain('onGranted()');
  });
});

describe('the disclosure is never restated on this side', () => {
  it('names no vendor, country or retention period in the frontend', () => {
    /*
     * THE FAILURE THIS PREVENTS ALREADY HAPPENED ONCE. The backend export carried a
     * hardcoded list of five processors, and it had drifted: it called ZhipuAI the
     * "standby" provider while AI_PROVIDER defaulted to glm — meaning every resume went to
     * China first and the disclosure said otherwise.
     *
     * services/legal/disclosure.py derives the list from the running configuration. A
     * second copy here would drift the same way, so there is not one: every string these
     * components render comes from the prop.
     */
    for (const source of [BODY, GATE]) {
      for (const vendor of ['Anthropic', 'ZhipuAI', 'NVIDIA', 'ElevenLabs', 'Razorpay']) {
        expect(source).not.toContain(vendor);
      }
      for (const country of ['China', 'United States', 'Singapore']) {
        expect(source).not.toContain(country);
      }
      expect(source).not.toMatch(/8 years|180 days/);
    }
  });

  it('surfaces the draft flag instead of hiding it', () => {
    // This text is accurate about the system and has not been through a lawyer. A comment
    // in the source cannot tell the reader that; the banner can.
    expect(BODY).toContain('disclosure.draft');
    expect(BODY).toMatch(/Draft/);
  });

  it('renders a missing grievance contact as a gap, not a blank', () => {
    // An obvious gap beats a plausible fabrication: a made-up name would look like the
    // obligation had been discharged.
    expect(BODY).toContain('grievance.configured');
    expect(BODY).toMatch(/No grievance officer has been appointed/);
  });
});
