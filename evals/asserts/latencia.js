// La revisión llega dentro de un presupuesto de tiempo.
//
// Una revisión correcta que tarda 40 s no es utilizable: la persona está
// esperando ante un artículo. El umbral se pasa en `config.ms` y se compara
// con el tiempo de pared que mide el adaptador (`metadata.latency_ms`).
module.exports = (output, context) => {
  const meta = JSON.parse(output || '{}').metadata || {};
  const limite = (context.config || {}).ms || 20000;
  if (typeof meta.latency_ms !== 'number') return false;
  return meta.latency_ms <= limite;
};
