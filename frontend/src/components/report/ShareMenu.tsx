'use client';

import { useEffect, useRef, useState } from 'react';
import {
  Check,
  Download,
  Globe,
  Link2,
  Loader2,
  Lock,
  Mail,
  MessageCircle,
  Share2,
  X,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface ShareMenuProps {
  reportId: string;
  isShared: boolean;
  onToggleShare: () => void;
  toggling?: boolean;
  /** Headline used in the share text, e.g. "78/100 · Interview Ready". */
  summary?: string;
  trackName?: string;
}

/** The public URL for a shared report. Absolute — it is going into WhatsApp. */
function publicUrl(reportId: string): string {
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  return `${origin}/r/${reportId}`;
}

export function ShareMenu({
  reportId,
  isShared,
  onToggleShare,
  toggling,
  summary,
  trackName,
}: ShareMenuProps) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  // Close on outside click and on Escape — a share panel that traps the user is
  // worse than one that is slightly too eager to close.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const url = publicUrl(reportId);
  const title = `My ${trackName ?? 'mock interview'} report on InterviewOS`;
  const text = summary ? `${title} — ${summary}` : title;

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard is blocked in some embedded browsers and over plain http.
      toast.error('Could not copy. Long-press the link to copy it manually.');
    }
  };

  /**
   * Native share sheet where the OS provides one — on a phone this is how the
   * candidate reaches WhatsApp, Telegram, Instagram or anything else they have
   * installed, without us guessing at a list. The explicit buttons below remain
   * for desktop, where navigator.share mostly does not exist.
   */
  const nativeShare = async () => {
    if (typeof navigator === 'undefined' || !navigator.share) return false;
    try {
      await navigator.share({ title, text, url });
      return true;
    } catch {
      // A user cancelling the sheet throws — not an error worth reporting.
      return true;
    }
  };

  const targets = [
    {
      name: 'WhatsApp',
      icon: MessageCircle,
      // wa.me works on mobile app and WhatsApp Web alike.
      href: `https://wa.me/?text=${encodeURIComponent(`${text}\n${url}`)}`,
      tone: 'text-emerald-600',
    },
    {
      name: 'LinkedIn',
      icon: Globe,
      href: `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`,
      tone: 'text-blue-600',
    },
    {
      name: 'X',
      icon: X,
      href: `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
      tone: 'text-foreground',
    },
    {
      name: 'Email',
      icon: Mail,
      href: `mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(`${text}\n\n${url}`)}`,
      tone: 'text-muted-foreground',
    },
  ];

  return (
    <div className="relative" ref={panelRef}>
      <div className="flex flex-wrap items-center gap-2">
        {/* Print-to-PDF. Deliberately the browser's own print pipeline rather than
            a JS PDF library: it produces a real vector PDF with selectable text at
            the correct paper size, needs no dependency, and works identically on
            desktop and mobile. Canvas-based libraries produce a heavy raster image
            of the page with unsearchable text. */}
        <Button
          variant="secondary"
          onClick={() => window.print()}
          className="print:hidden"
        >
          <Download className="h-3.5 w-3.5" />
          Download PDF
        </Button>

        <Button
          onClick={async () => {
            // If sharing is already on and the OS has a share sheet, go straight
            // there — that is the fastest path to WhatsApp on a phone.
            if (isShared && (await nativeShare())) return;
            setOpen((v) => !v);
          }}
          className="print:hidden"
        >
          <Share2 className="h-3.5 w-3.5" />
          Share
        </Button>
      </div>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-[19rem] rounded-xl border border-border bg-surface-elevated p-4 shadow-xl print:hidden">
          {/* Sharing state first. A link that 404s because sharing is off is the
              most confusing possible outcome, so it cannot be silent. */}
          <div className="mb-3 flex items-start gap-2 rounded-lg border border-border/60 bg-secondary/40 p-3">
            {isShared ? (
              <Globe className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
            ) : (
              <Lock className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold">
                {isShared ? 'Link sharing is on' : 'Link sharing is off'}
              </p>
              <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                {isShared
                  ? 'Anyone with the link can view your score, summary and topic breakdown. Your answers are never shown.'
                  : 'Turn it on to create a link. Until then, the link will not open for anyone.'}
              </p>
              <button
                onClick={onToggleShare}
                disabled={toggling}
                className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-semibold text-primary hover:underline disabled:opacity-50"
              >
                {toggling && <Loader2 className="h-3 w-3 animate-spin" />}
                {isShared ? 'Turn sharing off' : 'Turn sharing on'}
              </button>
            </div>
          </div>

          <div className={cn('space-y-3', !isShared && 'pointer-events-none opacity-40')}>
            <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2.5 py-2">
              <Link2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">{url}</span>
              <button
                onClick={copyLink}
                className="shrink-0 rounded-md px-2 py-1 text-[11px] font-semibold text-primary hover:bg-primary/10"
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : 'Copy'}
              </button>
            </div>

            <div className="grid grid-cols-4 gap-2">
              {targets.map(({ name, icon: Icon, href, tone }) => (
                <a
                  key={name}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex flex-col items-center gap-1.5 rounded-lg border border-border bg-surface px-2 py-3 transition-colors hover:bg-secondary"
                >
                  <Icon className={cn('h-4 w-4', tone)} />
                  <span className="text-[10px] font-medium text-muted-foreground">{name}</span>
                </a>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
