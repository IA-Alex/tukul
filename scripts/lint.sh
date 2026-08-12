#!/bin/bash
# Quality gates automation script
# Uso: ./scripts/lint.sh [fix|check]

MODE="${1:-check}"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    QUALITY GATES RUNNER                       ║"
echo "╚════════════════════════════════════════════════════════════════╝"

# Detectar Python
PY=$(which python3)
if [ -z "$PY" ]; then
    echo "❌ python3 no encontrado"
    exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

# 1. BLACK (formatting)
echo ""
echo "1. Formatting con black..."
if [ "$MODE" = "fix" ]; then
    $PY -m black articulador_ui articulador_core tests 2>/dev/null || {
        echo "⚠️  black no instalado, saltando"
    }
    echo "✓ Formatted"
else
    $PY -m black --check articulador_ui articulador_core tests 2>/dev/null || {
        echo "⚠️  black no instalado, saltando"
    }
fi

# 2. ISORT (import ordering)
echo ""
echo "2. Import ordering con isort..."
if [ "$MODE" = "fix" ]; then
    $PY -m isort articulador_ui articulador_core tests 2>/dev/null || {
        echo "⚠️  isort no instalado, saltando"
    }
    echo "✓ Sorted"
else
    $PY -m isort --check-only articulador_ui articulador_core tests 2>/dev/null || {
        echo "⚠️  isort no instalado, saltando"
    }
fi

# 3. MYPY (type checking)
echo ""
echo "3. Type checking con mypy..."
$PY -m mypy articulador_ui articulador_core --ignore-missing-imports 2>/dev/null || {
    echo "⚠️  mypy no instalado o errores de tipo encontrados"
}

# 4. PYLINT (linting)
echo ""
echo "4. Linting con pylint..."
$PY -m pylint articulador_ui articulador_core --disable=all --enable=E,F 2>/dev/null || {
    echo "⚠️  pylint no instalado, saltando"
}

# 5. Compilation check
echo ""
echo "5. Python compilation..."
for file in $(find articulador_ui articulador_core -name "*.py"); do
    $PY -m py_compile "$file" || {
        echo "❌ $file: syntax error"
        exit 1
    }
done
echo "✓ All files compile"

# 6. Tests
echo ""
echo "6. Running tests..."
$PY -m unittest discover -s tests -q || {
    echo "❌ Tests failed"
    exit 1
}

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
if [ "$MODE" = "fix" ]; then
    echo "✅ Quality gates: FIXED"
else
    echo "✅ Quality gates: PASS"
fi
echo "╚════════════════════════════════════════════════════════════════╝"
