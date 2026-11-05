// La revisión de un texto con faltas produce al menos un hallazgo válido.
// Lo cuenta `parse_findings` del repo, no una copia del criterio.
const bruto = JSON.parse(output || '{}');
const meta = bruto.metadata || {};
return typeof meta.parse_findings_count === 'number' && meta.parse_findings_count > 0;
