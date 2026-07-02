// Segmented controls des options (02 A3) : périmètre média, tranche, méthode.

import type { ApplicableResponse, Diagnostic, MediaScope, SliceKind } from "../api/types";
import { SCOPE_LABEL, SLICE_LABEL } from "../labels";

// --- Périmètre média : Son / Vidéo / Les deux -------------------------------
export function MediaScopeSelector({
  value,
  onChange,
  diagnostic,
}: {
  value: MediaScope;
  onChange: (v: MediaScope) => void;
  diagnostic: Diagnostic | null;
}) {
  const readable = diagnostic?.probe_readable ?? false;
  const hasAudio = (diagnostic?.tracks ?? []).some((t) => t.type === "audio");
  const hasVideo = (diagnostic?.tracks ?? []).some((t) => t.type === "video");
  // On ne grise que si on SAIT positivement qu'une piste est absente.
  const disabled: Record<MediaScope, boolean> = {
    audio: readable && !hasAudio,
    video: readable && !hasVideo,
    both: readable && (!hasAudio || !hasVideo),
  };
  const opts: MediaScope[] = ["audio", "video", "both"];
  return (
    <div className="field">
      <label className="field-label">Périmètre média</label>
      <div className="segmented">
        {opts.map((o) => (
          <button
            key={o}
            className={`seg ${value === o ? "seg-active" : ""}`}
            disabled={disabled[o]}
            title={disabled[o] ? "Piste non détectée dans ce fichier" : undefined}
            onClick={() => onChange(o)}
          >
            {SCOPE_LABEL[o]}
          </button>
        ))}
      </div>
    </div>
  );
}

// --- Tranche : 1 min / 5 min / Intégrale ------------------------------------
export function SliceSelector({
  value,
  onChange,
}: {
  value: SliceKind;
  onChange: (v: SliceKind) => void;
}) {
  const opts: SliceKind[] = ["1min", "5min", "full"];
  return (
    <div className="field">
      <label className="field-label">Tranche à contrôler</label>
      <div className="segmented">
        {opts.map((o) => (
          <button
            key={o}
            className={`seg ${value === o ? "seg-active" : ""}`}
            onClick={() => onChange(o)}
          >
            {SLICE_LABEL[o]}
          </button>
        ))}
      </div>
      <p className="note">
        La réparation prend le <b>même temps</b> quelle que soit la tranche. Choisir 1 min sert juste
        à <b>contrôler le rendu vite</b> avant d'exposer l'intégrale — l'affichage, lui, est instantané.
      </p>
    </div>
  );
}

// --- Méthode : Auto (recommandée) + méthodes applicables (mode avancé) ------
export function MethodSelector({
  applicable,
  value,
  onChange,
}: {
  applicable: ApplicableResponse | null;
  value: string;
  onChange: (v: string) => void;
}) {
  const methods = applicable?.methods ?? [];
  const top = methods[0];
  return (
    <div className="field">
      <label className="field-label">Méthode de récupération</label>
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="auto">
          Auto (recommandée{top ? ` — ${top.display_name}` : ""})
        </option>
        {methods.map((m) => (
          <option key={m.id} value={m.id}>
            {m.display_name} — confiance {m.confidence_label.toLowerCase()}
          </option>
        ))}
      </select>
      {value === "auto" && top && <p className="note">{top.reason}</p>}
      {value !== "auto" &&
        methods
          .filter((m) => m.id === value)
          .map((m) => (
            <p className="note" key={m.id}>
              {m.reason} {m.requires_reference ? "— référence requise." : ""}
            </p>
          ))}
      {methods.length === 0 && (
        <p className="note note-warn">Aucune méthode applicable à ce fichier pour l'instant.</p>
      )}
    </div>
  );
}
