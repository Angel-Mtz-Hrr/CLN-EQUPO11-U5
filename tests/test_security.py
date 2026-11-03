"""Seguridad de negocio: ¿cada persona puede hacer SOLO lo que su rol le permite?

Piensa en las llaves de un edificio: el Administrador tiene la llave maestra de la direccion,
Recepcion abre el mostrador y las reservas, y un Socio solo abre "su" puerta.
Aqui probamos CADA llave contra CADA puerta, incluidas las puertas que deben seguir cerradas,
y comprobamos que un intento no autorizado NO deja ningun cambio (nada se cancela, nada se guarda).

Reglas cubiertas (segun los comentarios del dominio y del Informe del equipo):
  BR-01  Solo el Administrador cancela clases.
  BR-03  Recepcion gestiona reservas de cualquier socio; un socio, solo las suyas.
  BR-04  El sistema NO modifica membresias (FitZone las administra por otro lado).
  BR-05  Solo el Administrador fija la capacidad.
  US-19  Solo Recepcion registra asistencia.     BR-08: solo el Sistema cierra la clase.
"""

import copy
import inspect

import pytest

from src.domain import (
    Actor,
    Capacidad,
    EstadoDeClase,
    PermisoDenegado,
    Rol,
)
from src.ports import MembresiaRepository
from src.servicios import ServicioDeReservas

# ---------------------------------------------------------------------------------------
# La "tabla de llaves": para cada accion, que roles SI pueden. Todo lo demas debe fallar.
# ---------------------------------------------------------------------------------------

R = Rol
QUIEN_PUEDE = {
    # accion: roles autorizados
    "reservar_su_propio_lugar": {R.SOCIO, R.RECEPCION},  # BR-03
    "reservar_por_otro_socio": {R.RECEPCION},  # BR-03
    "cancelar_su_propia_reserva": {R.SOCIO, R.RECEPCION},  # BR-03
    "cancelar_la_reserva_de_otro": {R.RECEPCION},  # BR-03
    "cancelar_una_clase": {R.ADMINISTRADOR},  # BR-01
    "fijar_capacidad": {R.ADMINISTRADOR},  # BR-05
    "registrar_asistencia": {R.RECEPCION},  # US-19
    "cerrar_clase_no_shows": {R.SISTEMA},  # BR-08
}


def _ejecutar(accion, clase, rol, ahora):
    """Hace la accion como un actor de ese rol. Ana es la socia con reserva; Carla no."""
    if accion == "reservar_su_propio_lugar":
        return clase.reservar("carla", Actor("carla", rol), ahora)
    if accion == "reservar_por_otro_socio":
        return clase.reservar("carla", Actor("alguien-mas", rol), ahora)
    if accion == "cancelar_su_propia_reserva":
        return clase.cancelar_reserva("ana", Actor("ana", rol))
    if accion == "cancelar_la_reserva_de_otro":
        return clase.cancelar_reserva("ana", Actor("alguien-mas", rol))
    if accion == "cancelar_una_clase":
        return clase.cancelar(Actor("x", rol))
    if accion == "fijar_capacidad":
        return clase.configurar_capacidad(Capacidad(10), Actor("x", rol))
    if accion == "registrar_asistencia":
        return clase.registrar_asistencia("ana", Actor("x", rol))
    if accion == "cerrar_clase_no_shows":
        return clase.registrar_no_shows(Actor("x", rol), clase.horario.fin)
    raise AssertionError(f"accion desconocida: {accion}")


# Una fila por cada combinacion accion x rol: 8 acciones x 5 roles = 40 casos.
TODAS_LAS_COMBINACIONES = [
    (accion, rol, rol in autorizados)
    for accion, autorizados in QUIEN_PUEDE.items()
    for rol in Rol
]


@pytest.fixture
def clase_con_ana(clase_yoga, recepcion, ahora):
    """Clase de yoga (2 lugares) donde Ana ya tiene su reserva."""
    clase_yoga.reservar("ana", recepcion, ahora)
    return clase_yoga


class TestMatrizDePermisos:
    @pytest.mark.parametrize(
        "accion, rol, permitido",
        TODAS_LAS_COMBINACIONES,
        ids=[f"{a}-{r.value}-{'SI' if p else 'NO'}" for a, r, p in TODAS_LAS_COMBINACIONES],
    )
    def test_cada_rol_hace_solo_lo_que_le_corresponde(
        self, clase_con_ana, accion, rol, permitido, ahora
    ):
        # Arrange: foto de la clase ANTES del intento
        antes = copy.deepcopy(clase_con_ana)

        if permitido:
            # Act + Assert: la llave abre la puerta (no se rechaza por permisos)
            _ejecutar(accion, clase_con_ana, rol, ahora)
            assert clase_con_ana != antes, "la accion permitida debia producir un cambio"
        else:
            # Act + Assert: la llave NO abre y, ademas, NO queda ningun cambio
            with pytest.raises(PermisoDenegado):
                _ejecutar(accion, clase_con_ana, rol, ahora)
            assert clase_con_ana == antes, "un intento sin permiso no debe cambiar nada"


class TestCasosEspecialesDeSocio:
    """Un socio es el unico rol cuyo permiso depende de QUIEN es (solo lo suyo)."""

    def test_un_socio_reserva_para_si_mismo(self, clase_yoga, ahora):
        assert clase_yoga.reservar("ana", Actor("ana", Rol.SOCIO), ahora).socio_id == "ana"

    def test_un_socio_no_reserva_para_otro_aunque_se_apellide_parecido(self, clase_yoga, ahora):
        # Caso LIMITE: identificadores casi iguales no deben confundirse.
        with pytest.raises(PermisoDenegado):
            clase_yoga.reservar("ana", Actor("ana2", Rol.SOCIO), ahora)

    def test_un_socio_no_cancela_la_reserva_de_otro_socio(self, clase_con_ana, socio_beto):
        with pytest.raises(PermisoDenegado):
            clase_con_ana.cancelar_reserva("ana", socio_beto)

    def test_el_administrador_no_gestiona_reservas_de_socios(
        self, clase_yoga, administrador, ahora
    ):
        # Hoy las reservas son cosa de Socio y Recepcion (BR-03). Esta prueba deja constancia.
        with pytest.raises(PermisoDenegado):
            clase_yoga.reservar("ana", administrador, ahora)


class TestPermisosDeCobro:
    @pytest.mark.parametrize(
        "rol, actor_id, socio, esperado",
        [
            (Rol.SOCIO, "ana", "ana", True),  # paga lo suyo
            (Rol.SOCIO, "beto", "ana", False),  # no paga por otro
            (Rol.RECEPCION, "rec-1", "ana", True),  # Recepcion cobra a cualquiera
            (Rol.ADMINISTRADOR, "admin-1", "ana", False),
            (Rol.INSTRUCTOR, "inst-1", "ana", False),
            (Rol.SISTEMA, "sistema", "ana", False),
        ],
    )
    def test_quien_puede_cobrar_a_un_socio(self, rol, actor_id, socio, esperado):
        assert Actor(actor_id, rol).puede_gestionar_pago_de(socio) is esperado


class TestBR04LasMembresiasSoloSeConsultan:
    def test_el_contrato_de_membresias_solo_ofrece_consultar(self):
        # Todas las operaciones publicas que el sistema conoce sobre membresias:
        operaciones = {
            nombre
            for nombre, _ in inspect.getmembers(MembresiaRepository, inspect.isfunction)
            if not nombre.startswith("_")
        }
        assert operaciones == {"obtener_actual_del_socio"}  # solo lectura

    def test_reservar_no_altera_la_membresia_del_socio(
        self, uow, plan_premium, membresia_vigente, clase_yoga, notificador_falso, ahora
    ):
        with uow:
            uow.planes.agregar(plan_premium)
            uow.membresias.agregar(membresia_vigente)
            uow.clases.guardar(clase_yoga)
            uow.confirmar()

        ServicioDeReservas(uow, notificador_falso).reservar(
            "YOGA-1", "ana", Actor("ana", Rol.SOCIO), ahora
        )

        with uow:
            assert uow.membresias.obtener_actual_del_socio("ana") == membresia_vigente


class TestIntentosNoAutorizadosNoDejanRastro:
    """Con la base de datos real (en memoria): un rechazo por permisos no guarda nada."""

    @pytest.fixture
    def servicio(self, uow, plan_premium, membresia_vigente, clase_yoga, notificador_falso):
        with uow:
            uow.planes.agregar(plan_premium)
            uow.membresias.agregar(membresia_vigente)
            uow.clases.guardar(clase_yoga)
            uow.confirmar()
        return ServicioDeReservas(uow, notificador_falso)

    def test_un_socio_no_puede_reservar_por_otro_y_la_base_queda_igual(
        self, servicio, uow, socio_beto, ahora
    ):
        with pytest.raises(PermisoDenegado):
            servicio.reservar("YOGA-1", "ana", socio_beto, ahora)
        with uow:
            assert uow.clases.obtener_por_id("YOGA-1").reservas == []

    @pytest.mark.parametrize("actor_fixture", ["recepcion", "instructor", "socio_ana", "sistema"])
    def test_solo_el_administrador_cancela_clases_y_la_base_lo_confirma(
        self, servicio, uow, actor_fixture, request
    ):
        actor = request.getfixturevalue(actor_fixture)
        with pytest.raises(PermisoDenegado):
            servicio.cancelar_clase("YOGA-1", actor)
        with uow:
            assert uow.clases.obtener_por_id("YOGA-1").estado is EstadoDeClase.PROGRAMADA
