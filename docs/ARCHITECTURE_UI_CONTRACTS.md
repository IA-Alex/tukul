# Contratos de Componentes UI

Para asegurar un desarrollo coherente tras la modularización, los componentes UI en `tukul_ui/components/` siguen los siguientes contratos de comunicación con `TukulApp` (el orquestador).

## Patrón de Comunicación: Callbacks
La comunicación es unidireccional:
1. **Componente -> App**: Mediante callbacks pasados en el constructor (`dict[str, Callable]`).
2. **App -> Componente**: Mediante métodos públicos del componente (ej. `panel.set_state(...)`, `panel.update(...)`).

### AssistantPanel
Contrato de callbacks obligatorios:
- `send_message`: `Callable[[], None]` - Dispara el envío del mensaje actual.
- `cancel_request`: `Callable[[], None]` - Cancela la petición activa.
- `review`: `Callable[[], None]` - Inicia la revisión del artículo/selección.
- `create_input`: `Callable[[tk.Misc], tk.Widget]` - Fábrica para el widget de entrada.
- `create_history`: `Callable[[tk.Misc], tk.Widget]` - Fábrica para el widget de historial.

### TopBar
Contrato de callbacks obligatorios:
- `save`: `Callable[[], bool]` - Guarda el documento actual.
- `manage_references`: `Callable[[], None]` - Abre diálogo de gestión de contexto.
- `toggle_asistente`: `Callable[[], None]` - Alterna visibilidad del panel asistente.
- `cambiar_tema`: `Callable[[], None]` - Alterna entre temas claro/oscuro.
- `settings`: `Callable[[], None]` - Abre diálogo de configuración.
