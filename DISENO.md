# Sistema visual de Articulador

La interfaz usa un tema oscuro de bajo contraste para escritura prolongada. Los valores globales de color y tipografía se definen en `COLORS` y `FONT` dentro de `articulador_ui/app.py`.

| Rol | Valor | Uso |
| --- | --- | --- |
| Lienzo | `#151a20` | Fondo de la aplicación |
| Superficie | `#1d252e` | Paneles y secciones |
| Superficie elevada | `#25313b` | Conversación y acciones agrupadas |
| Campo editable | `#10161c` | Editor y entrada de mensajes |
| Texto | `#edf2f6` | Lectura principal |
| Texto auxiliar | `#a9b7c4` | Estado y ayuda |
| Acción principal | `#69c7b2` | Enviar y acciones positivas |
| IA | `#aabaff` | Identidad de respuestas del asistente |
| Selección | `#365f69` | Texto seleccionado |

La familia base es **DejaVu Sans**, disponible de forma predeterminada en el entorno Linux objetivo. La escala es: caption 9, cuerpo 10, sección 11, editor 12 y display 22 puntos.

La conversación es el espacio principal; el artículo es el espacio de edición de apoyo. Las acciones primarias se reservan para una sola decisión por área y las acciones secundarias usan contraste menor.
