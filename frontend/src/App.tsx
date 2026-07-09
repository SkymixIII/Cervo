// Écran principal « Workbench » (02 §1) — layout 3 zones : (A) source & options,
// (B) lecteur & statut, (C) principe/aide. Historique/verdict/download = hors
// périmètre incrément 2 (endpoints backend absents).

import { useState } from "react";
import { DiagnosticCard } from "./components/DiagnosticCard";
import { ErrorBanner } from "./components/ErrorBanner";
import { FileBrowser } from "./components/FileBrowser";
import { FileInput } from "./components/FileInput";
import { ReferenceFileInput } from "./components/ReferenceFileInput";
import {
  GopModeSelector,
  MediaScopeSelector,
  MethodSelector,
  SliceSelector,
} from "./components/Selectors";
import { StatusPanel } from "./components/StatusPanel";
import { VideoPlayer } from "./components/VideoPlayer";
import { GOP_LABEL, SCOPE_LABEL, SLICE_LABEL } from "./labels";
import { useRecovery } from "./hooks/useRecovery";

export default function App() {
  const r = useRecovery();
  const s = r.state;
  // Navigateur partagé : cible le champ source OU référence (même modale, même endpoint).
  const [browseTarget, setBrowseTarget] = useState<"source" | "reference" | null>(null);

  const running = s.step === "running";
  const analyzed = s.step === "analyzed" || s.step === "done" || s.step === "failed";
  const refBlocking = s.requiresReference && !s.referenceId;
  const refIncompatible = s.compat?.compatible_estimate === false;
  const hasMethods = (s.applicable?.methods.length ?? 0) > 0;
  const canLaunch =
    Boolean(s.sourceId) &&
    Boolean(s.diagnostic?.recoverable) &&
    hasMethods &&
    !refBlocking &&
    !refIncompatible &&
    !running;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">MediaNotFound</div>
        <div className="tagline">Réparer une fois, prévisualiser autant qu'on veut.</div>
      </header>

      <main className="workbench">
        {/* ---- Zone A : Source & options ---- */}
        <section className="zone zone-a">
          <h2 className="zone-title">Source & options</h2>

          <FileInput
            label="Fichier abîmé (chemin monté)"
            value={s.sourcePath}
            onChange={r.setSourcePath}
            onSubmit={r.analyze}
            onBrowse={() => setBrowseTarget("source")}
            busy={s.step === "analyzing"}
            submitLabel="Analyser"
          />

          <FileBrowser
            open={browseTarget !== null}
            onClose={() => setBrowseTarget(null)}
            onChoose={(rel) => {
              const target = browseTarget;
              setBrowseTarget(null);
              if (target === "reference") r.setReferencePath(rel);
              else void r.pickSource(rel);
            }}
          />

          {s.step === "idle" && s.error && <ErrorBanner error={s.error} />}

          {s.diagnostic && <DiagnosticCard d={s.diagnostic} />}

          {s.step === "unrecoverable" && (
            <p className="note note-warn">
              Ce fichier n'est pas récupérable par les méthodes disponibles en l'état.
            </p>
          )}

          {analyzed && s.diagnostic?.recoverable && (
            <>
              <MediaScopeSelector value={s.scope} onChange={r.setScope} diagnostic={s.diagnostic} />
              {s.diagnostic?.container === "sony-rsv" && (
                <GopModeSelector value={s.gopMode} onChange={r.setGopMode} />
              )}
              <SliceSelector
                value={s.slice}
                onChange={(v) => (s.step === "done" ? r.switchSlice(v) : r.setSlice(v))}
              />

              {s.requiresReference && (
                <ReferenceFileInput
                  value={s.referencePath}
                  onChange={r.setReferencePath}
                  onCheck={r.attachReference}
                  onBrowse={() => setBrowseTarget("reference")}
                  busy={s.refBusy}
                  referenceId={s.referenceId}
                  compat={s.compat}
                  error={s.refError}
                />
              )}

              <MethodSelector applicable={s.applicable} value={s.methodId} onChange={r.setMethod} />

              <div className="launch">
                <button className="btn btn-primary" onClick={r.launch} disabled={!canLaunch}>
                  Lancer la récupération
                </button>
                <div className="recap">
                  {SCOPE_LABEL[s.scope]} · {SLICE_LABEL[s.slice]} ·{" "}
                  {s.methodId === "auto" ? "Auto" : s.methodId}
                  {s.diagnostic?.container === "sony-rsv" ? ` · GOP ${GOP_LABEL[s.gopMode]}` : ""}
                  {s.referenceId ? " · réf. fournie" : ""}
                </div>
                {refBlocking && (
                  <div className="note note-warn">Fournissez et vérifiez une référence pour lancer.</div>
                )}
                {refIncompatible && (
                  <div className="note note-warn">Référence incompatible — changez-la.</div>
                )}
              </div>
            </>
          )}
        </section>

        {/* ---- Zone B : Lecteur & statut ---- */}
        <section className="zone zone-b">
          <h2 className="zone-title">Aperçu & progression</h2>

          <StatusPanel live={s.live} onCancel={r.cancel} />

          {s.step === "failed" && s.error && (
            <ErrorBanner error={s.error} onTryAnother={r.tryAnotherMethod} />
          )}

          <VideoPlayer
            previewJobId={s.activePreviewJobId}
            scope={s.scope}
            slice={s.slice}
            sliceJobs={s.sliceJobs}
            onSwitchSlice={r.switchSlice}
            onExtend={r.extend}
            running={running}
          />
        </section>

        {/* ---- Zone C : Principe / aide (historique hors périmètre) ---- */}
        <section className="zone zone-c">
          <h2 className="zone-title">Principe</h2>
          <div className="card help">
            <p>
              <b>La réparation prend le même temps quelle que soit la tranche</b> : elle dépend de la
              taille du fichier, pas de la durée visée. Sur un gros rush 4K elle peut durer{" "}
              <b>plusieurs minutes</b>.
            </p>
            <p>
              Mais elle n'est <b>payée qu'une fois</b> : ensuite, 1 min / 5 min / intégrale et
              l'export sont <b>quasi instantanés</b> (copie de flux). Changer de tranche est gratuit.
            </p>
            <p className="note">
              Changer de <b>méthode</b> relance une réparation (nouvelle clé de cache) — c'est le seul
              point coûteux, et il est signalé.
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}
