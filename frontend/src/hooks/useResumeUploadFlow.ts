'use client';

import { useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { useResumeConsent, useUploadResume } from '@/hooks/useData';

/** Matches the server's own limit; checked here so a 40 MB file is refused before it is sent. */
export const RESUME_MAX_MB = 10;
const ACCEPTED = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
];

/**
 * Uploading a resume, with the consent step that must come first — hooks/useResumeUploadFlow.ts
 *
 * WHY THIS IS A HOOK AND NOT A COPIED BLOCK. The resume can be uploaded from two places: the
 * profile page and the interview setup form. Only one of them knew about consent.
 *
 * The upload endpoint answers **428 Precondition Required** when no consent row exists.
 * ResumeUploadCard checks `useResumeConsent()` first, holds the file back, shows the
 * disclosure, and additionally treats a 428 as "open the gate" rather than as a failure. The
 * interview page called `uploadResume.mutate` with a single generic `onError` and none of
 * that — so for anybody who had not already consented elsewhere, choosing a file there
 * produced:
 *
 *     "Could not read that file. Try a PDF, DOCX or plain text."
 *
 * which is not what happened, gives no way forward, and is unfixable by trying a different
 * file. The resume field is REQUIRED to start an interview, so the effect was that the
 * interview form could not be completed at all until the candidate found the profile page and
 * consented there. Reported exactly that way: "i am only able to upload it from the profile
 * section after confirming".
 *
 * THE BYTES DO NOT LEAVE THE BROWSER BEFORE THE DISCLOSURE IS SHOWN. The 428 handler is a
 * backstop for consent withdrawn in another tab; the local check is what keeps the file from
 * being sent once and refused.
 */
export function useResumeUploadFlow() {
  const upload = useUploadResume();
  const { data: hasConsented } = useResumeConsent();
  const queryClient = useQueryClient();

  //: The file chosen but not yet sent, because consent has not been recorded.
  const [awaitingConsent, setAwaitingConsent] = useState<File | null>(null);

  const send = (file: File, onDone?: () => void) => {
    upload.mutate(file, {
      onSuccess: (result) => {
        const skills = result.parsed_skills?.length ?? 0;
        if (result.parsing_status === 'completed') {
          toast.success(
            `Resume analysed — ${skills} skill${skills === 1 ? '' : 's'} and ` +
              `${result.project_count} project${result.project_count === 1 ? '' : 's'} found.`,
          );
        } else if (result.parsing_status === 'partial') {
          const found =
            skills > 0
              ? `${skills} skill${skills === 1 ? '' : 's'} found`
              : `${result.project_count} project${result.project_count === 1 ? '' : 's'} found`;
          toast.success(`Resume uploaded — ${found}. Part of the analysis could not be built.`);
        } else {
          toast.success('Resume uploaded. Interviews will use it.');
        }
        onDone?.();
      },
      onError: (err: unknown) => {
        // 428 IS NOT A FAILURE. It is the server saying consent has not been recorded, and
        // the right response is to show the disclosure — a red toast is a dead end.
        if ((err as { status?: number })?.status === 428) {
          setAwaitingConsent(file);
          return;
        }
        // The server explains exactly why a file could not be read ("that PDF is a scan —
        // upload the original export"). A generic message throws away the one thing the
        // candidate can act on.
        const message = (err as { message?: string })?.message?.trim();
        toast.error(message || 'That resume could not be uploaded.');
      },
    });
  };

  /** Validate, then either show the disclosure or send. */
  const submit = (file: File, onDone?: () => void) => {
    if (file.size > RESUME_MAX_MB * 1024 * 1024) {
      const mb = (file.size / 1024 / 1024).toFixed(1);
      toast.error(`That file is ${mb} MB. The limit is ${RESUME_MAX_MB} MB.`);
      return;
    }
    if (!ACCEPTED.includes(file.type) && !/\.(pdf|docx)$/i.test(file.name)) {
      toast.error('Upload a PDF or DOCX resume.');
      return;
    }
    // `undefined` means the consent read is still in flight, and is treated as NOT consented
    // so a slow read delays the upload rather than skipping the explanation.
    if (hasConsented !== true) {
      setAwaitingConsent(file);
      return;
    }
    send(file, onDone);
  };

  /** Call when the gate reports consent granted. */
  const consentGranted = (onDone?: () => void) => {
    const file = awaitingConsent;
    setAwaitingConsent(null);
    // So the gate does not reappear for the next upload in this tab.
    queryClient.invalidateQueries({ queryKey: ['legal', 'consent'] });
    if (file) send(file, onDone);
  };

  return {
    submit,
    isUploading: upload.isPending,
    awaitingConsent,
    consentGranted,
    cancelConsent: () => setAwaitingConsent(null),
  };
}
