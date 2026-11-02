#!/bin/bash
# Quality gate local, espejo del pipeline de CI (.github/workflows/ci.yml).
# Es la ÚNICA puerta de calidad local: no usar scripts/lint.sh (eliminado).
# Uso: ./scripts/quality-gate.sh
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

if [[ -z "${PYTHON:-}" ]]; then
    if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
        PYTHON="$PROJECT_ROOT/.venv/bin/python"
    else
        PYTHON="$(command -v python3 || true)"
    fi
fi
if [[ -z "$PYTHON" || ! -x "$PYTHON" ]]; then
    echo "No se encontró un intérprete Python ejecutable." >&2
    exit 1
fi
FAILED=0
TEST_REPORT="$(mktemp "${TMPDIR:-/tmp}/tukul-tests.XXXXXX.xml")"
trap 'rm -f "$TEST_REPORT"' EXIT

paso() { echo ""; echo "== $1 =="; }

paso "ruff check"
if "$PYTHON" -m ruff check .; then
    echo "   ✓ ruff"
else
    FAILED=1
fi

paso "mypy"
if "$PYTHON" -m mypy tukul_core tukul_ui tukul.py; then
    echo "   ✓ mypy"
else
    FAILED=1
fi

paso "instalación aislada"
# El lint y la suite pueden pasar dentro del checkout (conftest.py y el cwd
# resuelven imports que un usuario real no resuelve). Esta comprobación
# instala el paquete de verdad y lo arranca fuera del repositorio.
if PYTHON="$PYTHON" bash "$PROJECT_ROOT/scripts/verify-install.sh"; then
    echo "   ✓ instalación"
else
    FAILED=1
fi

paso "pytest + cobertura"
# Igual que en CI, el gate local exige que Tk sea operativo. Sin esta prueba,
# pytest puede marcar toda la interfaz como `skipped` y producir una señal verde
# engañosa con una cobertura artificialmente baja.
if command -v xvfb-run >/dev/null 2>&1; then
    RUNNER=(xvfb-run -a)
else
    RUNNER=()
fi
if ! "${RUNNER[@]}" "$PYTHON" -c \
        'import tkinter as tk; root = tk.Tk(); root.destroy(); print("Tk operativo")'; then
    echo "   ✗ Tk no pudo abrir una ventana; no se ejecuta la suite gráfica." >&2
    echo "     Revisa Xvfb/DISPLAY antes de interpretar la cobertura." >&2
    FAILED=1
elif "${RUNNER[@]}" "$PYTHON" -m pytest -q -rs \
        --junitxml="$TEST_REPORT" \
        --cov=tukul_core --cov=tukul_ui \
        --cov-report=term-missing --cov-fail-under=70; then
    if "$PYTHON" - "$TEST_REPORT" <<'PY'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
skipped = sum(int(suite.get("skipped", 0)) for suite in suites)
total = sum(int(suite.get("tests", 0)) for suite in suites)
print(f"   {total} pruebas registradas, {skipped} omitidas")
if skipped:
    print("   ✗ Hay pruebas omitidas; la cobertura de interfaz no es válida.", file=sys.stderr)
    raise SystemExit(1)
PY
    then
        echo "   ✓ pytest"
    else
        FAILED=1
    fi
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
