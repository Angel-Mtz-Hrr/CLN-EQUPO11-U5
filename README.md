# FitZone · Unidad 5 · Integración, pruebas y calidad

Pruebas automatizadas para el sistema de reservas, accesos y listas de espera de **FitZone**
(patrón *Domain Model*, basado en el BRD, las User Stories y el Informe de Arquitectura del Equipo 11).

> **Avance:** Sección 1 de 4 completada (dominio + pruebas unitarias + ciclo TDD).
> Siguen: persistencia (Sección 2), mocks y seguridad (Sección 3), cobertura y CI (Sección 4).

## ¿Qué es este proyecto, en palabras simples?

Un gimnasio tiene reglas: *"solo entra quien tiene membresía vigente"*, *"no se reserva una clase que
tu plan no incluye"*, *"nunca más gente que lugares"*. Este proyecto **escribe esas reglas como código
y luego las comprueba solas**, en menos de un segundo, cada vez que alguien cambia algo.

## Cómo ejecutarlo

```bash
python -m venv .venv
# Windows PowerShell:  .\.venv\Scripts\Activate.ps1
# macOS / Linux:       source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -v
python -m ruff check src tests
python -m pytest --cov=src --cov-report=term-missing
```

## Estructura

| Ruta | Para qué sirve |
|---|---|
| `src/domain.py` | Las reglas del negocio (BR-05, BR-06, BR-07, BR-08 y permisos BR-01 a BR-04) |
| `tests/conftest.py` | Datos de ejemplo ficticios que comparten las pruebas |
| `tests/test_elegibilidad.py` | Pruebas de membresía vigente (BR-06) y clase incluida en el plan (BR-07) |
| `tests/test_clase_grupal.py` | Pruebas de cupo (BR-05), reservas, lista de espera, asistencia y no-shows |
| `docs/evidencias/` | Salidas reales de RED, GREEN, REFACTOR y la prueba de defectos |
| `docs/matriz_de_casos_seccion1.csv` | Tabla de casos: éxito, error y límite |
| `.github/workflows/ci.yml` | Revisión automática en GitHub (se detalla en la Sección 4) |

## Cómo leer una prueba (Arrange – Act – Assert)

Es como probar una máquina expendedora: **Arrange** = meter las monedas (preparar la situación),
**Act** = presionar el botón (hacer la acción), **Assert** = comprobar que salió el producto correcto.

## TDD: Red → Green → Refactor

1. **RED:** escribo la prueba de una regla que aún no existe y la veo **fallar** (así sé que la prueba sirve).
2. **GREEN:** escribo lo mínimo para que pase.
3. **REFACTOR:** ordeno el código sin cambiar su comportamiento; las pruebas confirman que nada se rompió.

Caso de esta sección: **un socio no puede reservar dos veces la misma clase** (INV-4).
Evidencia: `docs/evidencias/TDD_1_RED.txt` (2 fallan), `TDD_2_GREEN.txt` (57 pasan), `TDD_3_REFACTOR.txt` (57 pasan).

## Supuestos que conviene validar con FitZone

- El **día exacto del vencimiento** cuenta como vigente (el BRD no lo precisa).
- Solo **Socio (para sí mismo)** y **Recepción** reservan; el BRD no menciona reservas del Administrador.
- No se puede **bajar la capacidad** de una clase por debajo de los lugares ya ocupados (se deduce de INV-1).
- No existen sanciones por no-show (BR-09) ni plazo de cancelación (BR-10): no se inventaron.
