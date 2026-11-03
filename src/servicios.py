"""Servicios de aplicacion: coordinan reglas (dominio), base de datos y avisos/cobros externos.

Idea clave para entender este archivo, sin tecnicismos:

  1. PRIMERO se decide y se GUARDA lo importante (la reserva, la cancelacion).
  2. DESPUES se avisa al socio. Un aviso que falla NO deshace una reserva ya confirmada:
     es mejor que el socio tenga su lugar y no reciba el correo, a que pierda su lugar
     porque el correo estaba caido.
  3. Un COBRO es distinto: si el banco rechaza, no hay nada que avisar como exito.

Los servicios externos (Notificador, PasarelaDePago) llegan "de afuera": en produccion son
reales; en las pruebas son dobles (mocks) que no envian ni cobran nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain import (
    Actor,
    EstadoDeReserva,
    MembresiaNoVigente,
    PermisoDenegado,
    ReglaDeNegocioError,
    ReglasDeElegibilidad,
)
from src.ports import (
    Notificador,
    PasarelaDePago,
    ServicioExternoNoDisponible,
    UnitOfWork,
)


class ClaseNoEncontrada(ReglaDeNegocioError):
    """La clase que se pidio no existe."""


class MontoInvalido(ReglaDeNegocioError):
    """El monto a cobrar debe ser mayor que cero."""


@dataclass(frozen=True)
class ResultadoDeReserva:
    reserva_id: str
    aviso_enviado: bool  # False = el lugar esta asegurado, pero el aviso no pudo salir


@dataclass(frozen=True)
class ResultadoDeCancelacion:
    avisados: tuple[str, ...]
    sin_aviso: tuple[str, ...]  # socios a quienes hay que avisar por otro medio


@dataclass(frozen=True)
class ResultadoDeCobro:
    comprobante: str
    aviso_enviado: bool


def _avisar(notificador: Notificador, socio_id: str, mensaje: str) -> bool:
    """Intenta avisar. Si el servicio de avisos esta caido, lo reporta sin romper nada."""
    try:
        notificador.enviar(socio_id, mensaje)
    except ServicioExternoNoDisponible:
        return False
    return True


class ServicioDeReservas:
    def __init__(self, uow: UnitOfWork, notificador: Notificador):
        self._uow = uow
        self._notificador = notificador

    def reservar(
        self, clase_id: str, socio_id: str, actor: Actor, ahora: datetime
    ) -> ResultadoDeReserva:
        # Primero el permiso (BR-03): a quien no puede, ni siquiera se le consulta la base.
        if not actor.puede_gestionar_reserva_de(socio_id):
            raise PermisoDenegado("este rol no puede reservar en nombre de ese socio")

        with self._uow as uow:
            clase = uow.clases.obtener_por_id(clase_id)
            if clase is None:
                raise ClaseNoEncontrada(f"no existe la clase {clase_id}")
            membresia = uow.membresias.obtener_actual_del_socio(socio_id)
            if membresia is None:
                raise MembresiaNoVigente("el socio no tiene membresia")
            plan = uow.planes.obtener_por_id(membresia.plan_id)
            ReglasDeElegibilidad().evaluar(membresia, plan, clase, ahora).exigir()  # BR-06, BR-07
            reserva = clase.reservar(socio_id, actor, ahora)  # BR-05 (cupo)
            uow.clases.guardar(clase)
            uow.confirmar()

        aviso = _avisar(
            self._notificador,
            socio_id,
            f"Tu lugar en la clase de {clase.tipo} ({clase.clase_id}) quedo confirmado.",
        )
        return ResultadoDeReserva(reserva.reserva_id, aviso)

    def cancelar_clase(self, clase_id: str, actor: Actor) -> ResultadoDeCancelacion:
        if not actor.puede_administrar_clases():  # BR-01
            raise PermisoDenegado("solo el Administrador puede cancelar una clase")

        with self._uow as uow:
            clase = uow.clases.obtener_por_id(clase_id)
            if clase is None:
                raise ClaseNoEncontrada(f"no existe la clase {clase_id}")
            afectados = [r.socio_id for r in clase.reservas if r.estado is EstadoDeReserva.ACTIVA]
            clase.cancelar(actor)
            uow.clases.guardar(clase)
            uow.confirmar()

        avisados, sin_aviso = [], []
        for socio_id in afectados:  # un aviso fallido no impide avisar a los demas
            ok = _avisar(
                self._notificador,
                socio_id,
                f"Lamentamos avisarte que la clase de {clase.tipo} ({clase.clase_id}) se cancelo.",
            )
            (avisados if ok else sin_aviso).append(socio_id)
        return ResultadoDeCancelacion(tuple(avisados), tuple(sin_aviso))


class ServicioDePagos:
    """Cobros a traves de la pasarela de pago (en pruebas: un doble que NO cobra)."""

    def __init__(self, pasarela: PasarelaDePago, notificador: Notificador):
        self._pasarela = pasarela
        self._notificador = notificador

    def cobrar(
        self, socio_id: str, monto_centavos: int, concepto: str, actor: Actor
    ) -> ResultadoDeCobro:
        if not actor.puede_gestionar_pago_de(socio_id):
            raise PermisoDenegado("este rol no puede cobrar a ese socio")
        if monto_centavos <= 0:
            raise MontoInvalido("el monto debe ser mayor que cero")

        # Un solo intento, sin reintentos automaticos: asi jamas se cobra dos veces por error.
        # Si la pasarela rechaza (PagoRechazado) o no responde, el error sube tal cual y
        # NO se manda ningun aviso de "pago exitoso".
        comprobante = self._pasarela.cobrar(socio_id, monto_centavos, concepto)

        mensaje = f"Recibimos tu pago por {concepto}. Comprobante {comprobante}."
        aviso = _avisar(self._notificador, socio_id, mensaje)
        return ResultadoDeCobro(comprobante, aviso)
