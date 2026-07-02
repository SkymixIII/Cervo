// Suivi d'un job en temps réel via SSE (/api/jobs/{id}/events), avec repli en
// polling (/api/jobs/{id}) si EventSource échoue (proxy, réseau). Rend une fonction
// d'arrêt. Les libellés distincts repair/extraction/cache-hit sont dérivés côté UI
// à partir de `step` + `repair_cache_hit` (voir stepLabel).

import { api } from "../api/client";
import type { Job, JobEvent } from "../api/types";

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

export interface JobHandlers {
  onProgress: (e: JobEvent) => void;
  onDone: (job: Job) => void;
}

export function trackJob(jobId: string, handlers: JobHandlers): () => void {
  let stopped = false;
  let finished = false;
  let poll: ReturnType<typeof setInterval> | null = null;
  let es: EventSource | null = null;

  const finish = (job: Job) => {
    if (finished) return;
    finished = true;
    handlers.onDone(job);
    cleanup();
  };

  const cleanup = () => {
    if (es) es.close();
    if (poll) clearInterval(poll);
    es = null;
    poll = null;
  };

  const startPolling = () => {
    if (poll || finished || stopped) return;
    poll = setInterval(async () => {
      try {
        const job = await api.getJob(jobId);
        handlers.onProgress({
          job_id: job.job_id,
          status: job.status,
          step: job.progress.step,
          percent: job.progress.percent,
          repair_cache_hit: job.repair_cache_hit,
        });
        if (TERMINAL.has(job.status)) finish(job);
      } catch {
        /* on retente au tick suivant */
      }
    }, 500);
  };

  try {
    es = new EventSource(api.eventsUrl(jobId));
    es.addEventListener("progress", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data) as JobEvent;
      handlers.onProgress(data);
    });
    es.addEventListener("done", (ev) => {
      const job = JSON.parse((ev as MessageEvent).data) as Job;
      finish(job);
    });
    es.onerror = () => {
      // Erreur/coupure SSE avant la fin → bascule en polling.
      if (es) es.close();
      es = null;
      if (!finished && !stopped) startPolling();
    };
  } catch {
    startPolling();
  }

  return () => {
    stopped = true;
    cleanup();
  };
}
