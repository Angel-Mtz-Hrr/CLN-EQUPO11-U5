"""Datos de ejemplo compartidos por todas las pruebas (ficticios, no son socios reales)."""

from datetime import datetime, timedelta

import pytest

from src.domain import (
    Actor,
    Capacidad,
    ClaseGrupal,
    Horario,
    Membresia,
    PlanDeMembresia,
    Rol,
)

# Un "hoy" fijo para que las pruebas den siempre el mismo resultado.
AHORA = datetime(2026, 11, 3, 10, 0, 0)


@pytest.fixture
def ahora():
    return AHORA


@pytest.fixture
def plan_premium():
    return PlanDeMembresia("PREMIUM", "Premium", frozenset({"yoga", "spinning", "box"}))


@pytest.fixture
def plan_basico():
    # El plan basico solo da pesas y cardio: no incluye clases grupales.
    return PlanDeMembresia("BASICO", "Basico", frozenset())


@pytest.fixture
def membresia_vigente():
    return Membresia(
        "ana", "PREMIUM", AHORA - timedelta(days=10), AHORA + timedelta(days=20)
    )


@pytest.fixture
def clase_yoga():
    """Clase de yoga con SOLO 2 lugares, para poder llenarla facil."""
    horario = Horario(AHORA + timedelta(days=1), AHORA + timedelta(days=1, hours=1))
    return ClaseGrupal("YOGA-1", "yoga", horario, Capacidad(2))


@pytest.fixture
def socio_ana():
    return Actor("ana", Rol.SOCIO)


@pytest.fixture
def socio_beto():
    return Actor("beto", Rol.SOCIO)


@pytest.fixture
def recepcion():
    return Actor("rec-1", Rol.RECEPCION)


@pytest.fixture
def instructor():
    return Actor("inst-1", Rol.INSTRUCTOR)


@pytest.fixture
def administrador():
    return Actor("admin-1", Rol.ADMINISTRADOR)


@pytest.fixture
def sistema():
    return Actor("sistema", Rol.SISTEMA)


# ---------------------------------------------------------------------------------------
# Base de datos de prueba (Seccion 2): SQLite EN MEMORIA, una nueva por cada prueba.
# Desaparece al terminar la prueba: jamas toca datos reales.
# ---------------------------------------------------------------------------------------
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.repository import SqlAlchemyUnitOfWork, crear_motor, crear_tablas  # noqa: E402


@pytest.fixture
def motor():
    motor = crear_motor("sqlite:///:memory:")
    crear_tablas(motor)
    yield motor
    motor.dispose()


@pytest.fixture
def session_factory(motor):
    return sessionmaker(bind=motor)


@pytest.fixture
def uow(session_factory):
    return SqlAlchemyUnitOfWork(session_factory)


# ---------------------------------------------------------------------------------------
# Seccion 3: un "correo de ensayo" que NO envia nada (para pruebas donde el aviso no es el tema)
# ---------------------------------------------------------------------------------------
from unittest.mock import create_autospec  # noqa: E402

from src.ports import Notificador  # noqa: E402


@pytest.fixture
def notificador_falso():
    return create_autospec(Notificador, instance=True)
