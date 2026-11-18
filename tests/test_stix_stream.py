"""Tests de `_stix_stream.iter_stix_objects` (extracción incremental de STIX).

El módulo no tenía pruebas directas: se cubría solo de refilón a través del
adaptador MITRE. Eso dejó pasar una regresión real: el refactor de `json.loads`
a la extracción incremental cambió el contrato de un JSON **sin** lista
`objects` (antes `[]`, después una excepción). Estos tests fijan la frontera
entre «bundle legítimo pero vacío» y «cuerpo ilegible».

Sin red ni disco: la respuesta se sustituye por un doble cuyo `read(n)` se agota
con `b""` como un cuerpo real.
"""

from __future__ import annotations

from typing import Any

import pytest

from tukul_core.real_time_feed.adapters._stix_stream import (
    StixStreamError,
    iter_stix_objects,
)


def _respuesta(cuerpo: bytes, trozo: int = 64) -> Any:
    """Doble de `response` que entrega `cuerpo` en tramos y luego `b""`."""
    from unittest.mock import MagicMock

    respuesta = MagicMock()
    tramos = [cuerpo[i:i + trozo] for i in range(0, len(cuerpo), trozo)] + [b""]
    cuerpo_iter = iter(tramos)
    respuesta.read.side_effect = lambda _n=None: next(cuerpo_iter)
    return respuesta


class TestBundleValido:
    def test_extrae_los_objetos_en_orden(self):
        cuerpo = (
            b'{"objects": [{"id": "a", "type": "attack-pattern"}, '
            b'{"id": "b", "type": "intrusion-set"}]}'
        )
        objetos = list(iter_stix_objects(_respuesta(cuerpo), 10_000))
        assert [o["id"] for o in objetos] == ["a", "b"]

    def test_lista_vacia_no_produce_objetos(self):
        objetos = list(iter_stix_objects(_respuesta(b'{"objects": []}'), 10_000))
        assert objetos == []

    def test_la_llave_partida_entre_tramos_se_reconoce(self):
        """`"objects"` puede caer a caballo entre dos lecturas."""
        cuerpo = b'{"type": "bundle", "objects": [{"id": "a"}]}'
        objetos = list(iter_stix_objects(_respuesta(cuerpo, trozo=18), 10_000))
        assert [o["id"] for o in objetos] == ["a"]

    def test_utf8_multibyte_no_desalinea_el_consumo(self):
        """`raw_decode` cuenta caracteres; el búfer es bytes (offset divergente)."""
        cuerpo = (
            '{"objects": [{"id": "a", "name": "café ñ"}, {"id": "b"}]}'
        ).encode()
        objetos = list(iter_stix_objects(_respuesta(cuerpo), 10_000))
        assert [o["id"] for o in objetos] == ["a", "b"]
        assert objetos[0]["name"] == "café ñ"

    def test_la_llave_raiz_manda_sobre_una_anidada_previa(self):
        """Una clave `"objects"` anidada antes que la raíz no debe secuestrar.

        La búsqueda literal de `"objects"` encontraba la primera aparición en
        cualquier parte: si un objeto declaraba antes una clave anidada
        `"objects"`, se extraía esa lista y se perdían los objetos de la raíz
        (bundle JSON válido, leído en silencio incorrectamente). El parser debe
        anclar la clave a la raíz (profundidad 1).
        """
        cuerpo = (
            b'{"meta": {"objects": [{"id": "nested", "type": "bogus"}]}, '
            b'"objects": [{"id": "real", "type": "attack-pattern"}]}'
        )
        objetos = list(iter_stix_objects(_respuesta(cuerpo), 10_000))
        assert [o["id"] for o in objetos] == ["real"]

    def test_la_llave_raiz_manda_con_cabecera_troceada(self):
        """El anclaje por profundidad también con la cabecera partida en tramos."""
        cuerpo = (
            b'{"meta": {"objects": [{"id": "nested"}]}, '
            b'"objects": [{"id": "real"}]}'
        )
        objetos = list(iter_stix_objects(_respuesta(cuerpo, trozo=5), 10_000))
        assert [o["id"] for o in objetos] == ["real"]

    def test_un_valor_de_cadena_objects_no_confunde_a_la_llave(self):
        """Un valor `"objects"` (raíz) no es la clave: se busca la clave real."""
        cuerpo = (
            b'{"note": "objects", "objects": [{"id": "real"}]}'
        )
        objetos = list(iter_stix_objects(_respuesta(cuerpo), 10_000))
        assert [o["id"] for o in objetos] == ["real"]

    def test_la_clave_con_espacios_antes_del_corchete_se_reconoce(self):
        cuerpo = b'{"objects":\n\t[{"id": "real"}]}'
        objetos = list(iter_stix_objects(_respuesta(cuerpo), 10_000))
        assert [o["id"] for o in objetos] == ["real"]


class TestJsonSinObjectsDegradaAVacio:
    """Un JSON válido sin lista `objects` no es un error: es un bundle vacío.

    Es el contrato que protegía el adaptador con `data.get("objects", [])` y que
    la extracción incremental rompió al lanzar `StixStreamError`.
    """

    @pytest.mark.parametrize("cuerpo", [b"{}", b'{"foo": 1}', b"[]", b'{"objects": 5}'])
    def test_json_valido_sin_lista_objects_devuelve_vacio(self, cuerpo):
        assert list(iter_stix_objects(_respuesta(cuerpo), 10_000)) == []


class TestCuerpoIlegibleFalla:
    def test_json_malformado_al_inicio_falla(self):
        with pytest.raises(StixStreamError):
            list(iter_stix_objects(_respuesta(b"{"), 10_000))

    def test_lista_objects_truncada_falla(self):
        with pytest.raises(StixStreamError, match="malformado"):
            list(iter_stix_objects(_respuesta(b'{"objects": [{"a": '), 10_000))

    def test_cuerpo_vacio_falla(self):
        with pytest.raises(StixStreamError):
            list(iter_stix_objects(_respuesta(b""), 10_000))


class TestTechoDeBytes:
    def test_respuesta_sobredimensionada_se_rechaza(self):
        cuerpo = b'{"objects": [' + b" " * 5000 + b"]}"
        with pytest.raises(StixStreamError, match="supera el límite"):
            list(iter_stix_objects(_respuesta(cuerpo), 100))
