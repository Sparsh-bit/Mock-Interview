'use client';

import { useInterview } from '@/hooks/useInterview';
import { useTracks } from '@/hooks/useData';
import { Play, Code2, Loader2, CheckCircle2 } from 'lucide-react';
import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

export default function InterviewSetupPage() {
  return (
    <Suspense fallback={<div className="text-sm text-muted-foreground mt-10 text-center">Loading...</div>}>
      <InterviewSetup />
    </Suspense>
  );
}

function InterviewSetup() {
  const { startSession } = useInterview();
  const { data: tracks, isLoading: tracksLoading } = useTracks();
  const searchParams = useSearchParams();
  const requestedTrackId = searchParams.get('trackId');
  const [selectedTrackId, setSelectedTrackId] = useState<string>('');

  useEffect(() => {
    if (!tracks || tracks.length === 0 || selectedTrackId) return;

    if (requestedTrackId && tracks.some((track) => track.id === requestedTrackId)) {
      setSelectedTrackId(requestedTrackId);
    } else {
      setSelectedTrackId(tracks[0].id);
    }
  }, [tracks, selectedTrackId, requestedTrackId]);

  const handleStart = () => {
    if (!selectedTrackId) return;
    startSession.mutate(selectedTrackId);
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8 mt-10">
      <div className="glass rounded-xl border border-border/50 p-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold">Start a New Mock Interview</h1>
          <p className="text-muted-foreground mt-2">
            Select an interview track to begin. The AI will evaluate your answers in real-time.
          </p>
        </div>

        {tracksLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 mb-8">
            {(tracks || []).map((track) => {
              const isSelected = selectedTrackId === track.id;
              return (
                <div
                  key={track.id}
                  className={`cursor-pointer rounded-xl border p-6 transition-all ${
                    isSelected
                      ? 'border-primary bg-primary/10 shadow-glow'
                      : 'border-border/50 bg-surface hover:border-primary/50'
                  }`}
                  onClick={() => setSelectedTrackId(track.id)}
                >
                  <div className="flex items-center justify-between mb-4">
                    <div className="h-10 w-10 rounded-lg bg-blue-500/20 flex items-center justify-center">
                      <Code2 className="h-5 w-5 text-blue-600" />
                    </div>
                    {isSelected && <CheckCircle2 className="h-5 w-5 text-primary" />}
                  </div>
                  <h3 className="font-bold text-lg">{track.company.name}</h3>
                  <p className="text-sm font-medium text-foreground/90 mt-0.5">{track.name}</p>
                  <p className="text-xs text-muted-foreground mt-2">
                    {track.description || 'Full stack technical assessment round.'}
                  </p>
                  <div className="mt-4 flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{track.duration_minutes || 45} mins</span>
                    <span>•</span>
                    <span>{track.difficulty_level || 'Intermediate'}</span>
                  </div>
                </div>
              );
            })}

            {/* Upcoming track placeholder */}
            <div className="rounded-xl border border-border/30 bg-surface/30 p-6 opacity-50 cursor-not-allowed">
              <div className="h-10 w-10 rounded-lg bg-emerald-500/10 flex items-center justify-center mb-4">
                <Code2 className="h-5 w-5 text-emerald-600" />
              </div>
              <h3 className="font-bold text-lg">TCS Digital</h3>
              <p className="text-sm text-muted-foreground mt-1">Java Backend (Coming Soon)</p>
            </div>
          </div>
        )}

        <button
          onClick={handleStart}
          disabled={startSession.isPending || !selectedTrackId}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary px-6 py-4 text-sm font-bold text-primary-foreground hover:bg-primary/90 transition-all disabled:opacity-50 shadow-glow"
        >
          {startSession.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Preparing Session...
            </>
          ) : (
            <>
              <Play className="h-4 w-4" />
              Begin Interview Simulation
            </>
          )}
        </button>
      </div>
    </div>
  );
}
