"""Pruebas de integracion con base de datos (SQLite en memoria).

En palabras simples: aqui comprobamos que FitZone GUARDA bien la informacion, que la RECUPERA
igual que la dejo, y que si algo sale mal a mitad de camino NO queda nada a medias
(como una transferencia bancaria: o se hace completa, o no se hace).
"""

import subprocess
import sys
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from src.domain import (
    Capacidad,
    ClaseGrupal,
    ClaseLlena,
    EstadoDeClase,
    EstadoDeReserva,
    Horario,
    Membresia,
    ReglasDeElegibilidad,
)
from src.ports import ConflictoDeVersion
from src.repository import (
    ClaseRow,
    EsperaRow,
    ReservaRow,
    SqlClaseGrupalRepository,
    SqlMembresiaRepository,
    SqlPlanRepository,
    crear_motor,
    crear_tablas,
)


def leer_clase(session_factory, clase_id):
    """Lee una clase con una sesion NUEVA: asi vemos lo que de verdad quedo guardado."""
    sesion = session_factory()
    try:
        return SqlClaseGrupalRepository(sesion).obtener_por_id(clase_id)
    finally:
        sesion.close()


def guardar_y_confirmar(uow, clase):
    with uow:
        uow.clases.guardar(clase)
        uow.confirmar()


# ======================================================================================
# 1. Guardar y recuperar (commit)
# ======================================================================================
class TestGuardarYRecuperar:
    def test_una_clase_confirmada_se_puede_recuperar_igual(self, uow, session_factory, clase_yoga):
        # Arrange + Act: se guarda y se CONFIRMA (commit)
        guardar_y_confirmar(uow, clase_yoga)
        # Assert: una sesion nueva la encuentra con los mismos datos
        recuperada = leer_clase(session_factory, "YOGA-1")
        assert recuperada is not None
        assert recuperada.tipo == "yoga"
        assert recuperada.capacidad.valor == 2
        assert recuperada.horario == clase_yoga.horario
        assert recuperada.estado is EstadoDeClase.PROGRAMADA

    def test_buscar_una_clase_que_no_existe_devuelve_none(self, uow):
        with uow:
            assert uow.clases.obtener_por_id("NO-EXISTE") is None

    def test_se_guardan_junto_con_la_clase_sus_reservas_y_su_lista_de_espera(
        self, uow, session_factory, clase_yoga, socio_ana, socio_beto, recepcion, ahora
    ):
        # Arrange: clase llena y una persona esperando
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.reservar("beto", socio_beto, ahora)
        clase_yoga.unir_a_lista_de_espera("carla", recepcion, ahora)
        # Act
        guardar_y_confirmar(uow, clase_yoga)
        # Assert
        r = leer_clase(session_factory, "YOGA-1")
        assert [x.socio_id for x in r.reservas] == ["ana", "beto"]
        assert r.esta_llena() is True
        assert r.posicion_en_lista("carla") == 1

    def test_el_orden_de_la_lista_de_espera_se_conserva(
        self, uow, session_factory, clase_yoga, socio_ana, socio_beto, recepcion, ahora
    ):
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.reservar("beto", socio_beto, ahora)
        for socio in ["carla", "dani", "eli"]:
            clase_yoga.unir_a_lista_de_espera(socio, recepcion, ahora)
        guardar_y_confirmar(uow, clase_yoga)
        r = leer_clase(session_factory, "YOGA-1")
        assert [e.socio_id for e in r.lista_de_espera] == ["carla", "dani", "eli"]

    def test_cada_persona_en_la_lista_guarda_su_numero_de_posicion(
        self, uow, session_factory, clase_yoga, socio_ana, socio_beto, recepcion, ahora
    ):
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.reservar("beto", socio_beto, ahora)
        for socio in ["carla", "dani", "eli"]:
            clase_yoga.unir_a_lista_de_espera(socio, recepcion, ahora)
        guardar_y_confirmar(uow, clase_yoga)
        with session_factory() as sesion:
            filas = sesion.query(EsperaRow).order_by(EsperaRow.posicion).all()
            assert [(f.socio_id, f.posicion) for f in filas] == [
                ("carla", 1),
                ("dani", 2),
                ("eli", 3),
            ]

    def test_cuando_alguien_sale_de_la_lista_los_demas_suben_de_posicion(
        self, uow, session_factory, clase_yoga, socio_ana, socio_beto, recepcion, ahora
    ):
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.reservar("beto", socio_beto, ahora)
        for socio in ["carla", "dani", "eli"]:
            clase_yoga.unir_a_lista_de_espera(socio, recepcion, ahora)
        guardar_y_confirmar(uow, clase_yoga)
        # Carla sale de la lista (por ahora se simula quitandola; las ofertas llegaran despues)
        with uow:
            clase = uow.clases.obtener_por_id("YOGA-1")
            clase.lista_de_espera.pop(0)
            uow.clases.guardar(clase)
            uow.confirmar()
        r = leer_clase(session_factory, "YOGA-1")
        assert r.posicion_en_lista("dani") == 1
        assert r.posicion_en_lista("eli") == 2
        assert r.posicion_en_lista("carla") is None

    def test_los_cambios_de_estado_se_guardan_al_actualizar(
        self, uow, session_factory, clase_yoga, socio_ana, recepcion, ahora
    ):
        # Arrange: se guarda una clase con la reserva de Ana
        clase_yoga.reservar("ana", socio_ana, ahora)
        guardar_y_confirmar(uow, clase_yoga)
        # Act: se carga, Ana cancela y se vuelve a guardar
        with uow:
            clase = uow.clases.obtener_por_id("YOGA-1")
            clase.cancelar_reserva("ana", socio_ana)
            uow.clases.guardar(clase)
            uow.confirmar()
        # Assert
        r = leer_clase(session_factory, "YOGA-1")
        assert r.reservas[0].estado is EstadoDeReserva.CANCELADA
        assert r.lugares_disponibles() == 2

    def test_quien_sale_de_la_lista_deja_de_aparecer_en_ella(
        self, session_factory, uow, clase_yoga, socio_ana, socio_beto, recepcion, ahora
    ):
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.reservar("beto", socio_beto, ahora)
        clase_yoga.unir_a_lista_de_espera("carla", recepcion, ahora)
        guardar_y_confirmar(uow, clase_yoga)
        # Se simula que Carla ya no esta en la lista (saldra con las ofertas de lugar, mas adelante)
        with uow:
            clase = uow.clases.obtener_por_id("YOGA-1")
            clase.lista_de_espera.clear()
            uow.clases.guardar(clase)
            uow.confirmar()
        assert leer_clase(session_factory, "YOGA-1").lista_de_espera == []

    def test_el_cierre_de_clase_con_no_shows_tambien_se_guarda(
        self, uow, session_factory, clase_yoga, socio_ana, sistema, ahora
    ):
        clase_yoga.reservar("ana", socio_ana, ahora)
        guardar_y_confirmar(uow, clase_yoga)
        with uow:
            clase = uow.clases.obtener_por_id("YOGA-1")
            clase.registrar_no_shows(sistema, clase.horario.fin)
            uow.clases.guardar(clase)
            uow.confirmar()
        assert leer_clase(session_factory, "YOGA-1").reservas[0].estado is EstadoDeReserva.NO_SHOW


# ======================================================================================
# 2. Rollback: "si algo sale mal, no queda nada a medias"
# ======================================================================================
class TestRollback:
    def test_si_se_revierte_no_queda_nada_guardado(self, uow, session_factory, clase_yoga):
        # Act: se guarda pero se REVIERTE (rollback) en lugar de confirmar
        with uow:
            uow.clases.guardar(clase_yoga)
            uow.revertir()
        # Assert: la base de datos sigue vacia
        assert leer_clase(session_factory, "YOGA-1") is None

    def test_si_se_olvida_confirmar_no_se_guarda_nada(self, uow, session_factory, clase_yoga):
        # Seguro por defecto: sin confirmar() explicito, se descarta.
        with uow:
            uow.clases.guardar(clase_yoga)
        assert leer_clase(session_factory, "YOGA-1") is None

    def test_despues_de_revertir_confirmar_ya_no_guarda_lo_descartado(
        self, uow, session_factory, clase_yoga
    ):
        # Si revertir() no deshiciera nada de verdad, el confirmar() posterior lo guardaria.
        with uow:
            uow.clases.guardar(clase_yoga)
            uow.revertir()
            uow.confirmar()
        assert leer_clase(session_factory, "YOGA-1") is None

    def test_un_error_de_negocio_a_mitad_de_la_operacion_deshace_todo(
        self, uow, session_factory, clase_yoga, socio_ana, socio_beto, recepcion, ahora
    ):
        # Arrange: clase de 2 lugares guardada y vacia
        guardar_y_confirmar(uow, clase_yoga)
        # Act: dentro de UNA transaccion se reserva a Ana y Beto (guardando) y luego
        # Carla choca con la clase llena -> ClaseLlena
        with pytest.raises(ClaseLlena):
            with uow:
                clase = uow.clases.obtener_por_id("YOGA-1")
                clase.reservar("ana", socio_ana, ahora)
                clase.reservar("beto", socio_beto, ahora)
                uow.clases.guardar(clase)  # ya "guardado" pero NO confirmado
                clase.reservar("carla", recepcion, ahora)  # <- falla aqui
                uow.confirmar()
        # Assert: ni Ana ni Beto quedaron reservados (todo o nada)
        assert leer_clase(session_factory, "YOGA-1").reservas == []

    def test_lo_confirmado_antes_no_se_pierde_por_un_rollback_posterior(
        self, uow, session_factory, clase_yoga, socio_ana, ahora
    ):
        # Arrange: Ana queda reservada y confirmada
        clase_yoga.reservar("ana", socio_ana, ahora)
        guardar_y_confirmar(uow, clase_yoga)
        # Act: una segunda operacion cancela, guarda y se revierte
        with uow:
            clase = uow.clases.obtener_por_id("YOGA-1")
            clase.cancelar_reserva("ana", socio_ana)
            uow.clases.guardar(clase)
            uow.revertir()
        # Assert: Ana sigue con su reserva ACTIVA
        assert leer_clase(session_factory, "YOGA-1").reservas[0].estado is EstadoDeReserva.ACTIVA


# ======================================================================================
# 3. La base de datos como segunda red de seguridad
# ======================================================================================
class TestRestriccionesDeLaBaseDeDatos:
    """Aunque el dominio ya valida, la base de datos tambien se niega a guardar datos absurdos."""

    @staticmethod
    def _clase_row(**cambios):
        datos = dict(
            clase_id="C1",
            tipo="yoga",
            inicio=__import__("datetime").datetime(2026, 11, 4, 10),
            fin=__import__("datetime").datetime(2026, 11, 4, 11),
            capacidad=5,
            estado="PROGRAMADA",
        )
        datos.update(cambios)
        return ClaseRow(**datos)

    @staticmethod
    def _reserva_row(reserva_id, estado="ACTIVA", socio="ana", orden=0):
        return ReservaRow(
            reserva_id=reserva_id,
            socio_id=socio,
            creada_en=__import__("datetime").datetime(2026, 11, 3, 9),
            estado=estado,
            orden=orden,
        )

    def test_la_base_rechaza_una_capacidad_de_cero(self, session_factory):
        with session_factory() as sesion:
            sesion.add(self._clase_row(capacidad=0))
            with pytest.raises(IntegrityError):
                sesion.flush()

    def test_la_base_rechaza_dos_lugares_vigentes_del_mismo_socio(self, session_factory):
        with session_factory() as sesion:
            clase = self._clase_row()
            clase.reservas = [self._reserva_row("R1", orden=0), self._reserva_row("R2", orden=1)]
            sesion.add(clase)
            with pytest.raises(IntegrityError):
                sesion.flush()

    def test_la_base_permite_reservar_otra_vez_si_la_anterior_fue_cancelada(self, session_factory):
        with session_factory() as sesion:
            clase = self._clase_row()
            clase.reservas = [
                self._reserva_row("R1", estado="CANCELADA", orden=0),
                self._reserva_row("R2", estado="ACTIVA", orden=1),
            ]
            sesion.add(clase)
            sesion.flush()  # no debe lanzar error

    def test_la_base_rechaza_al_mismo_socio_dos_veces_en_la_lista_de_espera(self, session_factory):
        import datetime as dt

        with session_factory() as sesion:
            clase = self._clase_row()
            clase.espera = [
                EsperaRow(socio_id="carla", solicitada_en=dt.datetime(2026, 11, 3), posicion=1),
                EsperaRow(socio_id="carla", solicitada_en=dt.datetime(2026, 11, 3), posicion=2),
            ]
            sesion.add(clase)
            with pytest.raises(IntegrityError):
                sesion.flush()

    def test_la_base_rechaza_una_reserva_de_una_clase_que_no_existe(self, session_factory):
        with session_factory() as sesion:
            huerfana = self._reserva_row("R9")
            huerfana.clase_id = "CLASE-FANTASMA"
            sesion.add(huerfana)
            with pytest.raises(IntegrityError):
                sesion.flush()


# ======================================================================================
# 4. Dos personas piden el ultimo lugar al mismo tiempo (concurrencia)
# ======================================================================================
class TestConcurrenciaOptimista:
    def test_si_dos_personas_editan_la_misma_clase_solo_gana_la_primera(
        self, uow, session_factory, clase_yoga, socio_ana, socio_beto, ahora
    ):
        # Arrange: clase guardada. Dos "ventanillas" (sesiones) la cargan a la vez.
        guardar_y_confirmar(uow, clase_yoga)
        sesion_a, sesion_b = session_factory(), session_factory()
        repo_a, repo_b = SqlClaseGrupalRepository(sesion_a), SqlClaseGrupalRepository(sesion_b)
        clase_a, clase_b = repo_a.obtener_por_id("YOGA-1"), repo_b.obtener_por_id("YOGA-1")

        # Act: A reserva y confirma primero
        clase_a.reservar("ana", socio_ana, ahora)
        repo_a.guardar(clase_a)
        sesion_a.commit()
        # B, que miraba una version vieja, intenta guardar su cambio
        clase_b.reservar("beto", socio_beto, ahora)
        with pytest.raises(ConflictoDeVersion):
            repo_b.guardar(clase_b)
        sesion_b.rollback()
        sesion_a.close()
        sesion_b.close()

        # Assert: solo quedo la reserva de Ana
        r = leer_clase(session_factory, "YOGA-1")
        assert [x.socio_id for x in r.reservas] == ["ana"]

    def test_despues_de_un_conflicto_se_puede_reintentar_con_datos_frescos(
        self, uow, session_factory, clase_yoga, socio_ana, socio_beto, ahora
    ):
        guardar_y_confirmar(uow, clase_yoga)
        sesion_a, sesion_b = session_factory(), session_factory()
        repo_a, repo_b = SqlClaseGrupalRepository(sesion_a), SqlClaseGrupalRepository(sesion_b)
        clase_a, clase_b = repo_a.obtener_por_id("YOGA-1"), repo_b.obtener_por_id("YOGA-1")
        clase_a.reservar("ana", socio_ana, ahora)
        repo_a.guardar(clase_a)
        sesion_a.commit()
        clase_b.reservar("beto", socio_beto, ahora)
        with pytest.raises(ConflictoDeVersion):
            repo_b.guardar(clase_b)
        sesion_b.rollback()
        sesion_a.close()
        sesion_b.close()

        # Reintento: ahora Beto trabaja con la clase actualizada (con Ana ya dentro)
        with uow:
            clase = uow.clases.obtener_por_id("YOGA-1")
            clase.reservar("beto", socio_beto, ahora)
            uow.clases.guardar(clase)
            uow.confirmar()
        r = leer_clase(session_factory, "YOGA-1")
        assert [x.socio_id for x in r.reservas] == ["ana", "beto"]

    def test_la_capacidad_nunca_se_supera_aunque_se_llene_poco_a_poco(
        self, uow, session_factory, clase_yoga, socio_ana, socio_beto, recepcion, ahora
    ):
        # Tres solicitudes sucesivas, cada una en su propia transaccion, para 2 lugares.
        guardar_y_confirmar(uow, clase_yoga)
        resultados = []
        for socio_id, actor in [("ana", socio_ana), ("beto", socio_beto), ("carla", recepcion)]:
            try:
                with uow:
                    clase = uow.clases.obtener_por_id("YOGA-1")
                    clase.reservar(socio_id, actor, ahora)
                    uow.clases.guardar(clase)
                    uow.confirmar()
                resultados.append("reservada")
            except ClaseLlena:
                resultados.append("rechazada")
        assert resultados == ["reservada", "reservada", "rechazada"]
        assert len(leer_clase(session_factory, "YOGA-1").reservas) == 2


# ======================================================================================
# 5. Membresias y planes (solo lectura para el sistema)
# ======================================================================================
class TestMembresiasYPlanes:
    def test_un_plan_se_recupera_con_sus_tipos_de_clase(self, session_factory, plan_premium):
        with session_factory() as sesion:
            SqlPlanRepository(sesion).agregar(plan_premium)
            sesion.commit()
        with session_factory() as sesion:
            plan = SqlPlanRepository(sesion).obtener_por_id("PREMIUM")
        assert plan == plan_premium
        assert plan.incluye("yoga") is True

    def test_un_plan_sin_clases_grupales_se_recupera_vacio(self, session_factory, plan_basico):
        with session_factory() as sesion:
            SqlPlanRepository(sesion).agregar(plan_basico)
            sesion.commit()
        with session_factory() as sesion:
            plan = SqlPlanRepository(sesion).obtener_por_id("BASICO")
        assert plan.tipos_de_clase == frozenset()

    def test_un_plan_inexistente_devuelve_none(self, session_factory):
        with session_factory() as sesion:
            assert SqlPlanRepository(sesion).obtener_por_id("XYZ") is None

    def test_una_membresia_suspendida_se_recupera_como_suspendida(
        self, session_factory, plan_premium, ahora
    ):
        suspendida = Membresia(
            "ana", "PREMIUM", ahora - timedelta(days=5), ahora + timedelta(days=5), suspendida=True
        )
        with session_factory() as sesion:
            SqlPlanRepository(sesion).agregar(plan_premium)
            SqlMembresiaRepository(sesion).agregar(suspendida)
            sesion.commit()
        with session_factory() as sesion:
            recuperada = SqlMembresiaRepository(sesion).obtener_actual_del_socio("ana")
        assert recuperada == suspendida
        assert recuperada.esta_vigente_en(ahora) is False

    def test_un_socio_sin_membresia_devuelve_none(self, session_factory):
        with session_factory() as sesion:
            assert SqlMembresiaRepository(sesion).obtener_actual_del_socio("nadie") is None

    def test_la_base_no_acepta_una_membresia_de_un_plan_que_no_existe(self, session_factory, ahora):
        huerfana = Membresia("ana", "PLAN-FANTASMA", ahora, ahora + timedelta(days=30))
        with session_factory() as sesion:
            with pytest.raises(IntegrityError):
                SqlMembresiaRepository(sesion).agregar(huerfana)


# ======================================================================================
# 6. Consulta de clases por cerrar
# ======================================================================================
class TestClasesTerminadasSinCierre:
    def test_solo_aparecen_clases_terminadas_con_reservas_activas(
        self, uow, clase_yoga, socio_ana, ahora
    ):
        clase_yoga.reservar("ana", socio_ana, ahora)
        guardar_y_confirmar(uow, clase_yoga)
        with uow:
            antes = uow.clases.obtener_clases_terminadas_sin_cierre(
                clase_yoga.horario.fin - timedelta(seconds=1)
            )
            despues = uow.clases.obtener_clases_terminadas_sin_cierre(clase_yoga.horario.fin)
        assert antes == []
        assert [c.clase_id for c in despues] == ["YOGA-1"]

    def test_una_clase_ya_cerrada_no_vuelve_a_aparecer(
        self, uow, clase_yoga, socio_ana, sistema, ahora
    ):
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.registrar_no_shows(sistema, clase_yoga.horario.fin)
        guardar_y_confirmar(uow, clase_yoga)
        with uow:
            assert uow.clases.obtener_clases_terminadas_sin_cierre(clase_yoga.horario.fin) == []


# ======================================================================================
# 7. Todo junto: reglas de negocio + base de datos
# ======================================================================================
class TestFlujoCompletoConBaseDeDatos:
    def test_reservar_validando_membresia_plan_y_cupo_con_datos_guardados(
        self, uow, session_factory, plan_premium, membresia_vigente, clase_yoga, socio_ana, ahora
    ):
        # Arrange: se cargan plan, membresia y clase en la base
        with uow:
            uow.planes.agregar(plan_premium)
            uow.membresias.agregar(membresia_vigente)
            uow.clases.guardar(clase_yoga)
            uow.confirmar()
        # Act: flujo del caso de uso CU-01 leyendo TODO desde la base
        with uow:
            membresia = uow.membresias.obtener_actual_del_socio("ana")
            plan = uow.planes.obtener_por_id(membresia.plan_id)
            clase = uow.clases.obtener_por_id("YOGA-1")
            ReglasDeElegibilidad().evaluar(membresia, plan, clase, ahora).exigir()
            clase.reservar("ana", socio_ana, ahora)
            uow.clases.guardar(clase)
            uow.confirmar()
        # Assert
        r = leer_clase(session_factory, "YOGA-1")
        assert r.reservas[0].socio_id == "ana"
        assert r.lugares_disponibles() == 1

    def test_la_clase_con_capacidad_y_horario_se_reconstruye_con_sus_reglas_activas(
        self, uow, session_factory, ahora
    ):
        # Lo que se recupera no es "datos sueltos": sigue protegiendo sus reglas.
        clase = ClaseGrupal(
            "BOX-1", "box", Horario(ahora, ahora + timedelta(hours=1)), Capacidad(1)
        )
        guardar_y_confirmar(uow, clase)
        recuperada = leer_clase(session_factory, "BOX-1")
        assert recuperada.lugares_disponibles() == 1
        assert isinstance(recuperada.capacidad, Capacidad)


# ======================================================================================
# 8. Arquitectura: el dominio no depende de la base de datos
# ======================================================================================
def test_el_dominio_no_importa_sqlalchemy():
    """Importa SOLO el dominio en un proceso limpio y confirma que SQLAlchemy no se cargo."""
    codigo = "import sys, src.domain; sys.exit(1 if 'sqlalchemy' in sys.modules else 0)"
    resultado = subprocess.run([sys.executable, "-c", codigo], capture_output=True)
    assert resultado.returncode == 0, "el dominio no debe depender de SQLAlchemy"


def test_se_guarda_ClaseRow_con_version_inicial_y_sube_al_actualizar(
    uow, session_factory, clase_yoga, socio_ana, ahora
):
    guardar_y_confirmar(uow, clase_yoga)
    with session_factory() as sesion:
        assert sesion.get(ClaseRow, "YOGA-1").version == 1
    with uow:
        clase = uow.clases.obtener_por_id("YOGA-1")
        clase.reservar("ana", socio_ana, ahora)
        uow.clases.guardar(clase)
        uow.confirmar()
    with session_factory() as sesion:
        assert sesion.get(ClaseRow, "YOGA-1").version == 2


def test_los_datos_sobreviven_aunque_se_cierre_y_se_vuelva_a_abrir_la_base(
    tmp_path, clase_yoga, socio_ana, ahora
):
    """Con una base en ARCHIVO temporal: se guarda, se 'apaga' todo y se vuelve a abrir."""
    from sqlalchemy.orm import sessionmaker

    from src.repository import SqlAlchemyUnitOfWork

    url = f"sqlite:///{tmp_path / 'fitzone_prueba.db'}"
    motor1 = crear_motor(url)
    crear_tablas(motor1)
    clase_yoga.reservar("ana", socio_ana, ahora)
    guardar_y_confirmar(SqlAlchemyUnitOfWork(sessionmaker(bind=motor1)), clase_yoga)
    motor1.dispose()  # "se apaga el sistema"

    motor2 = crear_motor(url)  # "se enciende de nuevo"
    recuperada = leer_clase(sessionmaker(bind=motor2), "YOGA-1")
    motor2.dispose()
    assert [r.socio_id for r in recuperada.reservas] == ["ana"]
