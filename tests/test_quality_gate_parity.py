"""Paridad entre la puerta de calidad local y el pipeline de CI.

El gate anunciaba ser "espejo del pipeline" pero omitía `pip-audit`, `bandit`
y las comprobaciones de `--health` y CLI; además, en un checkout sin instalar
fallaba con un `ModuleNotFoundError` críptico dentro de pytest. Estos tests
fijan el contrato para que la divergencia no vuelva a colarse.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "quality-gate.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _texto_gate() -> str:
    return GATE.read_text(encoding="utf-8")


def _texto_ci() -> str:
    return CI.read_text(encoding="utf-8")


def test_el_gate_ejecuta_las_puertas_de_seguridad_de_ci():
    """pip-audit y bandit son puertas en CI; el gate local debe ejecutarlas."""
    gate = _texto_gate()
    ci = _texto_ci()
    assert "pip_audit" in ci and "bandit" in ci
    assert "pip_audit" in gate, "El gate no audita dependencias como CI"
    assert "bandit" in gate, "El gate no ejecuta la puerta de Bandit de CI"
    assert "-lll -ii" in gate, "Bandit debe correr con los mismos umbrales que CI"


def test_el_gate_comprueba_la_instalacion_con_mensaje_accionable():
    """Sin el paquete instalado, pytest falla con un ModuleNotFoundError críptico."""
    gate = _texto_gate()
    assert 'import tukul_core' in gate
    assert "pip install -e" in gate, "El aviso debe decir cómo instalar el paquete"


def test_el_gate_ejecuta_el_diagnostico_health():
    """`--health` es contrato de CI y de release: también lo es en local."""
    assert "tukul.py --health" in _texto_ci()
    assert "tukul.py --health" in _texto_gate()


def test_el_gate_invoca_los_mismos_targets_de_mypy_que_ci():
    assert "mypy tukul_core tukul_ui tukul.py" in _texto_ci()
    assert "mypy tukul_core tukul_ui tukul.py" in _texto_gate()
