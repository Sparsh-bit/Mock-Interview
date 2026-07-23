/**
 * MediaPipe / TensorFlow-Lite emit benign glog-style diagnostics
 * ("INFO: Created TensorFlow Lite XNNPACK delegate for CPU.", GL version
 * banners, etc.) through console.error/console.warn during WASM init and
 * inference. The high-level @mediapipe/tasks-vision API exposes no way to
 * silence them, and Next.js's dev overlay elevates ANY console.error into a
 * red "Console Error", so these harmless lines look like real failures.
 *
 * installMediapipeLogFilter() patches the console to DROP only those known
 * diagnostic lines — every other log/warn/error passes through untouched —
 * and returns a restore function so the patch is fully reversible (we install
 * it while the presence monitor runs and restore it when it stops).
 */

// Matches glog-style prefixes (INFO:/WARNING:/I0000.../W0000...) and the
// specific TFLite/GL banners MediaPipe prints. Deliberately narrow so real
// application errors are never swallowed.
const MEDIAPIPE_DIAGNOSTIC = /^(INFO:|WARNING:|I\d{4}|W\d{4})|XNNPACK|TensorFlow Lite|Created \w+ delegate|GL version|OpenGL error checking is disabled/;

type ConsoleMethod = 'log' | 'info' | 'warn' | 'error' | 'debug';

export function installMediapipeLogFilter(): () => void {
  if (typeof console === 'undefined') return () => {};

  const methods: ConsoleMethod[] = ['log', 'info', 'warn', 'error', 'debug'];
  const originals = new Map<ConsoleMethod, (...args: unknown[]) => void>();

  for (const m of methods) {
    const original = console[m].bind(console) as (...args: unknown[]) => void;
    originals.set(m, original);
    console[m] = (...args: unknown[]) => {
      const first = args[0];
      if (typeof first === 'string' && MEDIAPIPE_DIAGNOSTIC.test(first)) {
        return; // drop benign MediaPipe/TFLite diagnostic
      }
      original(...args);
    };
  }

  return () => {
    for (const m of methods) {
      const original = originals.get(m);
      if (original) console[m] = original as typeof console.log;
    }
  };
}
