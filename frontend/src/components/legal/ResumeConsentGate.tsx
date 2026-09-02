'use client';

import { useEffect, useState } from 'react';

import Link from 'next/link';

import { Button } from '@/components/ui/button';
import ConsentCheckbox from '@/components/legal/ConsentCheckbox';
import { getBrowserApiClient } from '@/lib/api';
import type { Disclosure } from '@/lib/legal/disclosure';

/**
 * What a candidate is shown before their first resume upload.
 *
 * A RESUME IS THE MOST SENSITIVE THING THIS PRODUCT TOUCHES — education, employers, often a
 * phone number and a home address — and the analysis that follows sends its full text to a
 * model provider outside India. DPDP §5 wants that said before it happens rather than after,
 * so this is a blocking step on the first upload, not a footnote.
 *
 * ── LAYERED NOTICE, AND THE TRADE IT MAKES ────────────────────────────────────────────────
 *
 * This used to render the entire processor table inline — every vendor, its country and what
 * it receives — above a single "I understand" button. It now shows a short summary, a REQUIRED
 * tick box, and a Confirm that cannot be pressed until the box is ticked. The full list is one
 * click away on /privacy, rendered from the same endpoint, so there is still exactly one
 * source for it.
 *
 * WHAT THIS COSTS: §16's country-per-processor detail is now one click from the upload screen
 * instead of on it. That is a real reduction and docs/COMPLIANCE.md §16 records it as such
 * rather than continuing to claim the old behaviour.
 *
 * WHAT IT BUYS: a stronger §6 position and, honestly, a notice more people read. "I
 * understand" on a button is a navigation control that happens to carry legal weight; a tick
 * box is an affirmative act, and an unticked one cannot be clicked past. A 300-word table
 * above a button is the thing everybody scrolls straight past — a short sentence with a link
 * is the thing they actually read.
 *
 * NO VENDOR IS NAMED IN THIS FILE. Every string about who receives data comes from
 * /api/v1/legal/disclosure, which services/legal/disclosure.py derives from the running
 * configuration. A second copy here would drift — it did once, and the disclosure named the
 * wrong country for months. `lib/legal/consent.test.ts` fails if a vendor name appears here.
 *
 * ONLY THE FIRST TIME. Once consent is recorded the gate does not reappear: a prompt on every
 * upload is a prompt people click through without reading. Withdrawal in Settings brings it
 * back.
 *
 * THIS IS AN AFFORDANCE, NOT THE ENFORCEMENT. The endpoint checks consent itself and answers
 * 428 without it; this component exists so a candidate meets an explanation instead of an
 * error.
 */
export function ResumeConsentGate({
  onGranted,
  onCancel,
}: {
  onGranted: () => void;
  onCancel: () => void;
}) {
  const [disclosure, setDisclosure] = useState<Disclosure | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  // STILL FETCHED, even though the table is no longer rendered here. It carries
  // `notice_version`, and consent recorded without it cannot be tied to what the person was
  // actually shown — which is the whole point of stamping it.
  useEffect(() => {
    getBrowserApiClient()
      .get<Disclosure>('/api/v1/legal/disclosure')
      .then((r) => setDisclosure(r.data))
      .catch(() => setDisclosure(null));
  }, []);

  const confirm = async () => {
    setSaving(true);
    setFailed(false);
    try {
      await getBrowserApiClient().post('/api/v1/legal/consent', {
        purpose: 'resume_processing',
        granted: true,
        notice_version: disclosure?.notice_version,
      });
      onGranted();
    } catch {
      // NOT swallowed and NOT optimistic. Proceeding as though consent were recorded
      // would send the resume with no evidence anybody agreed — the exact state this
      // gate exists to prevent — and the upload would 428 anyway.
      setFailed(true);
      setSaving(false);
    }
  };

  return (
    <div className="rounded-2xl border border-border/60 p-5">
      <h2 className="text-base font-semibold">Before you upload your resume</h2>

      {/*
        * THE SUMMARY SAYS THE TWO THINGS THAT CHANGE SOMEBODY'S DECISION: that the full text
        * is read by AI services, and that some of them are outside India. Both are facts about
        * the system rather than reassurance about it. Who those services are, and which
        * countries, is on /privacy — named there and only there.
        */}
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        Your resume is read and analysed to personalise your interview. Its full text is sent
        to the AI services that generate your questions and write your report, and some of
        them operate outside India. You can see exactly which, and what each one receives, in
        our Privacy Policy.
      </p>

      <div className="mt-5 rounded-xl border border-border/60 p-4 text-sm">
        <ConsentCheckbox
          id="resume_processing_consent"
          checked={agreed}
          onChange={(e) => setAgreed(e.target.checked)}
        >
          I accept the{' '}
          {/*
            * `stopPropagation` because this link sits inside the checkbox's own <label>:
            * without it, opening the terms also toggles the box, so a candidate who reads
            * them before agreeing has their consent silently un-ticked for doing the right
            * thing.
            *
            * `target="_blank"` rather than a navigation: the candidate is mid-upload with a
            * file held in this component's state, and leaving the page discards it.
            */}
          <Link
            href="/terms"
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="font-medium text-accent-indigo-ink underline underline-offset-2 hover:text-foreground"
          >
            Terms and Conditions
          </Link>{' '}
          and the{' '}
          <Link
            href="/privacy"
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="font-medium text-accent-indigo-ink underline underline-offset-2 hover:text-foreground"
          >
            Privacy Policy
          </Link>
          , and I agree to my resume being processed as described there. They open in a new
          tab, so the file you have chosen is not lost.
        </ConsentCheckbox>
      </div>

      {failed && (
        <p role="alert" className="mt-4 text-sm text-accent-rose-ink">
          We could not record your choice, so nothing has been uploaded. Please try again.
        </p>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        {/*
          * DISABLED ON THE TICK, not only on the fetch. Gating it on `disclosure` alone would
          * leave the box as decoration and the old click-through behaviour intact — which is
          * the failure this control exists to remove.
          */}
        <Button onClick={confirm} loading={saving} disabled={!agreed || !disclosure}>
          Confirm
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Not now
        </Button>
      </div>
    </div>
  );
}
