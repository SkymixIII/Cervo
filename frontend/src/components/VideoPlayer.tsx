// Lecteur intégré + SliceTabs (02 B1). La <video>/<audio> tape /api/jobs/{id}/preview
// (le backend supporte les requêtes Range → streaming). Bascule de tranche instantanée
// une fois la source réparée (cache). « Son seul » → placeholder waveform.

import { api } from "../api/client";
import type { MediaScope, SliceKind } from "../api/types";
import { SLICE_LABEL } from "../labels";

interface Props {
  previewJobId: string | null;
  scope: MediaScope;
  slice: SliceKind;
  sliceJobs: Partial<Record<SliceKind, string>>;
  onSwitchSlice: (s: SliceKind) => void;
  onExtend: () => void;
  running: boolean;
}

function Waveform() {
  // Placeholder audio décoratif (02 B1 « son seul »).
  const bars = Array.from({ length: 48 });
  return (
    <div className="waveform" aria-hidden>
      {bars.map((_, i) => (
        <span key={i} style={{ height: `${20 + Math.abs(Math.sin(i * 0.7)) * 70}%` }} />
      ))}
    </div>
  );
}

export function VideoPlayer({ previewJobId, scope, slice, sliceJobs, onSwitchSlice, onExtend, running }: Props) {
  const tabs: SliceKind[] = ["1min", "5min", "full"];
  const src = previewJobId ? api.previewUrl(previewJobId) : null;

  return (
    <div className="card player">
      <div className="slice-tabs">
        {tabs.map((t) => {
          const generated = Boolean(sliceJobs[t]);
          return (
            <button
              key={t}
              className={`tab ${slice === t ? "tab-active" : ""} ${generated ? "" : "tab-dim"}`}
              onClick={() => onSwitchSlice(t)}
              disabled={running}
              title={generated ? "Tranche déjà extraite" : "Extraction rapide (copie sur l'artefact réparé)"}
            >
              {SLICE_LABEL[t]}
              {!generated && <span className="tab-hint"> ⤓</span>}
            </button>
          );
        })}
      </div>

      <div className="player-stage">
        {!src && <div className="player-empty">Aucun aperçu — lancez une récupération.</div>}
        {src && scope === "audio" && (
          <div className="audio-stage">
            <Waveform />
            <audio key={src} className="audio" controls src={src} />
          </div>
        )}
        {src && scope !== "audio" && (
          <video key={src} className="video" controls src={src} />
        )}
      </div>

      {src && slice !== "full" && (
        <div className="player-actions">
          <button className="btn" onClick={onExtend} disabled={running}>
            Récupérer l'intégralité
          </button>
          <span className="note">Réutilise l'artefact déjà réparé — aucune seconde réparation.</span>
        </div>
      )}
    </div>
  );
}
