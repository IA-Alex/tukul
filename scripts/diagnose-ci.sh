#!/bin/bash
# Diagnóstico de un run de CI rojo: ¿es un fallo de código o un bloqueo de
# cuenta (facturación de Actions)?
#
# Motivo: los runs de este repositorio salían `failure` en ~2-4 s con
# `steps: []` y `runner_name` vacío. Ese patrón NO es un fallo del workflow ni
# del código: es la cuenta sin runners de Actions (facturación). Este script
# clasifica el último run para no confundir ambos casos. Ver
# `docs/audit/hallazgos-abiertos-2026-11-04.md#h0--ci-no-ejecuta-ningún-paso`.
#
# Uso: ./scripts/diagnose-ci.sh [run-id]
# Requiere: gh (GitHub CLI) autenticado y acceso al repositorio.
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

if ! command -v gh >/dev/null 2>&1; then
    echo "Falta 'gh' (GitHub CLI). Instálalo o consulta el run en la web." >&2
    exit 2
fi

RUN_ID="${1:-}"
if [[ -z "$RUN_ID" ]]; then
    RUN_ID="$(gh run list --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)"
fi
if [[ -z "$RUN_ID" ]]; then
    echo "No se pudo obtener el último run. Pasa un run-id: ./scripts/diagnose-ci.sh <id>" >&2
    exit 2
fi

echo "Run: $RUN_ID"
gh run view "$RUN_ID" 2>/dev/null | head -3 || true

jobs="$(gh api "repos/{owner}/{repo}/actions/runs/${RUN_ID}/jobs" 2>/dev/null || true)"
if [[ -z "$jobs" ]]; then
    echo "No se pudieron leer los jobs (¿sin permisos o run-id inválido?)." >&2
    exit 2
fi

# Clasificación: si TODOS los jobs tienen steps=0 y runner vacío, es el bloqueo
# de cuenta; si alguno ejecutó pasos, es un fallo real de código/entorno.
python3 - "$jobs" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
jobs = data.get("jobs", [])
if not jobs:
    print("Sin jobs en el run.")
    sys.exit(2)

sin_runner = [j for j in jobs if not j.get("runner_name") and not j.get("steps")]
con_pasos = [j for j in jobs if j.get("steps")]

facturacion = any(
    "payments have failed" in (a.get("message", "") or "")
    or "spending limit" in (a.get("message", "") or "")
    for j in jobs
    for a in (j.get("annotations") or [])
)

for j in jobs:
    print(f"  {j.get('name')}: conclusion={j.get('conclusion')} "
          f"runner={j.get('runner_name')!r} steps={len(j.get('steps') or [])}")

if facturacion or (sin_runner and not con_pasos):
    print("\nDIAGNÓSTICO: bloqueo de CUENTA (facturación de Actions), no de código.")
    print("  Ningún job obtuvo runner (steps=0, runner vacío).")
    print("  Acción: Settings → Billing & plans de la cuenta del repositorio")
    print("          (método de pago / límite de gasto de Actions).")
    print("  Alternativa: runner self-hosted o repositorio público.")
    print("  Detalle: docs/audit/hallazgos-abiertos-2026-11-04.md (H0).")
    sys.exit(1)

print("\nDIAGNÓSTICO: el run SÍ ejecutó pasos; es un fallo de código/entorno.")
print("  Revisa el log del job que falló: gh run view --log-failed")
sys.exit(0)
PY
