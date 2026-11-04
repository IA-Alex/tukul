# Plan — Roadmap 1-4 de la auditoría 2026-11-04

Ejecución en local (CI bloqueado por el runner). Verificación obligatoria tras cada tarea:
`ruff`, `mypy`, `pytest` con cobertura bajo `xvfb-run`.

## Tarea 1 — Alinear `scripts/quality-gate.sh` con CI
- [ ] Añadir `pip-audit --local --skip-editable`
- [ ] Añadir `bandit -r tukul_core tukul_ui -lll -ii`
- [ ] Comprobar `import tukul_core` antes de pytest con mensaje accionable
- [ ] Añadir `--health` con `tukul.example.toml` (paridad con CI)
- [ ] Verificar: gate en checkout sin instalar → mensaje claro

## Tarea 2 — Perfiles: diagnóstico de campos descartados
- [ ] `_coerce_profile_fields` registra cada campo descartado (perfil, campo, valor, tipo)
- [ ] `load_profiles` devuelve los avisos (sin romper su contrato de tupla)
- [ ] `--health` los muestra
- [ ] Test: TOML con `max_output_tokens = 4096.0` → aviso + arranque sin crash

## Tarea 3 — Docs: reconciliar la fuente CVE
- [ ] `SECURITY.md`: sección "planeada" → histórica
- [ ] `TRACEABILITY.md`: fila de la fuente CVE

## Tarea 4 — Contrato HTTP de `LLMClient`
- [ ] Servidor local (`ThreadingHTTPServer`) en `tests/test_llm_http_contract.py`
- [ ] SSE correcto · `429` + `Retry-After` · `302` no seguido · body sobredimensionado
- [ ] Cabeceras por protocolo (OpenAI / Anthropic / Gemini)

## Cierre
- [ ] Suite completa verde, cobertura ≥ 80 %
- [ ] Actualizar `CHANGELOG.md` y recuento del informe
- [ ] Commit + push
