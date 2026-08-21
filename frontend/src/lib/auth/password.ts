import { z } from 'zod';

/**
 * What a password must be — lib/auth/password.ts
 *
 * ONE DEFINITION, because there are now two forms that set one. Registration has always had
 * these rules; the reset-completion form is new (see app/(auth)/reset-password) and a second
 * copy would drift. The drift would not be cosmetic either: if reset were laxer than
 * registration, "forgot password" would become a documented route to a weaker password than
 * the signup form allows — a bypass, not an inconsistency.
 *
 * Eight characters with an uppercase and a digit, matching what register already enforced.
 * Deliberately NOT tightened here: raising the bar inside the change that fixes a broken flow
 * would lock out people whose current password no longer qualifies, and that is a separate
 * decision with its own migration story.
 */
export const passwordRules = z
  .string()
  .min(8, 'Password must be at least 8 characters')
  .regex(/[A-Z]/, 'Include at least one uppercase letter')
  .regex(/[0-9]/, 'Include at least one number');

/** A password plus its confirmation, for any form that SETS a password rather than checks one. */
export const newPasswordSchema = z
  .object({
    password: passwordRules,
    confirmPassword: z.string(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords don't match",
    path: ['confirmPassword'],
  });

export type NewPasswordForm = z.infer<typeof newPasswordSchema>;
