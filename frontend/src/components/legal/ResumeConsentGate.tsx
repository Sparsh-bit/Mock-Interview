'use client';

import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { DisclosureBody } from '@/components/legal/DisclosureBody';
import { getBrowserApiClient } from '@/lib/api';
import type { Disclosure } from '@/lib/legal/disclosure';

/**
 * What a candidate is shown before their first resume upload.
 *
 * A RESUME IS THE MOST SENSITIVE THING THIS PRODUCT TOUCHES — education, employers, often a
 * phone number and a home address — and the analysis that follows sends its full text to a
 * model provider outside India. DPDP §5 wants that said before it happens rather than after,
 * and §16 wants the destination named. So this is a blocking step on the first upload, not a
 * footnote.
 *
 * IT SHOWS THE SAME DISCLOSURE AS /privacy, from the same component and the same endpoint.
 * Two hand-written copies of "who gets your data" would disagree within a month, and the one
 * shown at the moment of upload is the one that matters most.
 *
 * ONLY THE FIRST TIME. Once consent is recorded the gate does not reappear, because a prompt
 * on every upload is a prompt people click through without reading — which is worse for
 * informed consent than asking once and meaning it. Withdrawal in Settings brings it back.
 *
 * THIS IS AN AFFORDANCE, NOT THE ENFORCEMENT. The endpoint checks consent itself and answers
 * 428 without it; this component exists so a candidate meets an explanation instead of an
 * error. Deleting it would be a worse product, not a security hole.
 */
export function ResumeConsentGate({
  onGranted,
  onCancel,
}: {
  onGranted: () => void;
  onCancel: () => void;
}) {
  const [disclosure, setDisclosure] = useState<Disclosure | null>(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getBrowserApiClient()
      .get<Disclosure>('/api/v1/legal/disclosure')
      .then((r) => setDisclosure(r.data))
      .catch(() => setDisclosure(null));
  }, []);

  const agree = async () => {
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
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        Your resume is read and analysed to personalise your interview. Here is exactly who
        sees it and where that happens.
      </p>

      <div className="max-h-80 overflow-y-auto">
        <DisclosureBody disclosure={disclosure} />
      </div>

      {failed && (
        <p role="alert" className="mt-4 text-sm text-accent-rose-ink">
          We could not record your choice, so nothing has been uploaded. Please try again.
        </p>
      )}

      <div className="mt-6 flex flex-wrap gap-3">
        <Button onClick={agree} loading={saving} disabled={!disclosure}>
          I understand — continue
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Not now
        </Button>
      </div>
    </div>
  );
}
