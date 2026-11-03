# FitZone · Unidad 5 · Integración, pruebas y calidad

Pruebas automatizadas para el sistema de reservas, accesos y listas de espera de **FitZone**
(patrón _Domain Model_, basado en el BRD, las User Stories y el Informe de Arquitectura del Equipo 11).

> **Avance:** Secciones 1, 2 y 3 de 4 completadas (dominio + TDD, persistencia con SQLAlchemy, mocks y seguridad).
> Sigue: cobertura HTML y CI (Sección 4).

## ¿Qué es este proyecto, en palabras simples?

Un gimnasio tiene reglas: _"solo entra quien tiene membresía vigente"_, _"no se reserva una clase que
tu plan no incluye"_, _"nunca más gente que lugares"_. Este proyecto **escribe esas reglas como código
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

| Ruta                                                     | Para qué sirve                                                               |
| -------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `src/domain.py`                                          | Las reglas del negocio (BR-05, BR-06, BR-07, BR-08 y permisos BR-01 a BR-04) |
| `src/ports.py`                                           | "Contratos" de persistencia (Repository y Unit of Work), sin SQL             |
| `src/servicios.py`                                       | Reservar, cancelar clases y cobrar, coordinando reglas, base de datos, avisos y banco |
| `src/repository.py`                                      | Implementación con SQLAlchemy: tablas, repositorios y transacciones          |
| `tests/conftest.py`                                      | Datos de ejemplo ficticios y base SQLite en memoria para las pruebas         |
| `tests/test_repository.py`                               | Pruebas de integración: guardar, recuperar, rollback, concurrencia           |
| `tests/test_elegibilidad.py`                             | Pruebas de membresía vigente (BR-06) y clase incluida en el plan (BR-07)     |
| `tests/test_servicios_externos.py`                       | Mocks: avisos y cobros simulados (nada se envia ni se cobra de verdad)       |
| `tests/test_security.py`                                 | Permisos por rol (BR-01, BR-03, BR-04, BR-05, US-19, BR-08)                  |
| `tests/test_clase_grupal.py`                             | Pruebas de cupo (BR-05), reservas, lista de espera, asistencia y no-shows    |
| `docs/evidencias/`                                       | Salidas reales de RED, GREEN, REFACTOR y la prueba de defectos               |
| `docs/matriz_de_casos_seccion1/2/3.csv` | Tablas de casos: éxito, error y límite                                       |
| `.github/workflows/ci.yml`                               | Revisión automática en GitHub (se detalla en la Sección 4)                   |

## Cómo leer una prueba (Arrange – Act – Assert)

Es como probar una máquina expendedora: **Arrange** = meter las monedas (preparar la situación),
**Act** = presionar el botón (hacer la acción), **Assert** = comprobar que salió el producto correcto.

## TDD: Red → Green → Refactor

1. **RED:** escribo la prueba de una regla que aún no existe y la veo **fallar** (así sé que la prueba sirve).
2. **GREEN:** escribo lo mínimo para que pase.
3. **REFACTOR:** ordeno el código sin cambiar su comportamiento; las pruebas confirman que nada se rompió.

Caso de esta sección: **un socio no puede reservar dos veces la misma clase** (INV-4).
Evidencia: `docs/evidencias/TDD_1_RED.txt` (2 fallan), `TDD_2_GREEN.txt` (57 pasan), `TDD_3_REFACTOR.txt` (57 pasan).

## Sección 2: persistencia explicada sin tecnicismos

- **Repository** = el "archivista": sabe guardar y buscar clases sin que el resto del sistema sepa cómo.
- **Unit of Work** = una "transferencia bancaria": o se guarda **todo** o **nada**. Si algo falla, o si
  se olvida confirmar, no queda nada a medias (`confirmar()` guarda, `revertir()` descarta).
- **Control de versiones**: si dos personas piden el último lugar a la vez, la primera gana y la
  segunda recibe `ConflictoDeVersion` y puede reintentar. Nunca se supera el cupo.
- **Doble red de seguridad**: el dominio valida las reglas, y la base de datos también se niega a
  guardar datos imposibles (capacidad 0, dos lugares vigentes del mismo socio, etc.).
- Las pruebas usan SQLite **en memoria**: nunca tocan datos reales y desaparecen al terminar.
- Evidencia: `docs/evidencias/SECCION2_PRUEBA_DE_DEFECTOS.txt` (incluye un defecto real que las
  pruebas descubrieron y que se corrigió).

## Sección 3: servicios externos y seguridad, sin tecnicismos

- **Mock = actor de ensayo.** El correo y el banco son servicios de afuera. En las pruebas los
  reemplazamos por "actores de ensayo" que solo **anotan** lo que se les pide: así comprobamos
  _"se pidió cobrar exactamente 500 pesos"_ sin cobrar a nadie ni enviar un solo correo.
- **Regla de oro de los avisos:** primero se guarda la reserva, después se avisa. Si el correo está
  caído, el socio **conserva su lugar**; el sistema solo reporta que el aviso no salió.
- **Regla de oro de los cobros:** un solo intento (nunca doble cobro), monto mayor que cero, y si el
  banco rechaza no se manda ningún "pago exitoso".
- **Seguridad = llaves y puertas.** Se prueban las 8 acciones x 5 roles (40 combinaciones). Cuando
  alguien no tiene permiso, además de recibir un rechazo, **no queda ningún cambio** guardado.
- Evidencia: `docs/evidencias/SECCION3_PRUEBA_DE_DEFECTOS.txt` (la prueba de defectos descubrió un hueco
  y se cerró con una prueba nueva) y `SECCION3_pruebas_mocks_y_seguridad.txt`.
