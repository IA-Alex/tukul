// Un artículo LIMPIO solo es correcto si el modelo devolvió el contrato vacío.
//
// `contrato_json.js` acepta `sin_hallazgos` porque no distingue de dónde viene.
// En un artículo sin errores la única forma correcta es `{"findings": []}`;
// una respuesta con forma de objeto pero sin `findings` (p. ej.
// `{"review": "…"}`, observada el 2026-11-16) o prosa sin JSON significa que el
// modelo no entregó la revisión: el caso debe fallar aunque el texto no tenga
// errores. Sin esta aserción, ese fallo pasaba como «artículo limpio» (falso
// verde), y por eso el eval no lo detectaba de forma consistente.
//
// El adaptador publica `metadata.review_shape` (findings | vacia | otra |
// prosa). Se aceptan `vacia` y `findings`: una revisión con hallazgos en un
// texto limpio es un falso positivo del modelo, pero lo que decide el caso es
// que la revisión llegue; la ausencia de invención la mide `hallazgos_ser`/
// `categoria` en los casos que la exigen.
module.exports = (output) => {
  const bruto = JSON.parse(output || '{}');
  const meta = bruto.metadata || {};
  const forma = meta.review_shape;
  if (forma === 'vacia' || forma === 'findings') {
    return true;
  }
  return false;
};
