'use client';

import { useMemo } from 'react';

import { cn } from '@/lib/utils';

/**
 * Password strength, shown honestly — components/lightswind-pro/password-strength.tsx
 *
 * Local implementation at the import path the brief named; `lightswind-pro` is not installed.
 *
 * WHAT IT SCORES, AND WHAT IT DELIBERATELY DOES NOT. Length carries most of the weight,
 * because it genuinely carries most of the entropy — "correct horse battery staple" is far
 * stronger than "P@ss1!" and a meter that says otherwise is teaching the wrong lesson. Variety
 * counts, but less, and it cannot on its own lift a short password past "fair".
 *
 * It also refuses to call anything strong if it contains an obvious sequence or a repeated
 * run, because those are the first things a cracker tries and a green bar on "abcd1234" is
 * actively misleading.
 *
 * PURELY ADVISORY. It does not block submission — that is the server's job, and a meter that
 * gates the form turns a hint into an argument with the user about their own password
 * manager's output.
 *
 * NOTHING LEAVES THE BROWSER. All of this is computed locally; a password must never be sent
 * anywhere to be scored.
 */
export interface PasswordStrengthProps {
  password: string;
  className?: string;
}

const LEVELS = [
  { label: 'Too short', bar: 'bg-destructive', text: 'text-destructive' },
  { label: 'Weak', bar: 'bg-accent-coral', text: 'text-accent-coral-ink' },
  { label: 'Fair', bar: 'bg-accent-amber', text: 'text-accent-amber-ink' },
  { label: 'Good', bar: 'bg-accent-teal', text: 'text-accent-teal-ink' },
  { label: 'Strong', bar: 'bg-accent-emerald', text: 'text-accent-emerald-ink' },
] as const;

/** 0-4. Exported for tests — the thresholds are the whole of the advice. */
export function scorePassword(password: string): number {
  const pw = password ?? '';
  if (pw.length < 8) return 0;

  let score = 1;
  // Length is the dominant term, deliberately. Each of these is roughly a doubling of the
  // search space that no amount of punctuation in a short password can match.
  if (pw.length >= 12) score += 1;
  if (pw.length >= 16) score += 1;

  const variety =
    Number(/[a-z]/.test(pw)) +
    Number(/[A-Z]/.test(pw)) +
    Number(/[0-9]/.test(pw)) +
    Number(/[^A-Za-z0-9]/.test(pw));
  if (variety >= 3) score += 1;

  // Cheap patterns cap the result. "abcd1234" and "aaaaaaaaaa" clear the length bar and are
  // the first things anyone tries, so a green bar on them would be a lie.
  const sequential = /(abc|bcd|cde|def|123|234|345|456|567|678|789|qwe|wer|ert|asd)/i.test(pw);
  const repeated = /(.)\1{2,}/.test(pw);
  if (sequential || repeated) score = Math.min(score, 2);

  return Math.min(score, 4);
}

export default function PasswordStrength({ password, className }: PasswordStrengthProps) {
  const score = useMemo(() => scorePassword(password), [password]);
  const level = LEVELS[score];

  // Nothing typed yet — an empty form should not open with "Too short" in red.
  if (!password) return null;

  return (
    <div className={cn('mt-2', className)} aria-live="polite">
      <div className="flex gap-1">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={cn(
              'h-1 flex-1 rounded-full transition-colors duration-300',
              i <= score - 1 || (score === 0 && i === 0)
                ? score === 0
                  ? 'bg-destructive'
                  : level.bar
                : 'bg-secondary',
            )}
          />
        ))}
      </div>
      <p className={cn('mt-1 text-[11px] font-medium', level.text)}>
        {level.label}
        {score < 2 && password.length < 12 && (
          <span className="font-normal text-muted-foreground"> · length helps more than symbols</span>
        )}
      </p>
    </div>
  );
}
