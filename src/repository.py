"""Persistencia de FitZone con SQLAlchemy (la "bodega" donde se guarda la informacion).

Esta capa traduce entre dos mundos:
  - los objetos del dominio (ClaseGrupal, Reserva...), que solo conocen reglas de negocio;
  - las filas de la base de datos (tablas), que solo conocen columnas.

El dominio (`src/domain.py`) NO importa nada de este archivo.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.pool import StaticPool

from src.domain import (
    Capacidad,
    ClaseGrupal,
    EntradaDeListaDeEspera,
    EstadoDeClase,
    EstadoDeReserva,
    Horario,
    Membresia,
    PlanDeMembresia,
    Reserva,
)
from src.ports import (
    ClaseGrupalRepository,
    ConflictoDeVersion,
    MembresiaRepository,
    PlanRepository,
    UnitOfWork,
)

# --------------------------------------------------------------------------------------
# Tablas (el "formato" en que se guarda cada cosa)
# --------------------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class ClaseRow(Base):
    __tablename__ = "clases"

    clase_id: Mapped[str] = mapped_column(String, primary_key=True)
    tipo: Mapped[str] = mapped_column(String, nullable=False)
    inicio: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fin: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    capacidad: Mapped[int] = mapped_column(Integer, nullable=False)
    estado: Mapped[str] = mapped_column(String, nullable=False)
    # Contador de versiones: sirve para detectar que dos personas editaron a la vez.
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    reservas: Mapped[list[ReservaRow]] = relationship(
        back_populates="clase", cascade="all, delete-orphan", order_by="ReservaRow.orden"
    )
    espera: Mapped[list[EsperaRow]] = relationship(
        back_populates="clase", cascade="all, delete-orphan", order_by="EsperaRow.posicion"
    )

    __mapper_args__ = {"version_id_col": version}
    # Red de seguridad (INV-8): la base de datos tambien rechaza capacidades invalidas.
    __table_args__ = (CheckConstraint("capacidad > 0", name="ck_capacidad_positiva"),)


class ReservaRow(Base):
    __tablename__ = "reservas"

    reserva_id: Mapped[str] = mapped_column(String, primary_key=True)
    clase_id: Mapped[str] = mapped_column(ForeignKey("clases.clase_id"), nullable=False)
    socio_id: Mapped[str] = mapped_column(String, nullable=False)
    creada_en: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    estado: Mapped[str] = mapped_column(String, nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)

    clase: Mapped[ClaseRow] = relationship(back_populates="reservas")

    # Red de seguridad (INV-4): un socio no puede tener dos lugares vigentes en la misma
    # clase. Las reservas CANCELADAS o NO_SHOW no cuentan, por eso el indice es "parcial".
    __table_args__ = (
        Index(
            "uq_un_lugar_vigente_por_socio",
            "clase_id",
            "socio_id",
            unique=True,
            sqlite_where=text("estado IN ('ACTIVA', 'ASISTIDA')"),
        ),
    )


class EsperaRow(Base):
    __tablename__ = "lista_de_espera"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clase_id: Mapped[str] = mapped_column(ForeignKey("clases.clase_id"), nullable=False)
    socio_id: Mapped[str] = mapped_column(String, nullable=False)
    solicitada_en: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    posicion: Mapped[int] = mapped_column(Integer, nullable=False)

    clase: Mapped[ClaseRow] = relationship(back_populates="espera")

    __table_args__ = (UniqueConstraint("clase_id", "socio_id", name="uq_socio_una_vez_en_lista"),)


class PlanRow(Base):
    __tablename__ = "planes"

    plan_id: Mapped[str] = mapped_column(String, primary_key=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    # Tipos de clase incluidos, separados por coma (ej. "yoga,spinning,box").
    tipos_de_clase: Mapped[str] = mapped_column(String, nullable=False, default="")


class MembresiaRow(Base):
    __tablename__ = "membresias"

    socio_id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("planes.plan_id"), nullable=False)
    inicio: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    vencimiento: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    suspendida: Mapped[bool] = mapped_column(nullable=False, default=False)


# --------------------------------------------------------------------------------------
# Conexion
# --------------------------------------------------------------------------------------


def crear_motor(url: str = "sqlite:///:memory:") -> Engine:
    """Crea la conexion. Por defecto, una base SQLite en memoria (desaparece al cerrar)."""
    if url.endswith(":memory:"):
        # Una sola conexion compartida: si no, cada sesion veria su propia base vacia.
        motor = create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    else:
        motor = create_engine(url)

    if motor.dialect.name == "sqlite":

        @event.listens_for(motor, "connect")
        def _activar_llaves_foraneas(conexion, _registro):
            # SQLite no revisa las relaciones entre tablas a menos que se le pida.
            conexion.execute("PRAGMA foreign_keys=ON")

    return motor


def crear_tablas(motor: Engine) -> None:
    Base.metadata.create_all(motor)


# --------------------------------------------------------------------------------------
# Repositorios
# --------------------------------------------------------------------------------------


def _a_dominio(row: ClaseRow) -> ClaseGrupal:
    """Fila de base de datos -> objeto del dominio."""
    return ClaseGrupal(
        clase_id=row.clase_id,
        tipo=row.tipo,
        horario=Horario(row.inicio, row.fin),
        capacidad=Capacidad(row.capacidad),
        estado=EstadoDeClase(row.estado),
        reservas=[
            Reserva(r.reserva_id, r.socio_id, r.creada_en, EstadoDeReserva(r.estado))
            for r in row.reservas
        ],
        lista_de_espera=[EntradaDeListaDeEspera(e.socio_id, e.solicitada_en) for e in row.espera],
    )


class SqlClaseGrupalRepository(ClaseGrupalRepository):
    """La clase se guarda y se carga COMPLETA: con sus reservas y su lista de espera."""

    def __init__(self, session: Session):
        self._session = session
        # Mantiene "vivas" las filas leidas, con su numero de version original. Sin esto,
        # SQLAlchemy las olvida al terminar de cargar y, al guardar, las leeria de nuevo YA
        # actualizadas por otra persona: el conflicto pasaria desapercibido.
        self._filas_cargadas: dict[str, ClaseRow] = {}

    def obtener_por_id(self, clase_id: str) -> ClaseGrupal | None:
        row = self._session.get(ClaseRow, clase_id)
        if row is None:
            return None
        self._filas_cargadas[clase_id] = row
        return _a_dominio(row)

    def guardar(self, clase: ClaseGrupal) -> None:
        row = self._session.get(ClaseRow, clase.clase_id)
        es_nueva = row is None
        if es_nueva:
            row = ClaseRow(clase_id=clase.clase_id)
            self._session.add(row)
        self._filas_cargadas[clase.clase_id] = row

        row.tipo = clase.tipo
        row.inicio = clase.horario.inicio
        row.fin = clase.horario.fin
        row.capacidad = clase.capacidad.valor
        row.estado = clase.estado.value

        self._sincronizar_reservas(row, clase)
        self._sincronizar_lista_de_espera(row, clase)

        if not es_nueva:
            # Aunque solo cambien las reservas, la "clase" cuenta como modificada:
            # asi siempre sube su version y se detectan ediciones simultaneas.
            flag_modified(row, "estado")
        try:
            self._session.flush()
        except StaleDataError as error:
            raise ConflictoDeVersion(
                f"la clase {clase.clase_id} fue modificada por alguien mas; reintenta"
            ) from error

    def obtener_clases_terminadas_sin_cierre(self, instante: datetime) -> list[ClaseGrupal]:
        consulta = (
            select(ClaseRow)
            .join(ReservaRow, ReservaRow.clase_id == ClaseRow.clase_id)
            .where(
                ClaseRow.fin <= instante,
                ClaseRow.estado == EstadoDeClase.PROGRAMADA.value,
                ReservaRow.estado == EstadoDeReserva.ACTIVA.value,
            )
            .distinct()
            .order_by(ClaseRow.fin)
        )
        return [_a_dominio(r) for r in self._session.scalars(consulta)]

    # ---- ayudantes internos ----------------------------------------------------------

    @staticmethod
    def _sincronizar_reservas(row: ClaseRow, clase: ClaseGrupal) -> None:
        existentes = {r.reserva_id: r for r in row.reservas}
        for orden, reserva in enumerate(clase.reservas):
            fila = existentes.get(reserva.reserva_id)
            if fila is None:
                row.reservas.append(
                    ReservaRow(
                        reserva_id=reserva.reserva_id,
                        socio_id=reserva.socio_id,
                        creada_en=reserva.creada_en,
                        estado=reserva.estado.value,
                        orden=orden,
                    )
                )
            else:
                fila.estado = reserva.estado.value

    @staticmethod
    def _sincronizar_lista_de_espera(row: ClaseRow, clase: ClaseGrupal) -> None:
        existentes = {e.socio_id: e for e in row.espera}
        socios_actuales = {e.socio_id for e in clase.lista_de_espera}
        for socio_id, fila in existentes.items():
            if socio_id not in socios_actuales:
                row.espera.remove(fila)
        for posicion, entrada in enumerate(clase.lista_de_espera, start=1):
            fila = existentes.get(entrada.socio_id)
            if fila is None:
                row.espera.append(
                    EsperaRow(
                        socio_id=entrada.socio_id,
                        solicitada_en=entrada.solicitada_en,
                        posicion=posicion,
                    )
                )
            else:
                fila.posicion = posicion


class SqlPlanRepository(PlanRepository):
    def __init__(self, session: Session):
        self._session = session

    def obtener_por_id(self, plan_id: str) -> PlanDeMembresia | None:
        row = self._session.get(PlanRow, plan_id)
        if row is None:
            return None
        tipos = frozenset(t for t in row.tipos_de_clase.split(",") if t)
        return PlanDeMembresia(row.plan_id, row.nombre, tipos)

    def agregar(self, plan: PlanDeMembresia) -> None:
        """Solo para cargar datos de apoyo (en FitZone los planes los administra otro sistema)."""
        self._session.merge(
            PlanRow(
                plan_id=plan.plan_id,
                nombre=plan.nombre,
                tipos_de_clase=",".join(sorted(plan.tipos_de_clase)),
            )
        )
        self._session.flush()


class SqlMembresiaRepository(MembresiaRepository):
    def __init__(self, session: Session):
        self._session = session

    def obtener_actual_del_socio(self, socio_id: str) -> Membresia | None:
        row = self._session.get(MembresiaRow, socio_id)
        if row is None:
            return None
        return Membresia(row.socio_id, row.plan_id, row.inicio, row.vencimiento, row.suspendida)

    def agregar(self, membresia: Membresia) -> None:
        """Solo para cargar datos de apoyo (el sistema no modifica membresias: BR-04)."""
        self._session.merge(
            MembresiaRow(
                socio_id=membresia.socio_id,
                plan_id=membresia.plan_id,
                inicio=membresia.inicio,
                vencimiento=membresia.vencimiento,
                suspendida=membresia.suspendida,
            )
        )
        self._session.flush()


# --------------------------------------------------------------------------------------
# Unidad de trabajo (la transaccion)
# --------------------------------------------------------------------------------------


class SqlAlchemyUnitOfWork(UnitOfWork):
    """Abre una sesion, entrega los repositorios y decide: confirmar o revertir."""

    def __init__(self, session_factory: sessionmaker):
        self._session_factory = session_factory
        self._session: Session | None = None

    def iniciar(self) -> None:
        self._session = self._session_factory()
        self.clases = SqlClaseGrupalRepository(self._session)
        self.membresias = SqlMembresiaRepository(self._session)
        self.planes = SqlPlanRepository(self._session)

    def confirmar(self) -> None:
        """Guarda de forma definitiva (commit).

        Si algo falla, el error se propaga y al salir del bloque `with` se revierte todo.
        """
        self._session.commit()

    def revertir(self) -> None:
        """Descarta todo lo pendiente (rollback)."""
        if self._session is not None:
            self._session.rollback()

    def cerrar(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
