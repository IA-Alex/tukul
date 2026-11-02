#!/bin/bash
# Verificación de integridad del repositorio.
#
# Existe porque el quality gate (ruff/mypy/pytest/cobertura) puede estar en
# verde y el proyecto seguir sin poder instalarse ni ejecutarse fuera de un
# checkout. Eso ya ocurrió: paquetes movidos sin actualizar imports, con la
# suite "pasando" por el `conftest.py` que mete la raíz en sys.path.
#
# Comprueba, en orden:
#   1. Que el árbol de git no tenga borrados/cambios de paquetes sin commitear.
#   2. Que el paquete se construya y arranque en un entorno AISLADO (sin
#      conftest.py, sin sys.path manipulado, sin .venv del repo).
#   3. Que el lockfile respete los hashes (lo que hace CI).
#
# Uso: ./scripts/verify-install.sh
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
    for candidato in "$PROJECT_ROOT/.venv/bin/python" python3 python; do
        if command -v "$candidato" >/dev/null 2>&1; then PYTHON="$candidato"; break; fi
    done
fi
if [[ -z "$PYTHON" ]]; then
    echo "No se encontró un intérprete Python ejecutable." >&2
    exit 1
fi

FAILED=0
TMP="$(mktemp -d "${TMPDIR:-/tmp}/tukul-verify.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

paso() { echo ""; echo "== $1 =="; }

paso "estado de git: paquetes sin commitear"
# Borrados o renombrados bajo un paquete = el árbol no representa una versión.
CAMBIOS_PAQUETES="$(git status --porcelain -- tukul_core tukul_ui tukul.py)"
if [[ -z "$CAMBIOS_PAQUETES" ]]; then
    echo "   ✓ árbol limpio para los paquetes del producto"
else
    echo "$CAMBIOS_PAQUETES" | sed 's/^/   ! /'
    # Solo es error si hay borrados en tukul_core (el fallo que ya se vio);
    # modificaciones normales de trabajo no bloquean.
    if echo "$CAMBIOS_PAQUETES" | grep -qE "^ ?D +tukul_core/"; then
        echo "   ✗ Faltan módulos de tukul_core (¿movidos sin actualizar imports?)" >&2
        FAILED=1
    fi
fi

paso "instalación aislada (sin conftest, sin sys.path, sin .venv)"
VENV="$TMP/venv"
if "$PYTHON" -m venv "$VENV" >/dev/null 2>&1; then
    if "$VENV/bin/python" -m pip install -q "$PROJECT_ROOT" 2>"$TMP/install.log"; then
        # Ejecutar desde un directorio ajeno al checkout: si depende de la
        # raíz del repo para importar, esto falla.
        if (cd "$TMP" && "$VENV/bin/python" -c "import tukul_core, tukul_ui; print('   ✓ import OK desde', tukul_core.__file__)"); then
            if (cd "$TMP" && "$VENV/bin/tukul" --health >/dev/null 2>&1); then
                echo "   ✓ comando tukul --health OK"
            else
                echo "   ✗ el comando instalado no arranca con --health" >&2
                FAILED=1
            fi
        else
            echo "   ✗ el paquete instalado no importa fuera del checkout" >&2
            FAILED=1
        fi
    else
        echo "   ✗ pip install falló:" >&2
        sed 's/^/     /' "$TMP/install.log" | tail -15 >&2
        FAILED=1
    fi
else
    echo "   ! no se pudo crear un venv temporal; se omite esta comprobación"
fi

paso "lockfile con hashes"
if [[ -f requirements-dev.lock ]]; then
    if "$PYTHON" -m pip install -q --require-hashes -r requirements-dev.lock --dry-run >"$TMP/lock.log" 2>&1; then
        echo "   ✓ requirements-dev.lock resuelve con hashes"
    else
        echo "   ✗ el lockfile no resuelve (dependencias o hashes desactualizados):" >&2
        tail -10 "$TMP/lock.log" | sed 's/^/     /' >&2
        FAILED=1
    fi
else
    echo "   ! no hay requirements-dev.lock"
fi

echo ""
if [[ "$FAILED" -eq 0 ]]; then
    echo "✓ VERIFY INSTALL PASSED"
else
    echo "✗ VERIFY INSTALL FAILED"
fi
exit "$FAILED"
