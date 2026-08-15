#!/bin/bash
# Quality gate local, espejo del pipeline de CI (.github/workflows/ci.yml).
# Es la ÚNICA puerta de calidad local: no usar scripts/lint.sh (eliminado).
# Uso: ./scripts/quality-gate.sh
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

PYTHON="${PYTHON:-python3}"
FAILED=0

paso() { echo ""; echo "== $1 =="; }

paso "ruff check"
if "$PYTHON" -m ruff check .; then
    echo "   ✓ ruff"
else
    FAILED=1
fi

paso "mypy"
if "$PYTHON" -m mypy articulador_core articulador_ui articulador.py; then
    echo "   ✓ mypy"
else
    FAILED=1
fi

paso "pytest + cobertura"
# Misma orden que el CI: bajo X si no hay display, para que la interfaz no se
# salte en silencio y la cobertura refleje el código real.
if command -v xvfb-run >/dev/null 2>&1; then
    RUNNER=(xvfb-run -a)
else
    RUNNER=()
fi
if "${RUNNER[@]}" "$PYTHON" -m pytest -q -rs \
        --cov=articulador_core --cov=articulador_ui \
        --cov-report=term-missing --cov-fail-under=70; then
    echo "   ✓ pytest"
else
    FAILED=1
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "✓ QUALITY GATE PASSED"
else
    echo "✗ QUALITY GATE FAILED"
fi
exit "$FAILED"
