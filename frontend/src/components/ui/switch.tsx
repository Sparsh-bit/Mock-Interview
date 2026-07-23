'use client';

import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';

interface SwitchProps {
  checked: boolean;
  onChange: () => void;
  className?: string;
}

export function Switch({ checked, onChange, className }: SwitchProps) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={onChange}
      className={cn(
        'relative h-[31px] w-[51px] rounded-full p-0.5 transition-colors duration-300 ease-out-expo',
        checked ? 'bg-success' : 'bg-[hsl(240,9%,83%)]',
        className
      )}
    >
      <motion.div
        className="h-[27px] w-[27px] rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.25)]"
        animate={{ x: checked ? 20 : 0 }}
        transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
      />
    </button>
  );
}
