#!/usr/bin/env bash
# Abre Tukul con un artículo de ejemplo para hacer la captura del README.
#
# No forma parte del producto ni del gate: es una utilidad para generar una
# captura reproducible. Crea un directorio temporal con un config de ejemplo
# (sin key) y un artículo, y deja la ventana lista para capturar.
#
# Uso:  ./scripts/captura_manual.sh
#       ./scripts/captura_manual.sh --perfil personal   # usa tu config real
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

if [[ ! -x .venv/bin/python ]]; then
    echo "Falta .venv/bin/python. Instala primero el proyecto." >&2
    exit 1
fi

if [[ "${1:-}" == "--perfil" ]]; then
    # Config real del usuario: la ventana abre con sus perfiles y su llavero.
    CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/tukul/config.toml"
    if [[ ! -f "$CONFIG" ]]; then
        echo "No existe $CONFIG" >&2
        exit 1
    fi
    echo "Usando tu configuración: $CONFIG"
    printf '\n  Captura la ventana con Ctrl+Impr Pant o con:\n'
    printf '    gnome-screenshot -w -f docs/screenshots/tukul.png\n\n'
    exec .venv/bin/python tukul.py --config "$CONFIG"
fi

DIR="$(mktemp -d "${TMPDIR:-/tmp}/tukul-captura.XXXXXX")"
cat > "$DIR/config.toml" <<'TOML'
[llm]
active_profile = "ejemplo"

[profiles.ejemplo]
provider = "openai_compatible"
endpoint = "https://api.example.com/v1/chat/completions"
model = "modelo-de-ejemplo"
api_key_env = "TUKUL_CAPTURA_KEY"
TOML
cat > "$DIR/seguridad.md" <<'MD'
# La seguridad no es un producto

Durante años tratamos la seguridad como la última fase del proyecto: algo que
se revisaba cuando ya estaba todo lo demás. Esa forma de trabajar tiene un
problema de fondo y no es de calendario.

## El cambio de enfoque

La seguridad se vuelve un proceso continuo: se revisa cada trimestre y se
documenta cada cambio. No hay una línea final que cruzar.

La continuidad depende de la documentación de cada cambio, porque un control
que nadie recuerda por qué existe se retira en la siguiente reauditoría.
MD

echo "Config:   $DIR/config.toml"
echo "Artículo: $DIR/seguridad.md"
echo
echo "La ventana abre con el artículo cargado. Captúrala con:"
echo "  gnome-screenshot -w -f docs/screenshots/tukul.png"
echo "  (Pulsar Impr Pant o Ctrl+Impr Pant y recortar la ventana)"
echo

exec .venv/bin/python tukul.py --config "$DIR/config.toml" "$DIR/seguridad.md"
