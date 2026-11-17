# Verificación C3 — lector de pantalla (AT-SPI real)

Fecha: 2026-11-17. Cierra parcialmente el hallazgo **C3** que los cortes
`0.7.1` → `0.8.2` dejaron como «sin host con Orca; no verificado».

## Entorno

| Elemento | Estado |
|---|---|
| Orca | 48.1 (`/usr/bin/orca`), AT-SPI2 2.56.2 |
| `at-spi-bus-launcher` / `at-spi2-registryd` | corriendo en el bus de sesión |
| `python3-gi` (sistema) | 3.50.0, `Atspi` importable |
| Toolkit de Tukul | Tk 9.0 / Tkinter |
| `toolkit-accessibility` | activado durante la prueba |

## Método

1. Se lanza Tukul bajo `xvfb-run` con `GTK_MODULES=gail:atk-bridge` y
   `NO_AT_BRIDGE=0`.
2. A los 10 s se recorre `Atspi.get_desktop(0)` y se busca la aplicación por
   nombre, resumiendo roles y nombres accesibles.

## Resultado

```text
NO_ENCONTRADO: Tukul no expuso aplicación en AT-SPI
apps visibles: ['gnome-shell', 'gsd-color', ..., 'code', 'Brave Browser',
                'Google Chrome', 'org.gnome.Terminal']
```

Otras 19 aplicaciones sí aparecen en el mismo bus, incluido `code` (Electron) y
`org.gnome.Terminal` (GTK): el bus y el registro funcionan. **Tukul no
aparece.**

## Lectura

Tk 9.0 **no implementa el bridge AT-SPI**: no publica árbol de accesibilidad, así
que ningún lector de pantalla (Orca incluido) puede leer los widgets de Tukul,
con independencia de qué etiquetas ponga la aplicación. No es un defecto de
código de Tukul ni algo que se arregle con `tkinter` puro: requeriría exponer la
UI por otra vía (un toolkit con bridge propio, o una capa AT-SPI/Spi que publique
el árbol) — es una **decisión de arquitectura**, no una reparación.

## Estado

- **C3 deja de ser «no verificado»:** queda **verificado como no expuesto**.
- Lo que sí cubre la suite —contraste WCAG AA, foco, orden de tabulación— no se
  sustituye por esto; son comprobaciones distintas.
- Abrir accesibilidad real exige un contrato nuevo con su criterio de aceptación
  (p. ej. «Orca lee el árbol del editor y de la barra»), tal como pide
  `cierre-2026-11-13-final.md`.

## Efecto secundario

El `gsettings set org.gnome.desktop.interface toolkit-accessibility true` usado
para la prueba se dejó activado. Desactivarlo si no se desea: `gsettings set
org.gnome.desktop.interface toolkit-accessibility false`.
