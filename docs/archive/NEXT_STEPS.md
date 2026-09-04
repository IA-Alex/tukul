# Próximos Pasos - Roadmap post-Maduro

> **Nota (2026-08-15):** documento histórico de una fase anterior. Describe una
> arquitectura que ya no existe (`chunk_queue`, `partial_output`, `_queue_event`,
> índice BM25) y cifras de tests desactualizadas. La referencia vigente son el
> código, `CHANGELOG.md` y `docs/`. No lo uses como fuente de verdad del estado actual.

**Estado histórico de la revisión:** ✅ OPCIÓN B completo. No es estado actual ni
una declaración vigente de readiness.
**Próximo milestone:** v1.0 Enterprise  
**Horizonte:** 2-3 semanas adicionales

---

## Inmediato (Esta semana)

### 1. Review Final con `/code-review ultra`
```bash
cd /home/panda/Articulos/articulador
# Desde Claude Code:
/code-review ultra
```
**Propósito:** Verificar que no hay gaps en los cambios recientes  
**Tiempo:** 30-60 min

### 2. Beta Testing Plan
- [ ] Seleccionar 3-5 early users
- [ ] Comunicar cambios principales (logging, health checks)
- [ ] Establecer feedback channel

### 3. Tag v0.2-beta
```bash
git tag -a v0.2-beta -m "OPCIÓN B: Production-ready, observable, maintainable"
git push origin v0.2-beta
```

---

## Próxima Sprint (1-2 semanas)

### 4. Type Hints - Cobertura 95%
**Esfuerzo:** 3-4 días  
**Herramienta:** mypy --strict

```bash
# Ejecutar type check
python3 -m mypy articulador_ui articulador_core --strict

# Agregar type hints a funciones con Any/Missing
# Prioridad: métodos públicos, core functions
```

**Checklist:**
- [ ] Todos los métodos públicos tienen type hints completos
- [ ] Parámetros y returns tipados
- [ ] mypy --strict pasa sin errores

### 5. CI/CD Pipeline Setup
**Esfuerzo:** 2-3 días  
**Platform:** GitHub Actions

Crear `.github/workflows/test.yml`:
```yaml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: python3 -m unittest discover -s tests -q
      - run: python3 -m mypy articulador_ui articulador_core --strict
```

### 6. E2E Tests - Tkinter Real Loop
**Esfuerzo:** 3-4 días  
**Enfoque:** Tests que ejecuten event loop completo

Crear `tests/test_e2e_ui.py`:
```python
class TestE2EStreaming(unittest.TestCase):
    def test_full_request_workflow(self):
        """E2E: send message → streaming → complete → UI updated"""
        # Inicializar app
        # Simular LLM response
        # Verificar UI changes
        # Validar logging
```

**Cobertura mínima:**
- Normal request → complete
- Request → error → banner visible
- Cancel mid-request
- Graceful shutdown

---

## v1.0 Final (2-3 semanas)

### 7. User Manual
**Esfuerzo:** 2-3 días

Crear `docs/USER_MANUAL.md`:
- Getting started
- Configuration guide
- Troubleshooting guide
- Best practices

### 8. Deployment Guide
**Esfuerzo:** 1-2 días

Crear `docs/DEPLOYMENT.md`:
- Installation steps
- Python version requirements
- Dependencies
- Configuration setup
- Running from CLI vs. package

### 9. Performance Tests
**Esfuerzo:** 2 días

Crear `tests/test_performance.py`:
- Streaming large responses (>100KB)
- Large projects (10K+ tokens history)
- Memory usage baseline
- CPU usage baseline

### 10. Release Preparation
**Esfuerzo:** 1 día

- [ ] Update CHANGELOG.md
- [ ] Update README.md with new features
- [ ] Bump version to 1.0.0
- [ ] Create GitHub Release
- [ ] Announce to early users

---

## v1.1+ Wishlist (Nice-to-have)

- [ ] Web UI (FastAPI + React) para remote users
- [ ] Plugin system para custom LLM providers
- [ ] Model benchmarking tool
- [ ] Config preset templates
- [ ] Bulk file processing
- [ ] Integration with cloud storage (Google Drive, Dropbox)

---

## Success Criteria para v1.0

- ✅ Type hints: 95%+
- ✅ Tests: 90/90 pasando
- ✅ Docs: User manual + deployment guide
- ✅ CI/CD: GitHub Actions pasando
- ✅ E2E: Tests ejecutando UI real
- ✅ Performance: Baseline establecido
- ✅ Release: Tags y releases en GitHub

---

## Estimated Timeline

```
AHORA          Week 1         Week 2         Week 3
│              │              │              │
├─ v0.2-beta   ├─ Code review  ├─ Type hints  ├─ Release v1.0
├─ Beta users  │              ├─ E2E tests   │
│              ├─ CI/CD setup  ├─ Perf tests  │
│              │              │              │
└──────────────┴──────────────┴──────────────┘
```

---

## Recursos

- **Code Review:** `/code-review ultra`
- **Tests:** `python3 -m unittest discover -s tests -v`
- **Health:** `from articulador_core.health import status_string; print(status_string())`
- **Type Check:** `python3 -m mypy articulador_ui articulador_core --strict`
- **Docs:** `docs/` directory
- **Config:** `pyproject.toml`

---

## Notas Finales

- Mantener changelog actualizado
- Responder feedback de beta users rápidamente
- Priorizar type hints + E2E tests para v1.0
- Documentación completa es clave para adoptión
- Anunciar public release en Twitter/Hacker News si aplica

**Meta:** Llegar a v1.0 Enterprise-ready en 3 semanas.

🚀 **Vamos con esto!**
