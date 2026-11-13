#!/bin/bash
# Verificación del contrato C1 (firma keyless) sobre un release REAL publicado.
#
# No firma: descarga el binario y su bundle de la Release indicada y reproduce
# exactamente la verificación que documenta `docs/RELEASE.md`, con la misma
# identidad de workflow y el mismo emisor OIDC que usa el CI. Sirve para
# (a) probar que el procedimiento del documento lo puede ejecutar un tercero y
# (b) fallar en rojo cuando la release no trae firma.
#
# Requiere: `gh` autenticado y `cosign` (https://docs.sigstore.dev/cosign/).
# Uso: scripts/verify-signature.sh [TAG] [REPO]
set -euo pipefail

TAG="${1:-v0.5.2}"
REPO="${2:-IA-Alex/tukul}"
DESTINO="$(mktemp -d)"
trap 'rm -rf "$DESTINO"' EXIT

command -v cosign >/dev/null 2>&1 || {
    echo "::error::Falta 'cosign'. Instálalo antes de verificar la firma." >&2
    exit 2
}

echo "== Descarga $TAG de $REPO =="
gh release download "$TAG" -R "$REPO" -p 'tukul-*' -D "$DESTINO"
ls -l "$DESTINO"

BINARIO="$DESTINO/tukul-linux-x86_64"
BUNDLE="$BINARIO.bundle"

if [ ! -f "$BUNDLE" ]; then
    echo "::error::La release $TAG no trae '$BUNDLE'. No hay firma que verificar."
    echo "Un release sin firma permite comprobar integridad, no procedencia."
    exit 1
fi

echo "== Verificación keyless (identidad de workflow + emisor OIDC) =="
cosign verify-blob \
    --bundle "$BUNDLE" \
    --certificate-identity-regexp "^https://github.com/${REPO}/.github/workflows/build-release.yml@refs/(tags/v[0-9]+\.[0-9]+\.[0-9]+|heads/[^ ]+)$" \
    --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
    "$BINARIO"

# La firma prueba procedencia del bundle; esto prueba que el binario descargado
# es el que se firmó (integridad) y no otro con el mismo nombre.
echo "== Integridad del binario descargado =="
(cd "$DESTINO" && sha256sum -c SHA256SUMS)

echo "== Firma válida: el binario lo produjo este repositorio =="
