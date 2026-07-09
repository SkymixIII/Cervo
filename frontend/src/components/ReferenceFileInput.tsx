// Fichier de référence (02 A3) — affiché CONDITIONNELLEMENT selon
// methods/applicable.requires_reference (MAJ-9). Badge de compatibilité présenté
// comme ESTIMATION (MAJ-6), jamais un ✓ garanti.

import type { CompatCheck } from "../api/types";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onCheck: () => void;
  onBrowse?: () => void; // ouvre le navigateur de fichiers (même modale que la source)
  busy: boolean;
  referenceId: string | null;
  compat: CompatCheck | null;
  error: string | null;
}

export function ReferenceFileInput({ value, onChange, onCheck, onBrowse, busy, referenceId, compat, error }: Props) {
  return (
    <div className="field field-ref">
      <label className="field-label">
        Fichier de référence sain <span className="req">requis</span>
      </label>
      <div className="row">
        <input
          className="input"
          type="text"
          value={value}
          placeholder="/media/clip_sain_meme_camera.mp4"
          onChange={(e) => onChange(e.target.value)}
          disabled={busy}
        />
        {onBrowse && (
          <button className="btn" onClick={onBrowse} disabled={busy} title="Parcourir les disques montés">
            Parcourir…
          </button>
        )}
        <button className="btn" onClick={onCheck} disabled={busy || !value.trim()}>
          {busy ? "…" : "Vérifier"}
        </button>
      </div>

      <p className="note">
        Cherchez une vidéo <b>saine</b> de la <b>même carte / dossier / caméra et réglages</b>
        (codec, résolution, framerate). Pas besoin de la même durée.
      </p>

      {error && <p className="note note-warn">Référence : {error}</p>}

      {referenceId && compat && (
        <p className={`badge ${compat.compatible_estimate ? "badge-ok" : "badge-warn"}`}>
          {compat.compatible_estimate
            ? `≈ probablement compatible (${compat.confidence_label.toLowerCase()})`
            : "✗ incompatible (codec/conteneur différent)"}
          {compat.note ? ` — ${compat.note}` : ""}
        </p>
      )}
      {referenceId && !compat && (
        <p className="note">Référence enregistrée (compatibilité non évaluable pour l'instant).</p>
      )}
    </div>
  );
}
