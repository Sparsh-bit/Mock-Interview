'use client';

import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Sparkles } from 'lucide-react';

const DEFAULT_MESSAGES = [
  'Reading your answer…',
  'Checking technical accuracy…',
  'Weighing communication clarity…',
  'Comparing against the ideal answer…',
  'Almost done…',
];

interface AIWorkingIndicatorProps {
  messages?: string[];
  /** Rotation interval in ms. */
  intervalMs?: number;
  className?: string;
}

/**
 * Rotating status text for AI calls that can take anywhere from a few
 * seconds to over a minute (free-tier model latency) -- communicates
 * ongoing progress instead of a bare spinner that reads as stuck.
 */
export function AIWorkingIndicator({
  messages = DEFAULT_MESSAGES,
  intervalMs = 3500,
  className,
}: AIWorkingIndicatorProps) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    setIndex(0);
    const id = setInterval(() => {
      setIndex((i) => Math.min(i + 1, messages.length - 1));
    }, intervalMs);
    return () => clearInterval(id);
  }, [messages, intervalMs]);

  return (
    <div className={`flex items-center gap-2 text-xs text-muted-foreground ${className ?? ''}`}>
      <Sparkles className="h-3.5 w-3.5 shrink-0 animate-pulse text-primary" />
      <AnimatePresence mode="wait">
        <motion.span
          key={index}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.25 }}
        >
          {messages[index]}
        </motion.span>
      </AnimatePresence>
    </div>
  );
}
