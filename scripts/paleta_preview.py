"""Reproduce el sistema visual de Tukul como página HTML autocontenida.

Sirve para revisar la paleta sin abrir la app: se abre en un navegador, se
captura con Playwright y se compara entre temas. Genera la página desde
`tukul_ui.estilo`, así que nunca puede quedar desincronizada de la paleta real.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from tukul_ui import estilo as es  # noqa: E402

MUESTRAS = (
    ("fondo", "fondo"), ("superficie", "superficie"),
    ("superficie_alta", "superficie alta"), ("superficie_activa", "hover"),
    ("borde", "borde"), ("borde_control", "borde de control"),
    ("foco", "foco"), ("acento", "acento"), ("acento_activo", "acento activo"),
    ("texto", "texto"), ("texto_tenue", "texto tenue"), ("seleccion", "selección"),
    ("estado_exito", "éxito"), ("estado_aviso", "aviso"), ("estado_error", "error"),
    ("voz_usuario", "voz usuario"), ("voz_asistente", "voz asistente"),
)

ESTADOS = (
    ("estorbo", "estado_neutro", "·", "En reposo"),
    ("proceso", "estado_proceso", "◐", "Recibiendo respuesta"),
    ("éxito", "estado_exito", "✓", "Respuesta lista"),
    ("aviso", "estado_aviso", "!", "Sin perfiles habilitados"),
    ("error", "estado_error", "✗", "No se pudo completar"),
)


def bloque_tema(tema: str) -> str:
    """Wikimedia del tema: barra, editor, panel y estados."""
    es.aplicar_tema(tema)
    t = es.PALETAS[tema]
    muestras = "".join(
        f'<div class="muestra" style="color:{t["texto_tenue"]}">'
        f'<span style="background:{t[clave]}"></span>'
        f'<code>{t[clave]}</code><small>{etiqueta}</small></div>'
        for clave, etiqueta in MUESTRAS
    )
    estados = "".join(
        f'<div class="estado"><b style="color:{t[clave]}">{simbolo}</b>'
        f'<span>{titulo}</span></div>'
        for _, clave, simbolo, titulo in ESTADOS
    )
    return f'''
<section class="tema" style="background:{t["fondo"]};color:{t["texto"]}">
  <header style="background:{t["superficie"]};border-bottom:1px solid {t["borde"]}">
    <strong style="color:{t["texto"]}">Tukul · {tema}</strong>
    <span class="chip" style="background:{t["superficie_alta"]};border:1px solid {t["borde_control"]};color:{t["texto"]}">Revisar artículo</span>
    <span class="chip primario" style="background:{t["acento"]};color:{t["acento_texto"]}">Enviar</span>
    <span class="chip" style="background:{t["superficie_activa"]};color:{t["texto"]}">hover</span>
    <span class="chip" style="background:{t["superficie"]};border:1px solid {t["borde"]};color:{t["texto_tenue"]}">Cancelar</span>
  </header>
  <div class="cuerpo">
    <article style="background:{t["superficie_alta"]};border:1px solid {t["borde_control"]}">
      <h2 style="color:{t["texto"]}">Del tunkul al párrafo</h2>
      <p style="color:{t["texto"]}">El tambor maya de dos lengüetas suena en <em style="background:{t["seleccion"]}">el texto elegido</em> antes de cada corrección.</p>
      <p style="color:{t["texto_tenue"]}">El ocre de la madera separa; el azul del acento señala la acción.</p>
      <p class="cita" style="border-left:3px solid {t["borde"]};color:{t["texto_tenue"]}">Divisoria discreta a <b>3:1</b> sobre cada capa.</p>
    </article>
    <aside style="background:{t["superficie"]};border:1px solid {t["borde"]}">
      <p style="color:{t["voz_usuario"]}"><b>Tú:</b> revisa este párrafo</p>
      <p style="color:{t["voz_asistente"]}"><b>Tukul:</b> sobra una coma…</p>
      <div class="estados">{estados}</div>
      <span class="foco" style="outline:2px solid {t["foco"]};color:{t["texto"]}">campo con foco</span>
    </aside>
  </div>
  <div class="muestras">{muestras}</div>
</section>'''


def pagina() -> str:
    temas = bloque_tema("dark") + bloque_tema("light")
    es.aplicar_tema(es.TEMA_DEFECTO)
    return f'''<!doctype html><html lang="es"><meta charset="utf-8">
<title>Tukul · sistema visual</title>
<style>
  body {{ margin:0; font:14px/1.5 system-ui, sans-serif; background:#0b0b0c; }}
  .tema {{ padding:20px 24px 16px; }}
  header {{ display:flex; gap:10px; align-items:center; padding:10px 12px; border-radius:8px 8px 0 0; }}
  .chip {{ padding:5px 10px; border-radius:6px; font-size:13px; }}
  .chip.primario {{ font-weight:600; }}
  .cuerpo {{ display:grid; grid-template-columns:2fr 1fr; gap:12px; padding:12px 0; }}
  article, aside {{ padding:14px; border-radius:8px; }}
  h2 {{ margin:0 0 8px; font-size:18px; }}
  p {{ margin:0 0 8px; }}
  .cita {{ padding-left:10px; }}
  .estados {{ display:flex; flex-wrap:wrap; gap:8px; margin:10px 0; }}
  .estado {{ display:flex; gap:6px; align-items:baseline; font-size:12px; }}
  .foco {{ display:inline-block; padding:4px 8px; border-radius:6px; }}
  .muestras {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(130px,1fr)); gap:8px; }}
  .muestra {{ display:flex; flex-direction:column; gap:2px; font-size:11px; }}
  .muestra span {{ height:26px; border-radius:4px; display:block; border:1px solid rgba(128,128,128,.35); }}
</style>
<body>{temas}</body></html>'''


if __name__ == "__main__":
    destino = RAIZ / "build" / "paleta-tukul.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(pagina(), encoding="utf-8")
    print(destino)
