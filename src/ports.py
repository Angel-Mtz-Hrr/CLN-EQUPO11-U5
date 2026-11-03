"""Puertos: los "contratos" de persistencia que el resto del sistema conoce.

Aqui NO hay SQL ni SQLAlchemy. Solo se dice QUE hace falta (guardar una clase, buscar una
membresia) y no COMO se hace. La implementacion real vive en `src/repository.py`.
Asi el dominio y los servicios no dependen de ninguna base de datos concreta.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain import ClaseGrupal, Membresia, PlanDeMembresia


class ConflictoDeVersion(Exception):
    """Dos personas modificaron la misma clase al mismo tiempo (ej. el ultimo lugar).

    Gana quien guarda primero; el otro recibe este aviso y puede reintentar.
    """


class ClaseGrupalRepository(ABC):
    @abstractmethod
    def obtener_por_id(self, clase_id: str) -> ClaseGrupal | None: ...

    @abstractmethod
    def guardar(self, clase: ClaseGrupal) -> None: ...

    @abstractmethod
    def obtener_clases_terminadas_sin_cierre(self, instante: datetime) -> list[ClaseGrupal]:
        """Clases ya terminadas que aun tienen reservas activas (pendientes de no-show)."""


class MembresiaRepository(ABC):
    """Solo lectura: FitZone ya administra membresias; este sistema solo las consulta."""

    @abstractmethod
    def obtener_actual_del_socio(self, socio_id: str) -> Membresia | None: ...


class PlanRepository(ABC):
    @abstractmethod
    def obtener_por_id(self, plan_id: str) -> PlanDeMembresia | None: ...


class UnitOfWork(ABC):
    """Una unidad de trabajo = una transaccion: o se guarda TODO, o no se guarda NADA.

    Uso recomendado:
        with uow:
            clase = uow.clases.obtener_por_id("YOGA-1")
            clase.reservar(...)
            uow.clases.guardar(clase)
            uow.confirmar()

    Si ocurre cualquier error, o si se olvida llamar a `confirmar()`, no se guarda nada.
    """

    clases: ClaseGrupalRepository
    membresias: MembresiaRepository
    planes: PlanRepository

    @abstractmethod
    def iniciar(self) -> None: ...

    @abstractmethod
    def confirmar(self) -> None: ...

    @abstractmethod
    def revertir(self) -> None: ...

    @abstractmethod
    def cerrar(self) -> None: ...

    def __enter__(self) -> UnitOfWork:
        self.iniciar()
        return self

    def __exit__(self, tipo_de_error, error, traza) -> None:
        # Seguro por defecto: lo que no se confirmo explicitamente, se descarta.
        self.revertir()
        self.cerrar()
