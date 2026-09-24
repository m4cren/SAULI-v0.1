import { LoaderCircle, SquareTerminal } from "lucide-react";

export interface PipelineLogEntry {
  id: number;
  stage: string;
  message: string;
}

export function formatProcessDuration(elapsedMs: number) {
  const seconds = Math.max(0, elapsedMs) / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${(seconds % 60).toFixed(1)}s`;
}

export function ProgressIndicator({ logs, active = false, elapsedMs = 0 }: {
  logs: PipelineLogEntry[];
  active?: boolean;
  elapsedMs?: number;
}) {
  const duration = formatProcessDuration(elapsedMs);
  return <section className="pipeline-console" aria-label="Processing log">
    <div className="pipeline-console-heading"><span><SquareTerminal size={15} /> Progress</span><span className={active ? "pipeline-live" : ""}>{active && <LoaderCircle size={12} className="spin" />}{active ? `Elapsed ${duration}` : logs.length ? `Total ${duration}` : "Ready"}</span></div>
    <ol role="log" aria-live="polite">
      {logs.length ? logs.map((entry) => <li key={entry.id}><span>{entry.message}</span></li>) : <li className="pipeline-empty"><span>Progress updates will appear here after submission.</span></li>}
    </ol>
  </section>;
}
