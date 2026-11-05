"""TDD · BR-10 (provisional): un socio solo cancela con 2 h o mas de anticipacion."""

from datetime import timedelta

import pytest

from src.domain import CancelacionFueraDeVentana, PoliticaDeCancelacion


class TestVentanaDeCancelacion:
    def test_socio_cancela_con_mas_de_dos_horas_de_anticipacion(self, clase_yoga, socio_ana):
        # Arrange: faltan 3 h para la clase
        ahora = clase_yoga.horario.inicio - timedelta(hours=3)
        # Act + Assert: no lanza ningun error
        PoliticaDeCancelacion().exigir_puede_cancelar(socio_ana, "ana", clase_yoga, ahora)

    def test_limite_exactamente_dos_horas_todavia_puede_cancelar(self, clase_yoga, socio_ana):
        ahora = clase_yoga.horario.inicio - timedelta(hours=2)
        PoliticaDeCancelacion().exigir_puede_cancelar(socio_ana, "ana", clase_yoga, ahora)

    def test_un_segundo_dentro_de_la_ventana_se_rechaza(self, clase_yoga, socio_ana):
        ahora = clase_yoga.horario.inicio - timedelta(hours=2) + timedelta(seconds=1)
        with pytest.raises(CancelacionFueraDeVentana):
            PoliticaDeCancelacion().exigir_puede_cancelar(socio_ana, "ana", clase_yoga, ahora)


# ---------------------------------------------------------------------------------------
# Seccion 4: quien puede cancelar (rol) y cuando (estado de la clase y tiempo)
# ---------------------------------------------------------------------------------------
from src.domain import (  # noqa: E402
    Actor,
    ClaseNoProgramada,
    ClaseYaIniciada,
    EstadoDeClase,
    PermisoDenegado,
    Rol,
)


def _evaluar(actor, clase, ahora, socio_id="ana"):
    PoliticaDeCancelacion().exigir_puede_cancelar(actor, socio_id, clase, ahora)


class TestQuienPuedeCancelar:
    def test_un_tercero_no_cancela_la_reserva_de_otro(self, clase_yoga, socio_beto):
        ahora = clase_yoga.horario.inicio - timedelta(days=1)
        with pytest.raises(PermisoDenegado):
            _evaluar(socio_beto, clase_yoga, ahora)

    def test_el_administrador_tampoco_gestiona_reservas_de_socios(self, clase_yoga, administrador):
        ahora = clase_yoga.horario.inicio - timedelta(days=1)
        with pytest.raises(PermisoDenegado):
            _evaluar(administrador, clase_yoga, ahora)

    @pytest.mark.parametrize("rol", [Rol.INSTRUCTOR, Rol.SISTEMA, Rol.ADMINISTRADOR])
    def test_roles_sin_permiso_son_rechazados_por_permiso(self, rol, clase_yoga):
        ahora = clase_yoga.horario.inicio - timedelta(days=1)
        with pytest.raises(PermisoDenegado):
            _evaluar(Actor("x-1", rol), clase_yoga, ahora)

    def test_el_permiso_se_revisa_antes_que_el_tiempo(self, clase_yoga, socio_beto):
        # Un tercero a 10 min de la clase recibe PermisoDenegado, no "fuera de ventana":
        # asi no se le revela nada sobre la reserva ajena.
        ahora = clase_yoga.horario.inicio - timedelta(minutes=10)
        with pytest.raises(PermisoDenegado):
            _evaluar(socio_beto, clase_yoga, ahora)

    def test_recepcion_puede_cancelar_dentro_de_la_ventana(self, clase_yoga, recepcion):
        ahora = clase_yoga.horario.inicio - timedelta(minutes=30)
        _evaluar(recepcion, clase_yoga, ahora)  # no lanza


class TestCuandoSePuedeCancelar:
    def test_nadie_cancela_una_clase_que_ya_inicio_ni_recepcion(self, clase_yoga, recepcion):
        ahora = clase_yoga.horario.inicio + timedelta(minutes=1)
        with pytest.raises(ClaseYaIniciada):
            _evaluar(recepcion, clase_yoga, ahora)

    def test_limite_en_el_instante_exacto_del_inicio_ya_no_se_cancela(self, clase_yoga, recepcion):
        with pytest.raises(ClaseYaIniciada):
            _evaluar(recepcion, clase_yoga, clase_yoga.horario.inicio)

    def test_el_socio_con_clase_iniciada_recibe_clase_ya_iniciada(self, clase_yoga, socio_ana):
        ahora = clase_yoga.horario.inicio + timedelta(minutes=1)
        with pytest.raises(ClaseYaIniciada):
            _evaluar(socio_ana, clase_yoga, ahora)

    def test_una_clase_cancelada_no_admite_cancelar_reservas(
        self, clase_yoga, administrador, recepcion
    ):
        clase_yoga.cancelar(administrador)
        assert clase_yoga.estado is EstadoDeClase.CANCELADA
        with pytest.raises(ClaseNoProgramada):
            _evaluar(recepcion, clase_yoga, clase_yoga.horario.inicio - timedelta(days=1))
