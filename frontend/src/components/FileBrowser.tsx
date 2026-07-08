// Navigateur de fichiers (incrément 06) — modale pour choisir un .rsv sur les
// disques montés SOUS la racine média. Navigation confinée côté backend
// (GET /api/browse) : '..' remonte, clic dossier descend, 'Choisir' sur un
// fichier remplit le champ source (chemin relatif à la racine) puis lance
// l'analyse. Lecture seule.

import { useCallback, useEffect, useState } from "react";
import { ApiException, api } from "../api/client";
import type { BrowseEntry, BrowseResult } from "../api/types";

interface Props {
  open: boolean;
  onClose: () => void;
  onChoose: (relpath: string) => void; // chemin relatif à la racine média
}

function humanSize(bytes: number | null): string {
  if (bytes == null) return "";
  const units = ["o", "Ko", "Mo", "Go", "To"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${i === 0 ? v : v.toFixed(1)} ${units[i]}`;
}

// Joint le dossier courant (relatif) et un nom d'entrée.
function join(cwd: string, name: string): string {
  return cwd ? `${cwd}/${name}` : name;
}

export function FileBrowser({ open, onClose, onChoose }: Props) {
  const [data, setData] = useState<BrowseResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const go = useCallback(async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.browse(path);
      setData(res);
    } catch (e) {
      const msg = e instanceof ApiException ? e.message : "Erreur de navigation.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  // À l'ouverture : (re)partir de la racine média.
  useEffect(() => {
    if (open) void go("");
  }, [open, go]);

  // Échap ferme la modale.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const cwd = data?.cwd ?? "";

  const onEntry = (e: BrowseEntry) => {
    const full = join(cwd, e.name);
    if (e.type === "dir") {
      void go(full);
    } else {
      onChoose(full);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="Navigateur de fichiers" onClick={(ev) => ev.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">Parcourir la racine média</div>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Fermer">✕</button>
        </div>

        <div className="browser-path">
          <span className="browser-crumb">/{cwd}</span>
        </div>

        {error && <p className="note note-warn">{error}</p>}

        <ul className="browser-list">
          {data?.parent !== null && data?.parent !== undefined && (
            <li className="browser-entry browser-up" onClick={() => void go(data.parent as string)}>
              <span className="browser-icon">↩</span>
              <span className="browser-name">..</span>
            </li>
          )}
          {data?.entries.map((e) => (
            <li
              key={e.name}
              className={`browser-entry ${e.type === "dir" ? "is-dir" : "is-file"} ${e.is_media ? "is-media" : ""}`}
            >
              <button className="browser-row" onClick={() => onEntry(e)}>
                <span className="browser-icon">{e.type === "dir" ? "📁" : e.is_media ? "🎬" : "📄"}</span>
                <span className="browser-name">{e.name}</span>
                {e.type === "file" && <span className="browser-size">{humanSize(e.size)}</span>}
              </button>
              {e.type === "file" && (
                <button
                  className={`btn ${e.is_media ? "btn-primary" : ""} browser-choose`}
                  onClick={() => onChoose(join(cwd, e.name))}
                >
                  Choisir
                </button>
              )}
            </li>
          ))}
          {data && data.entries.length === 0 && (
            <li className="browser-entry browser-empty">
              <span className="note">Dossier vide.</span>
            </li>
          )}
        </ul>

        <p className="note">
          {loading ? "Chargement…" : "Les fichiers récupérables (.rsv, .mp4, .mov, .mxf, .mts, .m2ts) sont surlignés."}
        </p>
      </div>
    </div>
  );
}
