// Saisie d'un chemin de fichier (source ou référence) — chemin monté dans le
// conteneur (01 §1). Champ + bouton d'action.

interface Props {
  label: string;
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy?: boolean;
  disabled?: boolean;
  submitLabel: string;
  placeholder?: string;
  onBrowse?: () => void; // ouvre le navigateur de fichiers (incrément 06)
}

export function FileInput({ label, value, onChange, onSubmit, busy, disabled, submitLabel, placeholder, onBrowse }: Props) {
  return (
    <div className="field">
      <label className="field-label">{label}</label>
      <div className="row">
        <input
          className="input"
          type="text"
          value={value}
          placeholder={placeholder ?? "/media/rush_corrompu.rsv"}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !busy && !disabled) onSubmit();
          }}
          disabled={busy}
        />
        {onBrowse && (
          <button className="btn" onClick={onBrowse} disabled={busy} title="Parcourir les disques montés">
            Parcourir…
          </button>
        )}
        <button className="btn" onClick={onSubmit} disabled={busy || disabled || !value.trim()}>
          {busy ? "…" : submitLabel}
        </button>
      </div>
    </div>
  );
}
