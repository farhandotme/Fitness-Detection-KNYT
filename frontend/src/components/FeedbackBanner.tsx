import React from 'react';
import { cn } from '@/lib/utils';
import { AlertCircle, CheckCircle2, Info } from 'lucide-react';

interface FeedbackBannerProps {
  feedback: string | null;
  postureMessages?: string[];
  framingMessage?: string | null;
  alignmentIssue?: string | null;
  poseDetected: boolean;
  className?: string;
}

export function FeedbackBanner({ feedback, postureMessages = [], framingMessage, alignmentIssue, poseDetected, className }: FeedbackBannerProps) {
  if (!poseDetected) {
    return (
      <div className={cn("p-4 rounded-xl bg-destructive/10 border border-destructive/30 flex gap-3 items-start", className)}>
        <AlertCircle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
        <div className="flex flex-col gap-1">
          <p className="font-bold text-destructive uppercase tracking-wide text-sm">No Pose Detected</p>
          <p className="text-xs text-destructive/80">Make sure your full body is visible in the camera frame.</p>
        </div>
      </div>
    );
  }

  const issues = [];
  if (framingMessage) issues.push(framingMessage);
  if (alignmentIssue) issues.push(alignmentIssue);
  issues.push(...postureMessages);

  // If there's an issue, show amber/warning
  if (issues.length > 0) {
    return (
      <div className={cn("p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 flex gap-3 items-start", className)}>
        <AlertCircle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
        <div className="flex flex-col gap-1">
          <p className="font-bold text-amber-500 uppercase tracking-wide text-sm">Adjust Form</p>
          <ul className="text-xs text-amber-500/80 list-disc pl-4 space-y-1">
            {issues.map((msg, i) => <li key={i}>{msg}</li>)}
          </ul>
        </div>
      </div>
    );
  }

  // Good state
  return (
    <div className={cn("p-4 rounded-xl bg-primary/10 border border-primary/30 flex gap-3 items-start", className)}>
      <CheckCircle2 className="w-5 h-5 text-primary shrink-0 mt-0.5" />
      <div className="flex flex-col gap-1 w-full">
        <p className="font-bold text-primary uppercase tracking-wide text-sm">Form Looks Good</p>
        {feedback && <p className="text-xs text-primary/80">{feedback}</p>}
      </div>
    </div>
  );
}
