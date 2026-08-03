import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

/**
 * Vitest configuration.
 *
 * WHY THIS FILE EXISTS. There was no config at all, so vitest ran on defaults and
 * did not know about the `@/` path alias that tsconfig defines and that every
 * module in src/ uses. Any test that pulled in a module importing `@/…` at
 * RUNTIME failed to resolve — which meant the suite could only ever test modules
 * with no internal imports, or ones whose `@/` imports were type-only and
 * therefore erased before vitest saw them.
 *
 * That is why it went unnoticed: `useSpeech.ts` imported `@/lib/speech/delivery`
 * for a type, TypeScript erased it, and the missing alias stayed invisible until
 * a real value import was added.
 *
 * The alias is duplicated from tsconfig.json because vitest resolves modules
 * itself and cannot read tsconfig paths without a plugin. Keep the two in step.
 */
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
});
