# Política de congelación — Tukul 0.9.0

**Estado:** contrato abierto; candidato local 0.9.0.
**Base normativa:** [contracts/contratos-0.9.md](contracts/contratos-0.9.md).
**Última Release publicada:** v0.8.3. El candidato 0.8.4 nunca obtuvo tag ni
Release: su acta quedó preparado, pendiente de credencial válida para los evals
y de tag. MCP y la guía de usuario añaden capacidades nuevas; el candidato se
formaliza como 0.9.0, no como parche 0.8.4.

## Historial de contratos

La serie 0.7.x quedó cerrada en 0.7.2. Las versiones 0.8.1 y 0.8.2 corrigieron
defectos confirmados de 0.8.0; 0.8.3 corrigió el arnés de eval y retiró el
transporte Gemini sin consumidor. El candidato local 0.8.4 corrige DF-001 y
DF-005 en fuentes externas, pero no se publicó. El detalle histórico está en
[el acta de 0.8.4](audit/cierre-0.8.4.md).

El contrato 0.8 introdujo F5–F6: prompts separados por modo y defensa común
contra inyección. Esas capacidades se heredan y sus tres evals siguen siendo
requisito de aceptación en 0.9.0.

## Alcance de 0.9.0

El contrato nuevo incorpora F7 (orientación y guía de usuario) y F8 (consultas
MCP locales por stdio). El contrato de cierre fija sus criterios funcionales y
de seguridad; el ADR-0007 documenta la decisión MCP.

## Qué se acepta sobre una versión congelada

- **Defecto confirmado:** el comportamiento observable incumple una promesa
  documentada, con reproducción y prueba de regresión que falla antes y pasa
  después.
- **Regresión:** una capacidad aceptada deja de funcionar.
- **Fallo de seguridad o integridad:** exposición, ejecución no autorizada,
  pérdida de datos o artefacto no verificable.
- **Fallo de entrega:** el paquete no corresponde al código o versión
  declarados.

Funciones y flags nuevos, refactorizaciones opcionales y cambios de
dependencias sin defecto confirmado requieren un contrato nuevo. La falta de
evidencia es No verificado, no un defecto confirmado ni una aprobación.

## Puerta de cierre de 0.9.0

1. Declarar alcance y criterios de aceptación de F7 y F8 en
   [contratos-0.9.md](contracts/contratos-0.9.md).
2. pyproject.toml, uv.lock, CHANGELOG y --health declaran 0.9.0;
   uv lock --check pasa.
3. ./scripts/quality-gate.sh pasa con cero omitidas y cobertura mínima de 70 %.
4. CI pasa en Python 3.11–3.13 y ejecuta la integración MCP real por stdio.
5. Los tres evals promptfoo heredados pasan con credencial válida; un 401 queda
   pendiente y no se declara verde.
6. El ejecutable Linux se construye y pasa --health y el control del suelo de
   glibc.
7. El tag anotado v0.9.0 identifica exactamente el HEAD validado. Después se
   verifican checksum, firma y health sobre el artefacto descargado.

No etiquetar ni publicar mientras haya condiciones pendientes. La publicación
y el push de tags son acciones externas.

## Reglas permanentes

- Nunca reescribir tags publicados; no sustituir silenciosamente un Release
  firmado.
- No debilitar controles de seguridad para que pase un eval.
- No elevar mejoras cosméticas a bloqueos ni ampliar el alcance de cierre.
- La deuda que no bloquea queda clasificada, mitigada y documentada.
- Ante pérdida de datos o seguridad activa, corregir de inmediato y documentar
  sin esperar al gate completo.
