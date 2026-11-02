# Testing y quality gate

La suite está en `tests/`. Hay tests unitarios de core y utilidades, integración de UI bajo Tk/X, regresión de auditoría y contratos de concurrencia/protocolo. `tests/performance/locustfile.py` existe como material de performance opcional; no forma parte del gate local/CI actual.

## Comandos y contratos

```bash
python -m ruff check .
python -m mypy tukul_core tukul_ui tukul.py
xvfb-run -a python -m pytest -q -rs --cov=tukul_core --cov=tukul_ui --cov-report=term-missing --cov-fail-under=70
python -m pip_audit --local --skip-editable
bandit -r tukul_core tukul_ui -lll -ii
./scripts/verify-install.sh
./scripts/quality-gate.sh
```

CI usa Python 3.11, 3.12 y 3.13, instala Tk/Xvfb, lockfile con hashes, ejecuta `pip-audit`, la instalación aislada, ruff, mypy, pytest con cobertura mínima 70 %, falla si hay skips y prueba `--health` y el contrato CLI. Bandit produce informe completo como artefacto y bloquea solo severidad/confianza alta. No hay expected failures declarados; los skips de UI requieren display y el workflow los convierte en fallo.

`scripts/verify-install.sh` instala el paquete en un venv temporal, lo importa desde fuera del checkout y ejecuta `tukul --health`. Cubre el hueco que dejaban `pip install -e .` y `conftest.py`: con ambos, un paquete movido o mal declarado pasaba lint y tests mientras `pip install` fallaba para cualquiera. `tests/test_installation_integrity.py` fija ese contrato dentro de la suite.

- `TEST_PASS`: pytest termina sin fallos; los skips solo son aceptables en una ejecución explícitamente sin display y deben declararse.
- `QUALITY_GATE_PASS`: ruff, mypy, instalación aislada, pytest/cobertura/Tk y cero skips pasan en `scripts/quality-gate.sh`.
- `RELEASE_TEST_PASS`: quality gate, auditoría de dependencias, smoke `--health` del binario y validaciones del workflow de build pasan.

Los conteos de tests son snapshots de una ejecución, no contrato. Usa comandos y thresholds como autoridad.
