// Erreur honnête orientée-action (01 §8b) : message + hint contractuel + affordance
// « essayer une autre méthode ».

import type { ApiError } from "../api/types";

export function ErrorBanner({ error, onTryAnother }: { error: ApiError; onTryAnother?: () => void }) {
  return (
    <div className="card error-banner">
      <div className="error-title">⚠ {error.message}</div>
      {error.hint && <div className="error-hint">{error.hint}</div>}
      <div className="error-code">Code : {error.code}</div>
      {onTryAnother && (
        <button className="btn" onClick={onTryAnother}>
          Essayer une autre méthode
        </button>
      )}
    </div>
  );
}
