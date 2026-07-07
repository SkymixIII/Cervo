// Résultat de l'analyse structurelle (02 A2). Vocabulaire des badges DÉPENDANT du
// conteneur (MAJ-5) : MP4 (moov/mdat) ≠ MXF (partitions/KLV). Ne suppose jamais
// moov/mdat sur un MXF.

import type { ReactNode } from "react";
import type { Diagnostic } from "../api/types";

function Badge({ ok, warn, children }: { ok?: boolean; warn?: boolean; children: ReactNode }) {
  const cls = ok ? "badge badge-ok" : warn ? "badge badge-warn" : "badge";
  return <span className={cls}>{children}</span>;
}

export function DiagnosticCard({ d }: { d: Diagnostic }) {
  const dur = d.estimated_duration_s != null ? `${Math.round(d.estimated_duration_s)} s` : "inconnue";

  return (
    <div className="card diagnostic">
      <div className="card-title">Diagnostic</div>

      {d.container === "mp4" && (
        <div className="badges">
          <Badge ok={d.atoms.mdat} warn={!d.atoms.mdat}>
            {d.atoms.mdat ? "Données vidéo/audio détectées ✅" : "Données absentes ⚠️"}
          </Badge>
          <Badge ok={d.atoms.moov} warn={!d.atoms.moov}>
            {d.atoms.moov ? "Index de lecture présent ✅" : "Index de lecture manquant ⚠️"}
          </Badge>
        </div>
      )}

      {d.container === "sony-rsv" && (
        <div className="badges">
          <Badge ok>Essence XAVC-I détectée ✅</Badge>
          <Badge warn>Fichier Sony non finalisé (.rsv) ⚠️</Badge>
        </div>
      )}

      {d.container === "mxf" && (
        <div className="badges">
          <Badge ok warn={false}>Essence détectée ✅</Badge>
          <Badge warn>Footer/Index Partition manquante ⚠️</Badge>
        </div>
      )}

      {d.container !== "mp4" && d.container !== "mxf" && d.container !== "sony-rsv" && (
        <div className="badges">
          <Badge warn>Format non reconnu</Badge>
        </div>
      )}

      <dl className="kv">
        <div>
          <dt>Conteneur</dt>
          <dd>{d.container.toUpperCase()}</dd>
        </div>
        <div>
          <dt>Codec présumé</dt>
          <dd>
            {d.codec.family !== "unknown" ? d.codec.family.toUpperCase() : "indéterminé"}
            {d.codec.video ? ` (${d.codec.video})` : ""}
          </dd>
        </div>
        <div>
          <dt>Durée estimée</dt>
          <dd>{dur}</dd>
        </div>
        {d.tracks.length > 0 && (
          <div>
            <dt>Pistes</dt>
            <dd>{d.tracks.map((t) => t.type).join(", ")}</dd>
          </div>
        )}
      </dl>

      {d.container === "sony-rsv" && (
        <p className="note">
          Fichier <b>Sony .rsv</b> (enregistrement XAVC-I interrompu) — récupérable par
          reconstruction de l'essence via une <b>référence saine</b> de la même caméra.
        </p>
      )}

      {d.container === "mxf" && (
        <p className="note note-warn">
          Conteneur MXF détecté — la méthode de réparation adaptée est <b>à venir</b> (hors V1).
        </p>
      )}

      {d.recommendation === "reference_required" && (
        <p className="note note-warn">
          Un fichier de <b>référence sain</b> (même caméra/réglages) est <b>nécessaire</b> :
          sans lui, rien n'est récupérable, pas même le son.
        </p>
      )}
      {!d.recoverable && d.container === "mp4" && (
        <p className="note note-warn">
          Fichier <b>non récupérable</b> en l'état (données manquantes ou index déjà présent).
        </p>
      )}
    </div>
  );
}
