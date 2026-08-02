'use client';

import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { ChevronLeft, Code2, Info, Loader2, XCircle } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { CodingWorkspace } from '@/components/interview/CodingWorkspace';
import { getBrowserApiClient } from '@/lib/api';
import { fadeUp, scalePop, staggerContainer } from '@/lib/motion';

export const runtime = 'edge';

interface PracticeQuestion {
  id: string;
  content: string;
  question_type: string;
  difficulty: string;
  topic: string;
  expected_keywords: string[];
  ideal_answer: string | null;
  time_limit_seconds: number | null;
}

function usePracticeQuestion(questionId: string) {
  return useQuery({
    queryKey: ['practice-question', questionId],
    queryFn: async () => {
      const res = await getBrowserApiClient().get(`/api/v1/questions/${questionId}`);
      return res.data as PracticeQuestion;
    },
    enabled: !!questionId,
    // Question text is immutable once written.
    staleTime: Infinity,
  });
}

export default function PracticePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[50vh] items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      }
    >
      <Practice />
    </Suspense>
  );
}

function Practice() {
  const params = useParams();
  const questionId = params.questionId as string;
  const router = useRouter();
  const search = useSearchParams();
  // Where to go "back" to. Passed by the detailed analysis so returning lands on
  // the report the candidate came from rather than the dashboard.
  const from = search.get('from');

  const { data: question, isLoading, error } = usePracticeQuestion(questionId);

  if (isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error || !question) {
    return (
      <motion.div initial="hidden" animate="visible" variants={scalePop} className="mx-auto mt-12 max-w-2xl">
        <Card className="border-destructive/20 p-8 text-center">
          <XCircle className="mx-auto mb-4 h-12 w-12 text-destructive" />
          <h2 className="mb-2 text-xl font-semibold">Question Unavailable</h2>
          <p className="text-sm text-muted-foreground">
            {(error as { message?: string } | null)?.message || 'This question could not be loaded.'}
          </p>
          <Button className="mt-6" variant="secondary" onClick={() => router.push('/dashboard')}>
            Back to dashboard
          </Button>
        </Card>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={staggerContainer(0.06)}
      className="mx-auto max-w-5xl space-y-6 pb-16"
    >
      <motion.div variants={fadeUp}>
        <button
          onClick={() => router.push(from || '/dashboard')}
          className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" /> {from ? 'Back to Analysis' : 'Back to Dashboard'}
        </button>
      </motion.div>

      {/* Practice mode is stated plainly at the top. Someone arriving here from a
          report needs to know immediately that this is NOT the interview resuming
          — nothing they do here is scored or recorded against that session. */}
      <motion.div variants={fadeUp}>
        <Card className="p-5">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Badge variant="violet">Practice mode</Badge>
            <Badge variant="neutral">{question.topic}</Badge>
            <Badge variant={question.difficulty === 'hard' ? 'danger' : question.difficulty === 'easy' ? 'success' : 'warning'}>
              {question.difficulty}
            </Badge>
          </div>
          <h1 className="flex items-start gap-2 text-lg font-semibold leading-relaxed">
            <Code2 className="mt-1 h-5 w-5 shrink-0 text-primary" />
            {question.content}
          </h1>

          <div className="mt-4 flex items-start gap-2 rounded-lg border border-border/60 bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              This is a standalone practice attempt — your interview is not resumed and nothing here
              changes its report. Rewrite the solution, run it, and have it reviewed as many times as
              you like.
            </span>
          </div>

          {question.expected_keywords.length > 0 && (
            <div className="mt-4">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                A strong solution touches on
              </p>
              <div className="flex flex-wrap gap-1.5">
                {question.expected_keywords.map((kw) => (
                  <span
                    key={kw}
                    className="rounded-full border border-border bg-secondary/50 px-2.5 py-0.5 text-xs text-muted-foreground"
                  >
                    {kw}
                  </span>
                ))}
              </div>
            </div>
          )}
        </Card>
      </motion.div>

      {/* The same workspace the interview uses, so Run and "Review my code"
          behave identically. onSubmit is a no-op here by design: there is no
          session to record an answer against, and the review button is the whole
          point of practice mode. */}
      <motion.div variants={fadeUp}>
        <CodingWorkspace
          hideSubmit
          onSubmit={() => {
            /* Unreachable: hideSubmit removes the only caller. */
          }}
          problemTitle={question.topic}
          problemDescription={question.content}
          difficulty={question.difficulty}
        />
      </motion.div>
    </motion.div>
  );
}
