"""Dominio de FitZone: las reglas del gimnasio, escritas en el lenguaje del negocio.

Este archivo NO sabe nada de bases de datos, pantallas, correos ni cobros. Solo contiene
las reglas del BRD (BR-01 a BR-08) y las invariantes del Informe de Arquitectura (INV-1 a INV-8).
Por eso se puede probar de forma rapida y sin instalar nada extra.

Convencion de fechas: todas las fechas son "ingenuas" (sin zona horaria) y se reciben como
parametro (`ahora`). El dominio nunca consulta el reloj por su cuenta: asi las pruebas
siempre dan el mismo resultado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# --------------------------------------------------------------------------------------
# Errores del negocio: cada uno explica, en palabras del negocio, por que se rechazo algo
# --------------------------------------------------------------------------------------


class ReglaDeNegocioError(Exception):
    """Base de todos los rechazos del negocio (no son fallas tecnicas)."""


class MembresiaNoVigente(ReglaDeNegocioError):
    """BR-06: la membresia esta vencida o suspendida."""


class ClaseFueraDelPlan(ReglaDeNegocioError):
    """BR-07: el plan del socio no incluye este tipo de clase."""


class ClaseLlena(ReglaDeNegocioError):
    """BR-05: ya no hay lugares disponibles."""


class ReservaDuplicada(ReglaDeNegocioError):
    """INV-4: el socio ya tiene un lugar en esta clase."""


class ClaseNoProgramada(ReglaDeNegocioError):
    """INV-2: solo se reserva en una clase que sigue programada."""


class ListaDeEsperaNoPermitida(ReglaDeNegocioError):
    """INV-3: la lista de espera solo se usa cuando la clase esta llena."""


class ReservaNoEncontrada(ReglaDeNegocioError):
    """El socio no tiene una reserva activa en esta clase."""


class CapacidadInvalida(ReglaDeNegocioError):
    """INV-8 / INV-1: la capacidad debe ser mayor que cero y no menor a los lugares ocupados."""


class HorarioInvalido(ReglaDeNegocioError):
    """El inicio de una clase debe ser anterior a su fin."""


class ClaseNoHaTerminado(ReglaDeNegocioError):
    """BR-08: los no-shows solo se registran cuando termina el horario de la clase."""


class PermisoDenegado(ReglaDeNegocioError):
    """BR-01 a BR-04: el rol de quien actua no tiene permiso para esta accion."""


# --------------------------------------------------------------------------------------
# Roles y actores (quien hace que)
# --------------------------------------------------------------------------------------


class Rol(Enum):
    SOCIO = "SOCIO"
    RECEPCION = "RECEPCION"
    INSTRUCTOR = "INSTRUCTOR"
    ADMINISTRADOR = "ADMINISTRADOR"
    SISTEMA = "SISTEMA"


@dataclass(frozen=True)
class Actor:
    """Quien ejecuta una accion, junto con su rol."""

    actor_id: str
    rol: Rol

    def puede_gestionar_reserva_de(self, socio_id: str) -> bool:
        """BR-03: Recepcion gestiona reservas de cualquier socio; un socio, solo las suyas."""
        if self.rol is Rol.RECEPCION:
            return True
        return self.rol is Rol.SOCIO and self.actor_id == socio_id

    def puede_gestionar_pago_de(self, socio_id: str) -> bool:
        """Pagos: igual que las reservas (Recepcion cobra a cualquiera; un socio, lo suyo)."""
        return self.puede_gestionar_reserva_de(socio_id)

    def puede_administrar_clases(self) -> bool:
        """BR-01 y BR-05: solo el Administrador cancela clases o fija su capacidad."""
        return self.rol is Rol.ADMINISTRADOR

    def puede_registrar_asistencia(self) -> bool:
        """US-19: registrar asistencia es trabajo de Recepcion."""
        return self.rol is Rol.RECEPCION

    def es_sistema(self) -> bool:
        return self.rol is Rol.SISTEMA


# --------------------------------------------------------------------------------------
# Value Objects (valores pequenos que se protegen a si mismos)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Capacidad:
    """Maximo de socios en una clase. Siempre mayor que cero (INV-8)."""

    valor: int

    def __post_init__(self):
        if self.valor <= 0:
            raise CapacidadInvalida("la capacidad debe ser mayor que cero")


@dataclass(frozen=True)
class Horario:
    """Inicio y fin de una clase. El inicio siempre es anterior al fin."""

    inicio: datetime
    fin: datetime

    def __post_init__(self):
        if self.inicio >= self.fin:
            raise HorarioInvalido("el inicio debe ser anterior al fin")


class MotivoDeRechazo(Enum):
    MEMBRESIA_NO_VIGENTE = "MEMBRESIA_NO_VIGENTE"
    CLASE_FUERA_DEL_PLAN = "CLASE_FUERA_DEL_PLAN"


@dataclass(frozen=True)
class ResultadoDeElegibilidad:
    """Respuesta a: ¿este socio puede reservar esta clase? Si no, dice el motivo."""

    elegible: bool
    motivo: MotivoDeRechazo | None = None

    def exigir(self) -> None:
        """Lanza el error de negocio correspondiente si el socio no es elegible."""
        if self.motivo is MotivoDeRechazo.MEMBRESIA_NO_VIGENTE:
            raise MembresiaNoVigente("la membresia esta vencida o suspendida")
        if self.motivo is MotivoDeRechazo.CLASE_FUERA_DEL_PLAN:
            raise ClaseFueraDelPlan("la clase no esta incluida en el plan; sugiere actualizar plan")


# --------------------------------------------------------------------------------------
# Membresias y planes (BR-06, BR-07)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanDeMembresia:
    """Nivel de membresia: define que tipos de clase estan incluidos (BR-07)."""

    plan_id: str
    nombre: str
    tipos_de_clase: frozenset[str]

    def incluye(self, tipo_de_clase: str) -> bool:
        return tipo_de_clase in self.tipos_de_clase


@dataclass(frozen=True)
class Membresia:
    """Suscripcion de un socio. Vigente = dentro de su periodo y sin suspension (BR-06).

    El dia del vencimiento (inclusive) todavia cuenta como vigente.
    """

    socio_id: str
    plan_id: str
    inicio: datetime
    vencimiento: datetime
    suspendida: bool = False

    def esta_vigente_en(self, instante: datetime) -> bool:
        if self.suspendida:
            return False
        return self.inicio <= instante <= self.vencimiento


# --------------------------------------------------------------------------------------
# Reservas y clases (BR-05, BR-08 y las invariantes INV-1 a INV-8)
# --------------------------------------------------------------------------------------


class EstadoDeReserva(Enum):
    ACTIVA = "ACTIVA"
    CANCELADA = "CANCELADA"
    ASISTIDA = "ASISTIDA"
    NO_SHOW = "NO_SHOW"


class EstadoDeClase(Enum):
    PROGRAMADA = "PROGRAMADA"
    CANCELADA = "CANCELADA"


@dataclass
class Reserva:
    reserva_id: str
    socio_id: str
    creada_en: datetime
    estado: EstadoDeReserva = EstadoDeReserva.ACTIVA


@dataclass(frozen=True)
class EntradaDeListaDeEspera:
    socio_id: str
    solicitada_en: datetime


class ReglasDeElegibilidad:
    """Servicio de dominio: junta membresia + plan + clase (tres conceptos distintos).

    Orden de revision (igual que los gateways del BPMN-1): primero vigencia, luego plan.
    """

    def evaluar(
        self,
        membresia: Membresia,
        plan: PlanDeMembresia,
        clase: ClaseGrupal,
        ahora: datetime,
    ) -> ResultadoDeElegibilidad:
        if not membresia.esta_vigente_en(ahora):
            return ResultadoDeElegibilidad(False, MotivoDeRechazo.MEMBRESIA_NO_VIGENTE)
        if not plan.incluye(clase.tipo):
            return ResultadoDeElegibilidad(False, MotivoDeRechazo.CLASE_FUERA_DEL_PLAN)
        return ResultadoDeElegibilidad(True)


@dataclass
class ClaseGrupal:
    """Una sesion con horario, tipo y capacidad. Es la "raiz" que protege el cupo.

    Contiene sus reservas y su lista de espera, de modo que el cupo nunca se pueda
    superar aunque lleguen muchas solicitudes (INV-1).
    """

    clase_id: str
    tipo: str
    horario: Horario
    capacidad: Capacidad
    estado: EstadoDeClase = EstadoDeClase.PROGRAMADA
    reservas: list[Reserva] = field(default_factory=list)
    lista_de_espera: list[EntradaDeListaDeEspera] = field(default_factory=list)

    # ---- consultas -------------------------------------------------------------------

    def lugares_ocupados(self) -> int:
        """Ocupan lugar las reservas activas y las ya asistidas."""
        return sum(
            1
            for r in self.reservas
            if r.estado in (EstadoDeReserva.ACTIVA, EstadoDeReserva.ASISTIDA)
        )

    def lugares_disponibles(self) -> int:
        return self.capacidad.valor - self.lugares_ocupados()

    def esta_llena(self) -> bool:
        return self.lugares_disponibles() <= 0

    def posicion_en_lista(self, socio_id: str) -> int | None:
        for posicion, entrada in enumerate(self.lista_de_espera, start=1):
            if entrada.socio_id == socio_id:
                return posicion
        return None

    # ---- ayudantes internos (evitan repetir la misma comprobacion) -------------------

    def _tiene_lugar_vigente(self, socio_id: str) -> bool:
        """¿El socio ya tiene un lugar en esta clase (reserva activa o ya asistida)?"""
        return any(
            r.socio_id == socio_id
            and r.estado in (EstadoDeReserva.ACTIVA, EstadoDeReserva.ASISTIDA)
            for r in self.reservas
        )

    def _reserva_activa_de(self, socio_id: str) -> Reserva:
        """Busca la reserva activa del socio o lanza ReservaNoEncontrada."""
        for reserva in self.reservas:
            if reserva.socio_id == socio_id and reserva.estado is EstadoDeReserva.ACTIVA:
                return reserva
        raise ReservaNoEncontrada("el socio no tiene una reserva activa en esta clase")

    # ---- acciones del socio / recepcion ----------------------------------------------

    def reservar(self, socio_id: str, actor: Actor, ahora: datetime) -> Reserva:
        """Aparta un lugar. Valida permiso (BR-03), clase programada (INV-2) y cupo (BR-05)."""
        if not actor.puede_gestionar_reserva_de(socio_id):
            raise PermisoDenegado("este rol no puede reservar en nombre de ese socio")
        if self.estado is not EstadoDeClase.PROGRAMADA:
            raise ClaseNoProgramada("la clase ya no esta programada")
        if self._tiene_lugar_vigente(socio_id):
            raise ReservaDuplicada("el socio ya tiene un lugar en esta clase")
        if self.esta_llena():
            raise ClaseLlena("la clase alcanzo su capacidad maxima")
        reserva = Reserva(f"{self.clase_id}-R{len(self.reservas) + 1}", socio_id, ahora)
        self.reservas.append(reserva)
        return reserva

    def cancelar_reserva(self, socio_id: str, actor: Actor) -> Reserva:
        """Libera el lugar del socio. Recepcion puede hacerlo por el (BR-03)."""
        if not actor.puede_gestionar_reserva_de(socio_id):
            raise PermisoDenegado("este rol no puede cancelar la reserva de ese socio")
        reserva = self._reserva_activa_de(socio_id)
        reserva.estado = EstadoDeReserva.CANCELADA
        return reserva

    def unir_a_lista_de_espera(self, socio_id: str, actor: Actor, ahora: datetime) -> int:
        """Pone al socio al final de la lista y devuelve su posicion (INV-3, US-05)."""
        if not actor.puede_gestionar_reserva_de(socio_id):
            raise PermisoDenegado("este rol no puede apuntar a ese socio en la lista")
        if self.estado is not EstadoDeClase.PROGRAMADA:
            raise ClaseNoProgramada("la clase ya no esta programada")
        if not self.esta_llena():
            raise ListaDeEsperaNoPermitida("aun hay lugares: conviene reservar directamente")
        if self._tiene_lugar_vigente(socio_id):
            raise ReservaDuplicada("el socio ya tiene un lugar en esta clase")
        if self.posicion_en_lista(socio_id) is not None:
            raise ReservaDuplicada("el socio ya esta en la lista de espera")
        self.lista_de_espera.append(EntradaDeListaDeEspera(socio_id, ahora))
        return len(self.lista_de_espera)

    # ---- asistencia y no-shows -------------------------------------------------------

    def registrar_asistencia(self, socio_id: str, actor: Actor) -> Reserva:
        """Recepcion confirma que el socio si se presento (US-19)."""
        if not actor.puede_registrar_asistencia():
            raise PermisoDenegado("solo Recepcion registra asistencia")
        reserva = self._reserva_activa_de(socio_id)
        reserva.estado = EstadoDeReserva.ASISTIDA
        return reserva

    def registrar_no_shows(self, actor: Actor, ahora: datetime) -> list[str]:
        """Al terminar la clase, marca como no-show las reservas activas (BR-08, US-10).

        Solo registra; no aplica ninguna sancion (BR-09).
        """
        if not actor.es_sistema():
            raise PermisoDenegado("el cierre de clase lo ejecuta el Sistema")
        if ahora < self.horario.fin:
            raise ClaseNoHaTerminado("la clase aun no termina")
        ausentes = []
        for reserva in self.reservas:
            if reserva.estado is EstadoDeReserva.ACTIVA:
                reserva.estado = EstadoDeReserva.NO_SHOW
                ausentes.append(reserva.socio_id)
        return ausentes

    # ---- acciones administrativas ----------------------------------------------------

    def cancelar(self, actor: Actor) -> None:
        """BR-01: solo el Administrador cancela una clase."""
        if not actor.puede_administrar_clases():
            raise PermisoDenegado("solo el Administrador puede cancelar una clase")
        self.estado = EstadoDeClase.CANCELADA

    def configurar_capacidad(self, nueva: Capacidad, actor: Actor) -> None:
        """BR-05: solo el Administrador fija la capacidad, sin dejar a gente sin lugar."""
        if not actor.puede_administrar_clases():
            raise PermisoDenegado("solo el Administrador puede fijar la capacidad")
        if nueva.valor < self.lugares_ocupados():
            raise CapacidadInvalida("la nueva capacidad es menor a los lugares ya ocupados")
        self.capacidad = nueva
