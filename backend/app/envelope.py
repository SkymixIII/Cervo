"""Enveloppe de réponse commune (03 §6).

Toutes les réponses JSON suivent `{ data, error, meta }`. `error` est `null`
en succès, `data` est `null` en erreur. `hint` est contractuel (oriente l'UX).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi.responses import JSONResponse


def _meta() -> dict:
    return {
        "request_id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def ok(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"data": data, "error": None, "meta": _meta()},
    )


def err(code: str, message: str, hint: str | None = None, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "error": {"code": code, "message": message, "hint": hint},
            "meta": _meta(),
        },
    )


# Codes d'erreur normalisés (03 §6).
FILE_NOT_FOUND = "FILE_NOT_FOUND"
PATH_FORBIDDEN = "PATH_FORBIDDEN"
UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
MDAT_MISSING = "MDAT_MISSING"
CODEC_UNSUPPORTED_BY_METHOD = "CODEC_UNSUPPORTED_BY_METHOD"
REFERENCE_REQUIRED = "REFERENCE_REQUIRED"
REFERENCE_INCOMPATIBLE = "REFERENCE_INCOMPATIBLE"
NOT_FOUND = "NOT_FOUND"
JOB_FAILED = "JOB_FAILED"
CANCELED = "CANCELED"
VALIDATION_ERROR = "VALIDATION_ERROR"
