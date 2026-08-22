'use client';

import { useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  Loader2,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { usePrimaryResume, useUploadResume, useDeleteResume, type StoredResume } from '@/hooks/useData';
import { cn } from '@/lib/utils';

/** Mirrors the server's MAX_UPLOAD_SIZE_MB so we can reject before uploading. */
const MAX_MB = 10;

const ACCEPTED = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'];
const ACCEPT_ATTR = '.pdf,.docx,application/pdf';

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * What the candidate is told about the resume we hold.
 *
 * Deliberately distinguishes "read and analysed" from "read but not analysed":
 * both personalise the interview, and collapsing them into a single "uploaded"
 * badge is what allowed a resume to sit unparsed and unused without anyone
 * noticing.
 */
function statusMeta(resume: StoredResume): {
  tone: string;
  icon: typeof CheckCircle2;
  label: string;
  detail: string;
} {
  if (resume.parsing_status === 'completed') {
    return {
      tone: 'text-accent-emerald-ink',
      icon: CheckCircle2,
      label: 'Read and analysed',
      detail: 'Your interviews will ask about these projects and skills by name.',
    };
  }
  if (resume.parsing_status === 'partial') {
    // Half the analysis landed. Its own state rather than a shade of failure: the
    // server asks for skills and for projects as two independent calls, so one
    // arriving without the other is normal-and-usable, and the message says which
    // half is missing.
    return {
      tone: 'text-accent-amber-ink',
      icon: AlertTriangle,
      label: 'Partly analysed',
      detail:
        resume.parsing_error ??
        'Part of the analysis could not be built. Interviews will still use your resume.',
    };
  }
  if (resume.has_text) {
    return {
      tone: 'text-accent-amber-ink',
      icon: AlertTriangle,
      label: 'Read, not fully analysed',
      detail:
        resume.parsing_error ??
        'The text was read but the skill breakdown could not be built. Interviews will still use your resume.',
    };
  }
  return {
    tone: 'text-accent-coral-ink',
    icon: AlertTriangle,
    label: 'Not readable',
    detail: resume.parsing_error ?? 'No text could be read from this file. Try uploading the original PDF export.',
  };
}

export function ResumeUploadCard() {
  const { data: resume, isLoading } = usePrimaryResume();
  const upload = useUploadResume();
  const remove = useDeleteResume();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const submit = (file: File) => {
    // Check locally first. Uploading 40 MB just to be told the limit is 10 is a
    // waste of the candidate's time and bandwidth, and on a slow connection it
    // looks like the app hung.
    if (file.size > MAX_MB * 1024 * 1024) {
      toast.error(`That file is ${formatSize(file.size)}. The limit is ${MAX_MB} MB.`);
      return;
    }
    const byExtension = /\.(pdf|docx)$/i.test(file.name);
    if (!ACCEPTED.includes(file.type) && !byExtension) {
      toast.error('Upload a PDF or DOCX resume.');
      return;
    }

    upload.mutate(file, {
      onSuccess: (result) => {
        const skills = result.parsed_skills?.length ?? 0;
        if (result.parsing_status === 'completed') {
          toast.success(
            `Resume analysed — ${skills} skill${skills === 1 ? '' : 's'} and ${result.project_count} project${
              result.project_count === 1 ? '' : 's'
            } found.`
          );
        } else if (result.parsing_status === 'partial') {
          // Say what actually landed. Announcing a bare "uploaded" here is how a
          // resume with zero extracted skills used to read as a full success.
          const found = skills > 0
            ? `${skills} skill${skills === 1 ? '' : 's'} found`
            : `${result.project_count} project${result.project_count === 1 ? '' : 's'} found`;
          toast.success(`Resume uploaded — ${found}. Part of the analysis could not be built.`);
        } else {
          toast.success('Resume uploaded. Interviews will use it.');
        }
      },
      onError: (err: unknown) => {
        // The server explains exactly why a file could not be read ("that PDF is
        // a scan — upload the original export"). Showing a generic failure would
        // throw away the one message the candidate can act on.
        const message = (err as { message?: string })?.message?.trim();
        toast.error(message || 'That resume could not be uploaded.');
      },
    });
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) submit(file);
  };

  const meta = resume ? statusMeta(resume) : null;

  return (
    <Card className="p-6">
      <div className="mb-1 flex items-center gap-2">
        <FileText className="h-5 w-5 text-primary" />
        <h3 className="text-base font-semibold">Your resume</h3>
      </div>
      <p className="mb-5 text-sm text-muted-foreground">
        Upload it once. Every interview after that asks about your actual projects and skills —
        including questions that start with &ldquo;as you mentioned in your resume&hellip;&rdquo;
      </p>

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Checking&hellip;
        </div>
      ) : resume && meta ? (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-border/60 bg-surface/50 p-4"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              {/* `break-all`, not `truncate`. A filename is a single unbreakable token and
                  it is the only thing telling the candidate WHICH resume is on file — cutting
                  it off withholds exactly the information they opened this card for. */}
              <p className="break-all text-sm font-semibold">{resume.filename}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {formatSize(resume.file_size_bytes)} · uploaded{' '}
                {new Date(resume.created_at).toLocaleDateString()}
              </p>

              <div className={cn('mt-3 flex items-center gap-1.5 text-xs font-semibold', meta.tone)}>
                <meta.icon className="h-3.5 w-3.5" />
                {meta.label}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{meta.detail}</p>

              {resume.priority_topics.length > 0 && (
                <div className="mt-4">
                  <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    <Sparkles className="h-3 w-3" /> Interviews will focus on
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {resume.priority_topics.map((topic) => (
                      <span
                        key={topic}
                        className="rounded-full border border-primary/20 bg-primary/10 px-2.5 py-0.5 text-xs text-primary"
                      >
                        {topic}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="flex shrink-0 gap-2">
              <Button
                variant="secondary"
                onClick={() => inputRef.current?.click()}
                loading={upload.isPending}
              >
                <Upload className="h-3.5 w-3.5" /> Replace
              </Button>
              <Button
                variant="ghost"
                loading={remove.isPending}
                onClick={() => {
                  remove.mutate(resume.id, {
                    onSuccess: () => toast.success('Resume removed.'),
                    onError: () => toast.error('Could not remove that resume.'),
                  });
                }}
                aria-label="Remove resume"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </motion.div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          disabled={upload.isPending}
          className={cn(
            'flex w-full flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-8 text-center transition-colors',
            dragging ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50 hover:bg-secondary/40',
            upload.isPending && 'cursor-wait opacity-70'
          )}
        >
          {upload.isPending ? (
            <>
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
              <p className="text-sm font-semibold">Reading and analysing your resume&hellip;</p>
              <p className="text-xs text-muted-foreground">This takes a few seconds.</p>
            </>
          ) : (
            <>
              <Upload className="h-6 w-6 text-primary" />
              <p className="text-sm font-semibold">Drop your resume here, or click to choose</p>
              <p className="text-xs text-muted-foreground">PDF or DOCX, up to {MAX_MB} MB</p>
            </>
          )}
        </button>
      )}

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT_ATTR}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          // Reset so choosing the same file twice still fires a change event —
          // otherwise a failed upload cannot be retried with the same file.
          e.target.value = '';
          if (file) submit(file);
        }}
      />
    </Card>
  );
}
