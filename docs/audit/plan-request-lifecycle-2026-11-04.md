# Plan — Extraer `RequestLifecycle` de `TukulApp` (H2, primera etapa)

## Objetivo
Un solo dueño del ciclo de petición (inicio, cancelación, eventos de control),
en vez de cuatro `def work` inline y seis puntos de reset dispersos.

## Contrato del módulo `tukul_ui/request_lifecycle.py`
- `RequestLifecycle(chunks, control_queue, llm, publicar)`:
  - `publicar(evento)` → `control_queue.put_nowait` (misma tupla que hoy).
  - `start(profile, request_id, cancel_event, enviar)` → arranca el worker en
    `WorkerThreads`; `enviar(api_key)` ejecuta el stream y publica
    `complete`/`error` con el formato actual.
  - `cancel(request_id)` → marca el evento y cierra el stream HTTP.
  - `on_event(event)` → despacha `error`/`complete`/`keyring_unavailable`.
- La UI conserva: aprobación de contexto, diálogos, pintura y `finish`.

## Invariantes que NO deben cambiar (red de seguridad)
- [ ] `test_cola_eventos` sin cambios
- [ ] `test_reentrada_peticiones` sin cambios
- [ ] `test_cierre_hilos` sin cambios
- [ ] `test_flujo_revision` sin cambios (salvo el parche de `_en_el_hilo_de_tk` ya existente)
- [ ] `test_auditoria_regresion` sin cambios

## Pasos
- [ ] 1. Crear el módulo con tests propios (sin tocar `app.py`).
- [ ] 2. Migrar el envío normal (`request` → `confirm_and_send` → `_lanzar_envio`).
- [ ] 3. Migrar la revisión (`_solicitar_revision`).
- [ ] 4. Migrar el feed CVE y las ideas si aplica (no usan `LLMSessionManager`).
- [ ] 5. Medir: líneas de `app.py`, cobertura del módulo nuevo.

## Cierre
- `app.py` pierde ≥ 150 líneas y el ciclo de petición vive en un módulo con
  cobertura ≥ 90 %.

---

# Recaptura de la captura del README (punto 2)

`docs/screenshots/tukul.png` muestra la paleta anterior. Hace falta una captura
real de la ventana, que solo puede tomarse en el escritorio del usuario:

1. `python tukul.py` con un artículo de ejemplo.
2. Captura de ventana completa (la ventana debe estar mapeada y con foco).
3. Sustituir `docs/screenshots/tukul.png` y confirmar en el commit.
