// Libellés UX honnêtes (01 §0/§7) — libellés DISTINCTS repair (long) vs extraction
// (instantanée) vs cache-hit ("source déjà réparée").

export type Phase = "repair" | "extract" | "other";

export function stepPhase(step: string | null): Phase {
  switch (step) {
    case "repair":
    case "repair-attached":
      return "repair";
    case "slice-copy":
    case "validate":
    case "publish":
      return "extract";
    default:
      return "other";
  }
}

export function stepLabel(step: string | null, repairCacheHit: boolean): string {
  switch (step) {
    case "queued":
      return "En file d'attente…";
    case "probe":
      return "Analyse de la structure du fichier…";
    case "repair":
      return "Réparation en cours (une seule fois — peut durer plusieurs minutes sur un gros rush)…";
    case "repair-attached":
      return "Une réparation de ce fichier est déjà en cours — en attente…";
    case "slice-copy":
      return "Extraction de la tranche (copie de flux, quasi instantané)…";
    case "validate":
      return "Vérification de la tranche…";
    case "publish":
      return "Finalisation…";
    case "done":
      return repairCacheHit
        ? "Terminé — source déjà réparée, tranche extraite instantanément."
        : "Terminé — fichier réparé et tranche extraite.";
    case "canceled":
      return "Annulé.";
    case "error":
    case "crashed":
    case "orphaned":
      return "Échec.";
    default:
      return step ?? "…";
  }
}

export const SCOPE_LABEL: Record<string, string> = {
  audio: "Son seul",
  video: "Vidéo seule",
  both: "Les deux",
};

export const SLICE_LABEL: Record<string, string> = {
  "1min": "1 min",
  "5min": "5 min",
  full: "Intégrale",
};

export const GOP_LABEL: Record<string, string> = {
  auto: "Auto",
  "long-gop": "Long-GOP",
  "all-intra": "All-Intra",
};
