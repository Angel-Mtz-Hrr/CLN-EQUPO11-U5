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
    return Membresia("ana", "PREMIUM", AHORA - timedelta(days=10), AHORA + timedelta(days=20))


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
