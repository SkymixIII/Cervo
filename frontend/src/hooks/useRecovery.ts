// Machine à états du flux de récupération (01 §1). Orchestre : saisie source →
// analyze → applicable → (référence conditionnelle) → options → lancer → SSE →
// preview → bascule de tranche (cache) → extend. Endpoints existants uniquement.

import { useCallback, useRef, useState } from "react";
import { ApiException, api } from "../api/client";
import type {
  ApiError,
  ApplicableResponse,
  CompatCheck,
  Diagnostic,
  Job,
  JobEvent,
  MediaScope,
  SliceKind,
} from "../api/types";
import { trackJob } from "./jobTracker";

export type Step =
  | "idle"
  | "analyzing"
  | "analyzed"
  | "unrecoverable"
  | "running"
  | "done"
  | "failed";

export interface RecoveryState {
  step: Step;
  sourcePath: string;
  sourceId: string | null;
  diagnostic: Diagnostic | null;
  applicable: ApplicableResponse | null;
  requiresReference: boolean;
  referencePath: string;
  referenceId: string | null;
  compat: CompatCheck | null;
  refBusy: boolean;
  refError: string | null;
  scope: MediaScope;
  slice: SliceKind;
  methodId: string; // 'auto' | id concret
  live: JobEvent | null; // job en cours (progression)
  activePreviewJobId: string | null;
  sliceJobs: Partial<Record<SliceKind, string>>;
  error: ApiError | null;
  busy: boolean;
}

const initial: RecoveryState = {
  step: "idle",
  sourcePath: "",
  sourceId: null,
  diagnostic: null,
  applicable: null,
  requiresReference: false,
  referencePath: "",
  referenceId: null,
  compat: null,
  refBusy: false,
  refError: null,
  scope: "both",
  slice: "1min",
  methodId: "auto",
  live: null,
  activePreviewJobId: null,
  sliceJobs: {},
  error: null,
  busy: false,
};

function errOf(e: unknown): ApiError {
  if (e instanceof ApiException) return { code: e.code, message: e.message, hint: e.hint };
  return { code: "CLIENT_ERROR", message: e instanceof Error ? e.message : String(e) };
}

export function useRecovery() {
  const [s, setS] = useState<RecoveryState>(initial);
  const ref = useRef(s);
  ref.current = s;
  const untrack = useRef<null | (() => void)>(null);

  const patch = useCallback((p: Partial<RecoveryState>) => setS((prev) => ({ ...prev, ...p })), []);

  const setSourcePath = useCallback((sourcePath: string) => patch({ sourcePath }), [patch]);
  const setReferencePath = useCallback((referencePath: string) => patch({ referencePath }), [patch]);
  const setScope = useCallback((scope: MediaScope) => patch({ scope }), [patch]);
  const setSlice = useCallback((slice: SliceKind) => patch({ slice }), [patch]);
  const setMethod = useCallback((methodId: string) => patch({ methodId }), [patch]);

  // --- Analyse -------------------------------------------------------------
  const analyze = useCallback(async () => {
    const path = ref.current.sourcePath.trim();
    if (!path) return;
    patch({ busy: true, error: null, step: "analyzing", diagnostic: null, applicable: null,
      sourceId: null, referenceId: null, compat: null, sliceJobs: {}, activePreviewJobId: null });
    try {
      const media = await api.registerMedia(path);
      const sourceId = media.source_id!;
      const diagnostic = await api.analyze(sourceId);
      let applicable: ApplicableResponse | null = null;
      try {
        applicable = await api.applicableMethods(sourceId);
      } catch {
        applicable = { methods: [], requires_reference: null };
      }
      const recoverable = diagnostic.recoverable && applicable.methods.length > 0;
      patch({
        busy: false,
        sourceId,
        diagnostic,
        applicable,
        requiresReference: applicable.requires_reference ?? false,
        step: recoverable ? "analyzed" : "unrecoverable",
      });
    } catch (e) {
      patch({ busy: false, step: "idle", error: errOf(e) });
    }
  }, [patch]);

  // --- Référence -----------------------------------------------------------
  const attachReference = useCallback(async () => {
    const path = ref.current.referencePath.trim();
    const sourceId = ref.current.sourceId;
    if (!path || !sourceId) return;
    patch({ refBusy: true, refError: null, compat: null, referenceId: null });
    try {
      const media = await api.registerReference(path);
      const referenceId = media.reference_id!;
      let compat: CompatCheck | null = null;
      try {
        compat = await api.checkCompat(referenceId, sourceId);
      } catch {
        compat = null;
      }
      patch({ refBusy: false, referenceId, compat });
    } catch (e) {
      patch({ refBusy: false, refError: errOf(e).message });
    }
  }, [patch]);

  // --- Lancement d'un job (repair+slice ou cache-hit) ----------------------
  const runJob = useCallback(
    async (slice: SliceKind) => {
      const st = ref.current;
      if (!st.sourceId) return;
      if (untrack.current) untrack.current();
      patch({
        error: null,
        step: "running",
        slice,
        live: { job_id: "", status: "queued", step: "queued", percent: 0, repair_cache_hit: false },
      });
      try {
        const created = await api.createJob({
          source_id: st.sourceId,
          method_id: st.methodId,
          media_scope: st.scope,
          slice: { kind: slice },
          reference_id: st.referenceId ?? undefined,
        });
        untrack.current = trackJob(created.job_id, {
          onProgress: (e) => patch({ live: e }),
          onDone: (job: Job) => {
            if (job.status === "succeeded") {
              setS((prev) => ({
                ...prev,
                step: "done",
                live: {
                  job_id: job.job_id,
                  status: job.status,
                  step: job.progress.step,
                  percent: 100,
                  repair_cache_hit: job.repair_cache_hit,
                },
                activePreviewJobId: job.job_id,
                sliceJobs: { ...prev.sliceJobs, [slice]: job.job_id },
              }));
            } else {
              patch({
                step: "failed",
                error: job.error ?? { code: "JOB_FAILED", message: "La récupération a échoué." },
              });
            }
          },
        });
      } catch (e) {
        patch({ step: "analyzed", error: errOf(e) });
      }
    },
    [patch],
  );

  const launch = useCallback(() => runJob(ref.current.slice), [runJob]);

  // Bascule de tranche : réutilise le job déjà généré (instantané) sinon en crée un
  // nouveau (cache-hit repair, ~0,2 s).
  const switchSlice = useCallback(
    (slice: SliceKind) => {
      const existing = ref.current.sliceJobs[slice];
      if (existing) {
        patch({ slice, activePreviewJobId: existing, step: "done" });
      } else {
        void runJob(slice);
      }
    },
    [patch, runJob],
  );

  // Étendre à l'intégrale : réutilise l'artefact réparé (aucun second repair).
  const extend = useCallback(async () => {
    const parent = ref.current.activePreviewJobId;
    if (!parent) return;
    if (untrack.current) untrack.current();
    patch({
      error: null,
      step: "running",
      slice: "full",
      live: { job_id: "", status: "queued", step: "queued", percent: 0, repair_cache_hit: true },
    });
    try {
      const created = await api.extendJob(parent);
      untrack.current = trackJob(created.job_id, {
        onProgress: (e) => patch({ live: e }),
        onDone: (job: Job) => {
          if (job.status === "succeeded") {
            setS((prev) => ({
              ...prev,
              step: "done",
              live: {
                job_id: job.job_id,
                status: job.status,
                step: job.progress.step,
                percent: 100,
                repair_cache_hit: job.repair_cache_hit,
              },
              activePreviewJobId: job.job_id,
              sliceJobs: { ...prev.sliceJobs, full: job.job_id },
            }));
          } else {
            patch({ step: "failed", error: job.error ?? { code: "JOB_FAILED", message: "Échec." } });
          }
        },
      });
    } catch (e) {
      patch({ step: "done", error: errOf(e) });
    }
  }, [patch]);

  const cancel = useCallback(async () => {
    const jid = ref.current.live?.job_id;
    if (!jid) return;
    try {
      await api.cancelJob(jid);
    } catch {
      /* déjà terminé côté serveur */
    }
  }, []);

  // Repartir sur une autre méthode après échec/verdict négatif (01 §10).
  const tryAnotherMethod = useCallback(() => {
    if (untrack.current) untrack.current();
    patch({ step: "analyzed", error: null, live: null, methodId: "auto" });
  }, [patch]);

  const reset = useCallback(() => {
    if (untrack.current) untrack.current();
    setS(initial);
  }, []);

  return {
    state: s,
    setSourcePath,
    setReferencePath,
    setScope,
    setSlice,
    setMethod,
    analyze,
    attachReference,
    launch,
    switchSlice,
    extend,
    cancel,
    tryAnotherMethod,
    reset,
  };
}
