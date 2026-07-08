// Client API typé. Toutes les réponses passent par l'enveloppe { data, error, meta }.
// En cas d'erreur (HTTP non-2xx OU error != null), on lève `ApiException` porteuse
// du code/message/hint contractuels (le hint alimente l'UX orientée-action).

import type {
  ApiError,
  ApplicableResponse,
  BrowseResult,
  CompatCheck,
  Diagnostic,
  Envelope,
  GopMode,
  Job,
  MediaScope,
  MethodInfo,
  RegisteredMedia,
  SliceKind,
} from "./types";

export class ApiException extends Error {
  code: string;
  hint?: string | null;
  constructor(err: ApiError) {
    super(err.message);
    this.code = err.code;
    this.hint = err.hint;
    this.name = "ApiException";
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiException({
      code: "NETWORK_ERROR",
      message: "Impossible de joindre le serveur.",
      hint: "Le backend (uvicorn) est-il démarré sur le port 8000 ?",
    });
  }
  let body: Envelope<T> | null = null;
  try {
    body = (await res.json()) as Envelope<T>;
  } catch {
    /* réponse non-JSON (ex. 500 brut) */
  }
  if (!res.ok || (body && body.error)) {
    throw new ApiException(
      body?.error ?? { code: `HTTP_${res.status}`, message: res.statusText || "Erreur serveur." },
    );
  }
  return (body as Envelope<T>).data as T;
}

// ---- Endpoints -------------------------------------------------------------

export const api = {
  registerMedia: (path: string) =>
    call<RegisteredMedia>("/api/media", { method: "POST", body: JSON.stringify({ path }) }),

  browse: (path: string) => call<BrowseResult>(`/api/browse?path=${encodeURIComponent(path)}`),

  analyze: (sourceId: string) =>
    call<Diagnostic>(`/api/media/${sourceId}/analyze`, { method: "POST" }),

  getDiagnostic: (sourceId: string) => call<Diagnostic>(`/api/media/${sourceId}/diagnostic`),

  applicableMethods: (sourceId: string) =>
    call<ApplicableResponse>(`/api/methods/applicable?source=${encodeURIComponent(sourceId)}`),

  listMethods: () => call<MethodInfo[]>("/api/methods"),

  registerReference: (path: string) =>
    call<RegisteredMedia>("/api/references", { method: "POST", body: JSON.stringify({ path }) }),

  checkCompat: (referenceId: string, sourceId: string) =>
    call<CompatCheck>(
      `/api/references/${referenceId}/check?source=${encodeURIComponent(sourceId)}`,
      { method: "POST" },
    ),

  createJob: (body: {
    source_id: string;
    method_id: string;
    media_scope: MediaScope;
    slice: { kind: SliceKind };
    reference_id?: string | null;
    gop_mode?: GopMode;
  }) => call<{ job_id: string; status: string }>("/api/jobs", { method: "POST", body: JSON.stringify(body) }),

  getJob: (jobId: string) => call<Job>(`/api/jobs/${jobId}`),

  cancelJob: (jobId: string) =>
    call<{ job_id: string; canceling: boolean }>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),

  extendJob: (jobId: string) =>
    call<{ job_id: string; status: string; parent_job_id: string }>(`/api/jobs/${jobId}/extend`, {
      method: "POST",
    }),

  previewUrl: (jobId: string) => `/api/jobs/${jobId}/preview`,
  eventsUrl: (jobId: string) => `/api/jobs/${jobId}/events`,
};
