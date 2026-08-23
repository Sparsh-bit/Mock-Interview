'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ImageIcon, Trash2, Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { getBrowserApiClient } from '@/lib/api';
import { ApiError } from '@/lib/api/errors';

/**
 * The promo banner for one offer — components/admin/OfferBannerControl.tsx
 *
 * WHAT THIS IS FOR. An offer can carry an image that appears as a strip on every candidate's
 * dashboard and links to the pricing page's apply-a-code box. This is where the owner uploads
 * it, sees what is currently live, and takes it down.
 *
 * THE REQUIREMENTS ARE ON SCREEN, NOT IN A DOC. The exact pixel size, the ratio, the size
 * limit and the formats are rendered next to the file picker, and they come from the SERVER
 * (`/admin/offers/banner-spec`) rather than being written here — the validator and the form
 * must not be able to disagree. A form promising 2400x800 while the server accepts something
 * else presents as the upload mysteriously failing, and the person debugging it is the same
 * person who read the form.
 *
 * IT CHECKS BEFORE IT UPLOADS, AND THE SERVER CHECKS AGAIN. The browser can read an image's
 * dimensions locally, so a wrongly-sized file is refused instantly with the real numbers
 * instead of after a round trip carrying the whole file. That is a courtesy, not a control:
 * `validate_banner` on the server is the authority, and this deliberately does not try to
 * reimplement its rules — it checks the one thing a person gets wrong (the shape) and lets
 * the server have the final word on everything.
 *
 * WHY THE PREVIEW IS RENDERED AT THE REAL ASPECT RATIO. A banner that looks right in a file
 * browser can still be wrong on the dashboard, and the only honest preview is one shaped like
 * the container it will live in. The strip below is the same `aspect-[3/1]` box with the same
 * `object-cover` the dashboard uses, so what the owner sees here is what a candidate sees.
 */

interface BannerSpec {
  aspect_ratio: number;
  aspect_label: string;
  recommended_width: number;
  recommended_height: number;
  min_width: number;
  min_height: number;
  max_bytes: number;
  max_kb: number;
  formats: string[];
}

export interface OfferBanner {
  image_url: string;
  alt_text: string;
  width: number;
  height: number;
  bytes: number;
  content_type: string;
  matches_spec: boolean;
}

/**
 * The dimensions of a local file, read in the browser.
 *
 * Resolves null rather than throwing for anything unreadable — a file that is not an image at
 * all, or is corrupt. The caller treats null as "let the server decide", because this exists
 * to give fast feedback on the common mistake and must never be the thing that blocks an
 * upload the server would have accepted.
 */
function readLocalDimensions(file: File): Promise<{ width: number; height: number } | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      // Revoked in both paths: an object URL held for the lifetime of the page is a leak,
      // and this component can be used many times while iterating on an image.
      URL.revokeObjectURL(url);
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(null);
    };
    img.src = url;
  });
}

export function OfferBannerControl({
  offerId,
  banner,
}: {
  offerId: string;
  banner: OfferBanner | null;
}) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  // Shared across every row: the spec is one fact about the product, not per-offer, so a
  // single cached query rather than one request per offer on the page.
  const spec = useQuery({
    queryKey: ['admin', 'banner-spec'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/admin/offers/banner-spec');
      return res.data as BannerSpec;
    },
    staleTime: Infinity,
  });

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append('file', file);
      const res = await getBrowserApiClient().post(
        `/api/v1/admin/offers/${offerId}/banner`,
        form,
        { timeout: 60_000 },
      );
      return res.data as OfferBanner;
    },
    onSuccess: () => {
      toast.success('Banner is live on the dashboard.');
      void qc.invalidateQueries({ queryKey: ['admin', 'offers'] });
    },
    onError: (err) => {
      // The server's message is written for the person reading it — "that image is 1600x900,
      // which is 16:9, export it at 2400x800" — so it is shown verbatim. A generic string
      // here would throw away the only part of the response that says what to do next.
      toast.error(
        err instanceof ApiError && err.message
          ? err.message
          : 'That image could not be uploaded.',
      );
    },
  });

  const remove = useMutation({
    mutationFn: async () => {
      await getBrowserApiClient().delete(`/api/v1/admin/offers/${offerId}/banner`);
    },
    onSuccess: () => {
      toast.success('Banner removed.');
      void qc.invalidateQueries({ queryKey: ['admin', 'offers'] });
    },
    onError: () => toast.error('Could not remove that banner.'),
  });

  const s = spec.data;

  const pick = async (file: File | undefined) => {
    if (!file || !s) return;
    setBusy(true);
    try {
      // Cheap local checks first, in the order the server does them, so the message names the
      // first thing wrong rather than a consequence of it.
      if (file.size > s.max_bytes) {
        toast.error(
          `That image is ${Math.round(file.size / 1024)} KB and the limit is ${s.max_kb} KB. ` +
            `Export it as WebP — a ${s.recommended_width}x${s.recommended_height} banner is ` +
            'usually well under 200 KB.',
        );
        return;
      }
      const dims = await readLocalDimensions(file);
      if (dims) {
        if (dims.width < s.min_width) {
          toast.error(
            `That image is ${dims.width}px wide and would look soft. Export it at ` +
              `${s.recommended_width}x${s.recommended_height}.`,
          );
          return;
        }
        const ratio = dims.width / dims.height;
        // The same 2% tolerance the server applies, so the two cannot disagree about a
        // 2400x801 export. Kept as a literal here only because it is a courtesy check; the
        // server's copy is the one that decides.
        if (Math.abs(ratio - s.aspect_ratio) > s.aspect_ratio * 0.02) {
          toast.error(
            `That image is ${dims.width}x${dims.height}. A banner has to be ` +
              `${s.aspect_label} so it fits the dashboard strip without being cropped — ` +
              `export it at ${s.recommended_width}x${s.recommended_height}.`,
          );
          return;
        }
      }
      await upload.mutateAsync(file);
    } finally {
      setBusy(false);
      // Cleared so choosing the SAME file again still fires a change event, which is exactly
      // what somebody re-exporting an image at the right size will do.
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <div className="mt-3 w-full rounded-xl border border-border/70 bg-surface/40 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
            <ImageIcon className="h-3.5 w-3.5" aria-hidden />
            Dashboard banner
          </p>
          {/* THE SPEC, STATED EXACTLY. One precise size rather than a range: a range
              produces uploads at the smallest value in it. */}
          {s ? (
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
              Export at{' '}
              <strong className="font-semibold text-foreground">
                {s.recommended_width} × {s.recommended_height}
              </strong>{' '}
              ({s.aspect_label}) · max {s.max_kb} KB ·{' '}
              {s.formats.map((f) => f.toUpperCase()).join(', ')} · minimum {s.min_width}px wide.
              Keep the promo code well inside the frame — on a phone this strip is about 120px
              tall.
            </p>
          ) : (
            <p className="mt-1 text-[11px] text-muted-foreground">Loading requirements…</p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            // The formats the server will accept, so the OS picker does not offer files that
            // are certain to be refused. Not a control — see the docstring.
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            id={`banner-file-${offerId}`}
            onChange={(e) => void pick(e.target.files?.[0])}
          />
          <Button
            variant="secondary"
            size="sm"
            loading={busy || upload.isPending}
            disabled={!s}
            onClick={() => fileRef.current?.click()}
          >
            <Upload className="h-3.5 w-3.5" />
            {banner ? 'Replace' : 'Upload'}
          </Button>
          {banner && (
            <Button
              variant="ghost"
              size="sm"
              loading={remove.isPending}
              onClick={() => remove.mutate()}
              aria-label="Remove banner"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      {banner && (
        <div className="mt-3">
          {/* THE SAME BOX THE DASHBOARD USES — `aspect-[3/1]` with `object-cover` — because a
              preview shaped differently to the real container is not a preview. */}
          <div className="overflow-hidden rounded-lg border border-border/60">
            {/* eslint-disable-next-line @next/next/no-img-element -- a Supabase public URL is
                not a configured next/image domain, and adding one for an admin-only preview
                would be a build-config change for no rendering benefit. */}
            <img
              src={banner.image_url}
              alt={banner.alt_text}
              className="aspect-[3/1] w-full object-cover"
            />
          </div>
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            {banner.width} × {banner.height} · {Math.round(banner.bytes / 1024)} KB
          </p>
          {/* RECOMPUTED SERVER-SIDE ON EVERY READ, so raising the requirement surfaces every
              banner that now needs re-exporting instead of leaving the owner to compare
              numbers by eye. */}
          {!banner.matches_spec && s && (
            <p className="mt-2 rounded-md border border-accent-amber/40 bg-accent-amber/10 px-2.5 py-1.5 text-[11px] text-accent-amber-ink">
              This image no longer matches the requirement ({s.recommended_width} ×{' '}
              {s.recommended_height}, {s.aspect_label}). It is still live — candidates see it
              cropped to fit rather than distorted — but re-exporting it will look better.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default OfferBannerControl;
