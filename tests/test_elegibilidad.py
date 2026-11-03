"""Pruebas de BR-06 (membresia vigente) y BR-07 (clase incluida en el plan).

En palabras simples: ¿el gimnasio deja pasar solo a quien corresponde?
Cada prueba sigue el patron Arrange-Act-Assert (Preparar - Actuar - Verificar).
"""

from datetime import timedelta

import pytest

from src.domain import (
    ClaseFueraDelPlan,
    Membresia,
    MembresiaNoVigente,
    MotivoDeRechazo,
    ReglasDeElegibilidad,
)


class TestMembresiaVigente:
    """BR-06: una membresia vencida o suspendida no da acceso."""

    def test_membresia_dentro_de_su_periodo_es_vigente(self, membresia_vigente, ahora):
        # Arrange: la membresia de Ana (fixture) va de hace 10 dias a dentro de 20.
        # Act
        resultado = membresia_vigente.esta_vigente_en(ahora)
        # Assert
        assert resultado is True

    def test_membresia_vencida_no_es_vigente(self, ahora):
        # Arrange: venció ayer
        vencida = Membresia("ana", "PREMIUM", ahora - timedelta(days=60), ahora - timedelta(days=1))
        # Act + Assert
        assert vencida.esta_vigente_en(ahora) is False

    def test_membresia_suspendida_no_es_vigente_aunque_no_haya_vencido(self, ahora):
        # Arrange: fechas correctas, pero suspendida
        suspendida = Membresia(
            "ana", "PREMIUM", ahora - timedelta(days=5), ahora + timedelta(days=5), suspendida=True
        )
        # Act + Assert
        assert suspendida.esta_vigente_en(ahora) is False

    def test_limite_el_dia_exacto_del_vencimiento_todavia_es_vigente(self, ahora):
        # Caso LIMITE: justo en el instante del vencimiento.
        m = Membresia("ana", "PREMIUM", ahora - timedelta(days=30), ahora)
        assert m.esta_vigente_en(ahora) is True

    def test_limite_un_segundo_despues_del_vencimiento_ya_no_es_vigente(self, ahora):
        m = Membresia("ana", "PREMIUM", ahora - timedelta(days=30), ahora)
        assert m.esta_vigente_en(ahora + timedelta(seconds=1)) is False

    def test_membresia_que_aun_no_inicia_no_es_vigente(self, ahora):
        futura = Membresia("ana", "PREMIUM", ahora + timedelta(days=1), ahora + timedelta(days=30))
        assert futura.esta_vigente_en(ahora) is False


class TestClaseIncluidaEnElPlan:
    """BR-07: si la clase no esta en el plan, se bloquea y se sugiere actualizar."""

    def test_plan_premium_incluye_yoga(self, plan_premium):
        assert plan_premium.incluye("yoga") is True

    def test_plan_basico_no_incluye_yoga(self, plan_basico):
        assert plan_basico.incluye("yoga") is False


class TestReglasDeElegibilidad:
    """Junta las dos reglas anteriores y dice 'si puede' o 'no puede, y por que'."""

    def test_socio_vigente_con_clase_en_su_plan_es_elegible(
        self, membresia_vigente, plan_premium, clase_yoga, ahora
    ):
        # Arrange: todo en orden (fixtures)
        # Act
        resultado = ReglasDeElegibilidad().evaluar(
            membresia_vigente, plan_premium, clase_yoga, ahora
        )
        # Assert
        assert resultado.elegible is True
        assert resultado.motivo is None

    def test_membresia_vencida_es_rechazada_con_su_motivo(self, plan_premium, clase_yoga, ahora):
        vencida = Membresia("ana", "PREMIUM", ahora - timedelta(days=60), ahora - timedelta(days=1))
        resultado = ReglasDeElegibilidad().evaluar(vencida, plan_premium, clase_yoga, ahora)
        assert resultado.elegible is False
        assert resultado.motivo is MotivoDeRechazo.MEMBRESIA_NO_VIGENTE

    def test_clase_fuera_del_plan_es_rechazada_con_su_motivo(
        self, membresia_vigente, plan_basico, clase_yoga, ahora
    ):
        resultado = ReglasDeElegibilidad().evaluar(
            membresia_vigente, plan_basico, clase_yoga, ahora
        )
        assert resultado.elegible is False
        assert resultado.motivo is MotivoDeRechazo.CLASE_FUERA_DEL_PLAN

    def test_si_falla_vigencia_y_plan_a_la_vez_se_reporta_primero_la_vigencia(
        self, plan_basico, clase_yoga, ahora
    ):
        # Orden de los gateways del BPMN-1: primero vigencia, despues plan.
        vencida = Membresia("ana", "BASICO", ahora - timedelta(days=60), ahora - timedelta(days=1))
        resultado = ReglasDeElegibilidad().evaluar(vencida, plan_basico, clase_yoga, ahora)
        assert resultado.motivo is MotivoDeRechazo.MEMBRESIA_NO_VIGENTE

    def test_exigir_lanza_el_error_de_negocio_de_membresia(self, plan_premium, clase_yoga, ahora):
        vencida = Membresia("ana", "PREMIUM", ahora - timedelta(days=60), ahora - timedelta(days=1))
        resultado = ReglasDeElegibilidad().evaluar(vencida, plan_premium, clase_yoga, ahora)
        with pytest.raises(MembresiaNoVigente):
            resultado.exigir()

    def test_exigir_lanza_el_error_de_negocio_de_plan(
        self, membresia_vigente, plan_basico, clase_yoga, ahora
    ):
        resultado = ReglasDeElegibilidad().evaluar(
            membresia_vigente, plan_basico, clase_yoga, ahora
        )
        with pytest.raises(ClaseFueraDelPlan, match="actualizar"):
            resultado.exigir()

    def test_exigir_no_hace_nada_si_es_elegible(
        self, membresia_vigente, plan_premium, clase_yoga, ahora
    ):
        resultado = ReglasDeElegibilidad().evaluar(
            membresia_vigente, plan_premium, clase_yoga, ahora
        )
        assert resultado.exigir() is None
