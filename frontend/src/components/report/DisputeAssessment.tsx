'use client';

import { useState } from 'react';
import { toast } from 'sonner';

import { getBrowserApiClient } from '@/lib/api/browser';

/**
 * "This is wrong" — components/report/DisputeAssessment.tsx
 *
 * THE OTHER HALF OF THE LABEL. Telling somebody a machine judged them and giving them no way
 * to contest it is worse than not telling them: it names the problem and closes the door. So
 * every report that carries the notice also carries this.
 *
 * IT DOES NOT RE-RUN THE MODEL, and that is the point rather than a limitation. Asking the
 * thing that got it wrong to mark its own work is not review. This records that a person
 * should look, and `GET /admin/disputes` is where they look.
 *
 * THE STATE AFTER SUBMITTING IS NOT A TOAST THAT DISAPPEARS. A complaint that vanishes from
 * the screen is indistinguishable from one that was never sent, so the control becomes a
 * standing line saying the dispute is open — and, once somebody has answered it, what they
 * said.
 */
interface Props {
  reportId: string;
  /** An existing dispute, if the page already knows about one. */
  existing?: { status: string; resolution?: string | null } | null;
}

export function DisputeAssessment({ reportId, existing = null }: Props) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [raised, setRaised] = useState(existing);

  if (raised) {
    return (
      <div className="rounded-xl border border-border bg-muted/30 p-4 text-sm" data-testid="dispute-state">
        {raised.status === 'open' ? (
          <p className="leading-relaxed text-muted-foreground">
            <strong className="font-semibold text-foreground">You have asked for a review.</strong>{' '}
            A person will look at this report and come back to you. We will not close it
            without telling you what we decided.
          </p>
        ) : (
          <p className="leading-relaxed text-muted-foreground">
            <strong className="font-semibold text-foreground">
              Reviewed: {raised.status === 'upheld' ? 'your dispute was upheld' : 'the assessment stands'}.
            </strong>{' '}
            {raised.resolution ?? ''}
          </p>
        )}
      </div>
    );
  }

  async function submit() {
    const text = reason.trim();
    if (!text) {
      toast.error('Tell us briefly what is wrong.');
      return;
    }
    setSubmitting(true);
    try {
      await getBrowserApiClient().post(`/api/v1/reports/${reportId}/dispute`, { reason: text });
      setRaised({ status: 'open' });
      toast.success('Sent. A person will review this report.');
    } catch {
      // The candidate is already telling us something is wrong; a raw error string here
      // would be a second failure in the same breath.
      toast.error('That did not send. Please try again, or write to the grievance contact.');
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        data-testid="dispute-open"
      >
        Think this assessment is wrong? Ask for a human review
      </button>
    );
  }

  return (
    <div className="space-y-3 rounded-xl border border-border p-4" data-testid="dispute-form">
      <label htmlFor="dispute-reason" className="block text-sm font-semibold">
        What is wrong with it?
      </label>
      <textarea
        id="dispute-reason"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        maxLength={2000}
        rows={4}
        placeholder="For example: it marked my answer on HashMap wrong, but what I said was correct."
        className="w-full rounded-lg border border-border bg-background p-3 text-sm"
      />
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={submit}
          disabled={submitting}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-60"
        >
          {submitting ? 'Sending…' : 'Send for review'}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-lg px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export default DisputeAssessment;
