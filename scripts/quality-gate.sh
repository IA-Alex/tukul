#!/bin/bash
# Quality Gate - Verificación de Calidad Real
# Reporta TODOS los hallazgos (bloqueantes y no-bloqueantes)
# Uso: ./scripts/quality-gate.sh

set -o pipefail  # Fail if any command in a pipe fails (pero no set -e para permitir que fallos de linting no terminen el script)

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           QUALITY GATE - VERIFICACIÓN REAL                    ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON="${PYTHON:-python3}"
BLACK_TIMEOUT_SECONDS="${BLACK_TIMEOUT_SECONDS:-30}"
FAILED=0

# 1. Python Compilation (SIEMPRE disponible)
echo "1️⃣  Python Compilation:"
if $PYTHON -m py_compile articulador_ui/*.py articulador_core/*.py 2>&1; then
    echo "   ✅ All files compile"
else
    echo "   ❌ COMPILATION FAILED"
    FAILED=1
fi

echo ""

# 2. Unit Tests (SIEMPRE disponible)
echo "2️⃣  Unit Tests:"
if $PYTHON -m unittest discover -s tests -v 2>&1 | tee /tmp/test_output.log | tail -3; then
    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        echo "   ✅ Tests passed"
    else
        echo "   ❌ TESTS FAILED"
        echo "   Error details:"
        grep -E "^(FAIL|ERROR):" /tmp/test_output.log | head -5
        FAILED=1
    fi
else
    echo "   ❌ TESTS FAILED"
    FAILED=1
fi

echo ""

# 3. Ruff (si está instalado)
echo "3️⃣  Ruff Linting:"
if command -v ruff &> /dev/null; then
    set +e
    ruff_output=$(ruff check articulador.py articulador_core articulador_ui scripts tests 2>&1)
    ruff_exit=$?
    set -o pipefail

    if [ $ruff_exit -eq 0 ]; then
        echo "   ✅ Ruff passed (0 errors)"
    else
        error_line=$(echo "$ruff_output" | grep "found\|Found" | tail -1)
        echo "   ❌ $error_line"
        FAILED=1
    fi
else
    echo "   ⚠️  ruff not installed (optional for CI)"
    echo "      Install with: pip install ruff"
fi

echo ""

# 4. MyPy (si está instalado)
echo "4️⃣  Type Checking (mypy):"
if command -v mypy &> /dev/null; then
    set +e
    mypy_output=$(mypy articulador.py articulador_core articulador_ui --ignore-missing-imports 2>&1)
    mypy_exit=$?
    set -o pipefail

    if [ $mypy_exit -eq 0 ]; then
        echo "   ✅ mypy passed (0 errors)"
    else
        echo "$mypy_output" | tail -1
        echo "   ❌ MyPy check failed"
        FAILED=1
    fi
else
    echo "   ⚠️  mypy not installed (optional for CI)"
    echo "      Install with: pip install mypy"
fi

echo ""

# 5. Black (non-blocking; bounded to keep the gate responsive)
echo "5️⃣  Code Formatting (black):"
if command -v black &> /dev/null; then
    black_output=$(timeout "$BLACK_TIMEOUT_SECONDS" black --check articulador_ui articulador_core 2>&1)
    black_exit=$?
    if [ $black_exit -eq 0 ]; then
        echo "   ✅ black check passed"
    elif [ $black_exit -eq 124 ]; then
        echo "   ⚠️  Black timed out after ${BLACK_TIMEOUT_SECONDS}s (non-blocking)"
    else
        echo "$black_output" | tail -1
        echo "   ℹ️  Black formatting is non-blocking"
    fi
else
    echo "   ⚠️  black not installed (optional for CI)"
fi

echo ""

# 6. isort (non-blocking)
echo "6️⃣  Import Sorting (isort):"
if command -v isort &> /dev/null; then
    isort_output=$(isort --check-only articulador_ui articulador_core 2>&1)
    isort_exit=$?
    if [ $isort_exit -eq 0 ]; then
        echo "   ✅ isort check passed"
    else
        echo "$isort_output" | head -3
        echo "   ℹ️  isort formatting is non-blocking"
    fi
else
    echo "   ⚠️  isort not installed (optional for CI)"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"

if [ $FAILED -eq 0 ]; then
    echo "✅ QUALITY GATE PASSED"
    echo "╚════════════════════════════════════════════════════════════════╝"
    exit 0
else
    echo "❌ QUALITY GATE FAILED"
    echo "╚════════════════════════════════════════════════════════════════╝"
    exit 1
fi
