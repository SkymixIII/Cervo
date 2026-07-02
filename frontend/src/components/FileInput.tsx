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
}

export function FileInput({ label, value, onChange, onSubmit, busy, disabled, submitLabel, placeholder }: Props) {
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
        <button className="btn" onClick={onSubmit} disabled={busy || disabled || !value.trim()}>
          {busy ? "…" : submitLabel}
        </button>
      </div>
    </div>
  );
}
