// Types du contrat API (backend incrément 1). Enveloppe commune { data, error, meta }.

export interface ApiError {
  code: string;
  message: string;
  hint?: string | null;
}

export interface Envelope<T> {
  data: T | null;
  error: ApiError | null;
  meta: { request_id: string; timestamp: string };
}

export interface Track {
  type: string; // 'video' | 'audio'
  codec?: string | null;
  width?: number | null;
  height?: number | null;
}

export interface Diagnostic {
  container: string; // 'mp4' | 'mxf' | 'unknown'
  atoms: { ftyp: boolean; mdat: boolean; moov: boolean };
  brand: string | null;
  codec: { family: string; video: string | null; audio: string | null };
  estimated_duration_s: number | null;
  tracks: Track[];
  recoverable: boolean;
  recommendation: string | null; // 'reference_required' | null
  probe_readable: boolean;
}

export interface RegisteredMedia {
  source_id?: string;
  reference_id?: string;
  size: number;
  cache_hash: string;
}

export interface ApplicableMethod {
  id: string;
  display_name: string;
  requires_reference: boolean;
  confidence: number; // 0..1 interne
  confidence_label: string; // NULLE | BASSE | MOYENNE | HAUTE
  reason: string;
}

export interface ApplicableResponse {
  methods: ApplicableMethod[];
  requires_reference: boolean | null;
}

export interface MethodInfo {
  id: string;
  display_name: string;
  requires_reference: boolean;
  capabilities: Record<string, unknown>;
}

export interface CompatCheck {
  compatible_estimate: boolean;
  confidence: number;
  confidence_label: string;
  note: string;
  reference_codec: string | null;
  source_codec: string | null;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";
export type MediaScope = "audio" | "video" | "both";
export type SliceKind = "1min" | "5min" | "full";

export interface Job {
  job_id: string;
  status: JobStatus;
  method_id: string;
  media_scope: string;
  slice_kind: string;
  progress: { step: string | null; percent: number };
  repair_cache_hit: boolean;
  parent_job_id: string | null;
  error?: ApiError;
  result?: { has_preview: boolean };
}

// Événement SSE (event: progress) — sous-ensemble du Job.
export interface JobEvent {
  job_id: string;
  status: JobStatus;
  step: string | null;
  percent: number;
  repair_cache_hit: boolean;
}
