"""Couche de présentation de `confidence` (MAJ-14, tranché arbitrage #2).

Le contrat `RecoveryMethod.can_handle()` retourne un **float 0..1 interne** ; c'est
ICI (présentation) qu'on le mappe vers un label qualitatif pour l'UI et le tableau
de décision. Le moteur ne raisonne jamais sur le label.
"""
from __future__ import annotations


def label(confidence: float) -> str:
    if confidence <= 0.0:
        return "NULLE"
    if confidence < 0.5:
        return "BASSE"
    if confidence < 0.8:
        return "MOYENNE"
    return "HAUTE"
