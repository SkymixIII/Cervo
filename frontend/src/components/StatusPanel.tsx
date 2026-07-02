// Suivi du job (02 B2) : barre de progression + libellé d'étape lisible, avec
// distinction visuelle repair (long) vs extraction (instantané) vs cache-hit.

import type { JobEvent } from "../api/types";
import { stepLabel, stepPhase } from "../labels";

interface Props {
  live: JobEvent | null;
  onCancel: () => void;
}

export function StatusPanel({ live, onCancel }: Props) {
  if (!live) return null;
  const phase = stepPhase(live.step);
  const running = live.status === "running" || live.status === "queued";
  const label = stepLabel(live.step, live.repair_cache_hit);

  return (
    <div className={`card status status-${phase} status-${live.status}`}>
      <div className="status-head">
        <span className="status-label">{label}</span>
        {running && (
          <button className="btn btn-ghost" onClick={onCancel}>
            Annuler
          </button>
        )}
      </div>

      <div className="progress">
        <div
          className={`progress-bar ${phase === "repair" ? "progress-repair" : "progress-extract"}`}
          style={{ width: `${Math.max(4, live.percent)}%` }}
        />
      </div>

      <div className="status-meta">
        {phase === "repair" && running && (
          <span>Étape la plus longue — payée une seule fois, puis mise en cache.</span>
        )}
        {phase === "extract" && running && <span>Copie de flux — quasi instantané.</span>}
        {live.status === "succeeded" && live.repair_cache_hit && (
          <span className="ok">Source déjà réparée : aucune re-réparation.</span>
        )}
      </div>
    </div>
  );
}
