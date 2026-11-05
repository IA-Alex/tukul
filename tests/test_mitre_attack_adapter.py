"""Tests del adaptador MITRE ATT&CK (STIX desde el repositorio CTI).

El adaptador tenía 30 % de cobertura: se probaba a través del orquestador pero
nunca se ejercitaban ni el parseo STIX ni la normalización a `FeedEntry`, que
son justo los dos sitios donde un cambio de formato de MITRE rompería el feed
en silencio. Aquí se fija ese contrato sin red: el opener se sustituye por un
doble y el reloj/backoff se sustituyen por dobles para que la suite no duerma.
"""

from __future__ import annotations

import json
import urllib.error
from datetime import UTC, datetime, timedelta
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest

from tukul_core.http_safety import NO_REDIRECT_OPENER
from tukul_core.real_time_feed.adapters.mitre_attack import (
    ATTACK_ENTERPRISE_URL,
    BACKOFF_MAX,
    MAX_ATTEMPTS,
    MAX_RESPONSE_BYTES,
    RETRYABLE_STATUS,
    USER_AGENT,
    MitreAttackAdapter,
    _parse_stix_date,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(ATTACK_ENTERPRISE_URL, code, "error", headers, None)


def _response(payload: bytes | list[dict]) -> MagicMock:
    """Respuesta doble de urllib cuyo `read(n)` se agota con b'' como un cuerpo real."""
    cuerpo = payload if isinstance(payload, bytes) else json.dumps({"objects": payload}).encode()
    restante = [cuerpo, b"", b"", b""]
    respuesta = MagicMock()
    respuesta.read.side_effect = lambda *_a, **_k: restante.pop(0)
    respuesta.headers = {}
    return respuesta


def _hoy_stix(horas: int = 1) -> str:
    """Fecha STIX relativa al reloj real: `fetch()` filtra contra `datetime.now`."""
    return (
        (datetime.now(UTC) - timedelta(hours=horas))
        .strftime("%Y-%m-%dT%H:%M:%S.000Z")
    )


def _tecnica(
    tech_id: str = "T1059",
    nombre: str = "Command and Scripting Interpreter",
    modificada: str | None = None,
    **extra,
) -> dict:
    objeto = {
        "type": "attack-pattern",
        "id": tech_id,
        "name": nombre,
        "description": "Ejecución de comandos vía intérprete.",
        "modified": _hoy_stix() if modificada is None else modificada,
        "external_references": [
            {
                "source_name": "mitre-attack",
                "url": f"https://attack.mitre.org/techniques/{tech_id}/",
            }
        ],
    }
    objeto.update(extra)
    return objeto


@pytest.fixture(autouse=True)
def _cache_limpia():
    """El cache es de clase: se limpia antes y después para aislar los tests."""
    MitreAttackAdapter._cache = None
    MitreAttackAdapter._cache_ts = None
    yield
    MitreAttackAdapter._cache = None
    MitreAttackAdapter._cache_ts = None


# ─── Identidad de la fuente ────────────────────────────────────────────────


class TestIdentidad:
    def test_source_id_y_label(self):
        assert MitreAttackAdapter.source_id() == "mitre-attack"
        assert MitreAttackAdapter.label() == "MITRE ATT&CK Enterprise"

    def test_el_endpoint_usa_https(self):
        """El opener no sigue redirecciones: con http:// el fetch fallaría siempre."""
        assert ATTACK_ENTERPRISE_URL.startswith("https://")


# ─── Parseo de fechas STIX ────────────────────────────────────────────────


class TestParseStixDate:
    def test_acepta_el_sufijo_z(self):
        assert _parse_stix_date("2026-11-04T10:00:00Z", NOW) == datetime(
            2026, 11, 4, 10, 0, tzinfo=UTC
        )

    def test_acepta_desplazamiento_explicito(self):
        parsed = _parse_stix_date("2026-11-04T10:00:00+01:00", NOW)
        assert parsed == datetime(2026, 11, 4, 9, 0, tzinfo=UTC)

    @pytest.mark.parametrize("raw", ["", "no es una fecha", "2026-13-45T99:99:99Z"])
    def test_fecha_invalida_devuelve_el_valor_por_defecto(self, raw):
        assert _parse_stix_date(raw, NOW) is NOW

    def test_tipo_no_texto_devuelve_el_valor_por_defecto(self):
        with pytest.raises(AttributeError):
            _parse_stix_date(None, NOW)  # type: ignore[arg-type]


# ─── fetch() ──────────────────────────────────────────────────────────────


class TestFetch:
    def test_filtra_por_tipo_y_ventana_temporal(self):
        """Solo `attack-pattern` modificados dentro de la ventana pasan el filtro."""
        objetos = [
            _tecnica("T1059"),
            _tecnica("T1105", modificada=_hoy_stix(horas=24 * 40)),  # fuera de 24 h
            {"type": "intrusion-set", "id": "G0001", "modified": _hoy_stix()},
            # Fecha rota: se parsea con `now` como defecto y cuenta como reciente.
            {"type": "attack-pattern", "id": "T9999", "name": "fecha rota",
             "modified": "fecha rota"},
        ]
        with patch.object(NO_REDIRECT_OPENER, "open", return_value=_response(objetos)) as abrir:
            resultado = MitreAttackAdapter().fetch(24)

        assert [t["id"] for t in resultado] == ["T1059", "T9999"]
        # La petición va al endpoint CTI con el User-Agent declarado.
        peticion = abrir.call_args.args[0]
        assert peticion.full_url == ATTACK_ENTERPRISE_URL
        assert peticion.get_header("User-agent") == USER_AGENT

    def test_mete_en_cache_y_la_reutiliza_dentro_del_ttl(self):
        objetos = [_tecnica()]
        with patch.object(NO_REDIRECT_OPENER, "open", return_value=_response(objetos)) as abrir:
            adaptador = MitreAttackAdapter()
            primera = adaptador.fetch(24)
            segunda = adaptador.fetch(24)

        assert primera == segunda
        assert abrir.call_count == 1, "Dentro del TTL no debe haber segunda descarga."

    def test_refresca_la_cache_caducada(self):
        objetos = [_tecnica()]
        with patch.object(NO_REDIRECT_OPENER, "open", side_effect=[
            _response(objetos), _response(objetos),
        ]) as abrir:
            adaptador = MitreAttackAdapter()
            adaptador.fetch(24)
            adaptador._cache_ts = datetime.now(UTC) - timedelta(
                minutes=MitreAttackAdapter._CACHE_TTL_MINUTES + 1
            )
            adaptador.fetch(24)

        assert abrir.call_count == 2, "Caducado el TTL, se vuelve a descargar."

    @pytest.mark.parametrize("codigo", sorted(RETRYABLE_STATUS))
    def test_un_error_reintentable_se_reintenta_y_acaba_en_ok(self, codigo):
        objetos = [_tecnica()]
        side_effect = [_http_error(codigo), _response(objetos)]
        with patch.object(NO_REDIRECT_OPENER, "open", side_effect=side_effect) as abrir, \
                patch.object(MitreAttackAdapter, "_sleep") as dormir:
            resultado = MitreAttackAdapter().fetch(24)

        assert [t["id"] for t in resultado] == ["T1059"]
        assert abrir.call_count == 2
        dormir.assert_called_once()

    def test_un_error_reintentable_que_persiste_agota_intentos_y_falla(self):
        with patch.object(NO_REDIRECT_OPENER, "open", side_effect=_http_error(503)) as abrir, \
                patch.object(MitreAttackAdapter, "_sleep"):
            with pytest.raises(RuntimeError, match="503"):
                MitreAttackAdapter().fetch(24)

        assert abrir.call_count == MAX_ATTEMPTS

    def test_un_error_no_reintentable_falla_al_primero(self):
        with patch.object(NO_REDIRECT_OPENER, "open", side_effect=_http_error(404)) as abrir:
            with pytest.raises(RuntimeError, match="404"):
                MitreAttackAdapter().fetch(24)

        assert abrir.call_count == 1

    def test_url_error_se_reintenta_y_termina_en_error_legible(self):
        error = urllib.error.URLError("sin ruta al host")
        with patch.object(NO_REDIRECT_OPENER, "open", side_effect=error) as abrir, \
                patch.object(MitreAttackAdapter, "_sleep"):
            with pytest.raises(RuntimeError, match="No se pudo conectar"):
                MitreAttackAdapter().fetch(24)

        assert abrir.call_count == MAX_ATTEMPTS

    def test_os_error_transitorio_se_reintenta_y_acaba_en_ok(self):
        objetos = [_tecnica()]
        side_effect = [OSError("conexión reiniciada"), _response(objetos)]
        with patch.object(NO_REDIRECT_OPENER, "open", side_effect=side_effect), \
                patch.object(MitreAttackAdapter, "_sleep"):
            resultado = MitreAttackAdapter().fetch(24)

        assert [t["id"] for t in resultado] == ["T1059"]

    def test_timeout_que_persiste_falla(self):
        with patch.object(NO_REDIRECT_OPENER, "open", side_effect=TimeoutError("timeout")), \
                patch.object(MitreAttackAdapter, "_sleep"):
            with pytest.raises(RuntimeError, match="No se pudo conectar"):
                MitreAttackAdapter().fetch(24)


# ─── Lectura acotada ──────────────────────────────────────────────────────


class TestReadBounded:
    def test_lee_a_trozos_hasta_el_final(self):
        cuerpo = b'{"objects": []}'
        respuesta = MagicMock()
        respuesta.read.side_effect = [cuerpo[:5], cuerpo[5:], b""]

        assert MitreAttackAdapter()._read_bounded(respuesta) == cuerpo

    def test_rechaza_respuestas_por_encima_del_limite(self):
        respuesta = MagicMock()
        respuesta.read.side_effect = [b"x" * (MAX_RESPONSE_BYTES + 1)]

        with pytest.raises(RuntimeError, match="límite de bytes"):
            MitreAttackAdapter()._read_bounded(respuesta)

    def test_una_respuesta_demasiado_grande_aborta_el_fetch(self):
        """El tope de bytes se aplica antes de parsear: no se carga JSON gigante."""
        with patch.object(NO_REDIRECT_OPENER, "open", return_value=_response(
            b"x" * (MAX_RESPONSE_BYTES + 1)
        )):
            with pytest.raises(RuntimeError, match="límite de bytes"):
                MitreAttackAdapter().fetch(24)


# ─── Backoff ──────────────────────────────────────────────────────────────


class TestSleep:
    def test_backoff_exponencial_respeta_el_factor(self):
        with patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.time.sleep"
        ) as dormir, patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.random.random",
            return_value=0.0,
        ):
            adaptador = MitreAttackAdapter()
            adaptador._sleep(None, 1)
            adaptador._sleep(None, 2)

        esperados = [0.5, 1.0]
        reales = [llamada.args[0] for llamada in dormir.call_args_list]
        assert reales == pytest.approx(esperados)

    def test_el_jitter_se_aplica(self):
        with patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.time.sleep"
        ) as dormir, patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.random.random",
            return_value=1.0,
        ):
            MitreAttackAdapter()._sleep(None, 1)

        assert dormir.call_args.args[0] == pytest.approx(0.625)

    def test_el_tope_acota_el_backoff(self):
        with patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.time.sleep"
        ) as dormir, patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.random.random",
            return_value=1.0,
        ):
            MitreAttackAdapter()._sleep(None, 10)

        assert dormir.call_args.args[0] == pytest.approx(BACKOFF_MAX * 1.25)

    def test_retry_after_de_un_429_manda_sobre_el_backoff(self):
        with patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.time.sleep"
        ) as dormir, patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.random.random",
            return_value=0.0,
        ):
            MitreAttackAdapter()._sleep(_http_error(429, retry_after="2"), 1)

        assert dormir.call_args.args[0] == pytest.approx(2.0)

    def test_retry_after_se_acota_al_tope(self):
        with patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.time.sleep"
        ) as dormir, patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.random.random",
            return_value=0.0,
        ):
            MitreAttackAdapter()._sleep(_http_error(429, retry_after="9999"), 1)

        assert dormir.call_args.args[0] == pytest.approx(BACKOFF_MAX)

    @pytest.mark.parametrize("valor", ["no-numérico", "0.5"])
    def test_un_retry_after_inservible_cae_al_backoff(self, valor):
        with patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.time.sleep"
        ) as dormir, patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.random.random",
            return_value=0.0,
        ):
            MitreAttackAdapter()._sleep(_http_error(429, retry_after=valor), 1)

        assert dormir.call_args.args[0] == pytest.approx(0.5)

    def test_sin_retry_after_cae_al_backoff(self):
        with patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.time.sleep"
        ) as dormir, patch(
            "tukul_core.real_time_feed.adapters.mitre_attack.random.random",
            return_value=0.0,
        ):
            MitreAttackAdapter()._sleep(_http_error(429), 1)

        assert dormir.call_args.args[0] == pytest.approx(0.5)


# ─── Normalización a FeedEntry ────────────────────────────────────────────


class TestNormalize:
    def test_convierte_una_tecnica_en_entrada(self):
        entrada, = MitreAttackAdapter().normalize([_tecnica()])

        assert entrada.source_id == "mitre-attack:T1059"
        assert entrada.source == "mitre-attack"
        assert entrada.title == "Command and Scripting Interpreter"
        assert entrada.url == "https://attack.mitre.org/techniques/T1059/"
        modifica = datetime.fromisoformat(_tecnica()["modified"].replace("Z", "+00:00"))
        assert entrada.published == modifica
        assert entrada.severity is None, "ATT&CK no asigna severidad numérica."
        assert entrada.confidence == pytest.approx(0.9)
        assert entrada.tags == frozenset({"mitre-attack", "ttp", "attack-pattern"})
        assert "ttp" in entrada.topics

    def test_la_descripcion_se_recorta_a_500_caracteres(self):
        entrada, = MitreAttackAdapter().normalize([_tecnica(description="x" * 900)])

        assert len(entrada.description) == 500

    def test_sin_referencia_mitre_usa_la_url_canonica(self):
        entrada, = MitreAttackAdapter().normalize(
            [_tecnica(external_references=[{"source_name": "otra", "url": "https://ejemplo"}] )]
        )

        assert entrada.url == "https://attack.mitre.org/techniques/T1059/"

    def test_sin_external_references_usa_la_url_canonica(self):
        tech = _tecnica()
        del tech["external_references"]
        entrada, = MitreAttackAdapter().normalize([tech])

        assert entrada.url == "https://attack.mitre.org/techniques/T1059/"

    def test_fecha_ausente_o_rota_cae_al_momento_de_normalizar(self):
        sin_fecha = _tecnica("T1")
        del sin_fecha["modified"]
        antes = datetime.now(UTC)
        entradas = MitreAttackAdapter().normalize([
            sin_fecha,
            _tecnica("T2", modificada="no es fecha"),
        ])
        despues = datetime.now(UTC)

        assert len(entradas) == 2
        for entrada in entradas:
            assert antes <= entrada.published <= despues

    @pytest.mark.parametrize(
        "roto",
        [
            {"id": "", "name": "sin id"},
            {"id": "T1", "name": ""},
            {},
        ],
    )
    def test_descarta_tecnicas_sin_id_o_sin_nombre(self, roto):
        assert MitreAttackAdapter().normalize([roto]) == []

    def test_lista_vacia(self):
        assert MitreAttackAdapter().normalize([]) == []

    def test_descripcion_ausente_queda_vacia(self):
        tech = _tecnica()
        del tech["description"]
        entrada, = MitreAttackAdapter().normalize([tech])

        assert entrada.description == ""


# ─── Recorrido completo ───────────────────────────────────────────────────


class TestFetchYNormalize:
    def test_payload_stix_realista_de_punta_a_punta(self):
        payload = {
            "objects": [
                _tecnica("T1059"),
                {"type": "intrusion-set", "id": "G0001"},
                _tecnica("T1105", modificada=_hoy_stix(horas=24 * 365)),
            ]
        }
        cuerpo = json.dumps(payload).encode()
        with patch.object(NO_REDIRECT_OPENER, "open", return_value=_response(cuerpo)):
            crudo = MitreAttackAdapter().fetch(48)
            entradas = MitreAttackAdapter().normalize(crudo)

        assert [e.source_id for e in entradas] == ["mitre-attack:T1059"]

    def test_un_json_no_objeto_no_rompe_el_tipo_de_objects(self):
        """`json` devuelve lo que haya: solo se guardan los `objects` declarados."""
        with patch.object(NO_REDIRECT_OPENER, "open", return_value=_response(b"{}")):
            assert MitreAttackAdapter().fetch(24) == []
