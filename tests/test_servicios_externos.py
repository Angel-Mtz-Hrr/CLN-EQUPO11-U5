"""Pruebas con "dobles" (mocks): simulamos el correo y el banco SIN enviar ni cobrar nada real.

¿Que es un mock, en palabras simples?
  Es un "actor de ensayo": se comporta como el servicio real (el correo, el banco), pero
  solo ANOTA lo que le piden. Asi podemos comprobar: "¿se le pidio enviar el aviso?",
  "¿se le pidio cobrar exactamente 500 pesos?", y tambien practicar el mal dia:
  "¿que pasa si el banco rechaza la tarjeta?". Nadie recibe correos y nadie paga.

`create_autospec` hace al actor de ensayo MUY estricto: solo acepta los mismos metodos que
el servicio real. Si alguien se equivoca de nombre, la prueba avisa de inmediato.
"""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import create_autospec

import pytest

from src.domain import (
    Actor,
    ClaseFueraDelPlan,
    ClaseLlena,
    EstadoDeClase,
    EstadoDeReserva,
    MembresiaNoVigente,
    PermisoDenegado,
    Rol,
)
from src.ports import (
    Notificador,
    PagoRechazado,
    PasarelaDePago,
    ServicioExternoNoDisponible,
)
from src.servicios import (
    ClaseNoEncontrada,
    MontoInvalido,
    ServicioDePagos,
    ServicioDeReservas,
)

# ---------------------------------------------------------------------------------------
# Preparativos (Arrange compartido): una base en memoria con un plan, una membresia y una clase
# ---------------------------------------------------------------------------------------


@pytest.fixture
def datos_en_la_base(uow, plan_premium, plan_basico, membresia_vigente, clase_yoga):
    with uow:
        uow.planes.agregar(plan_premium)
        uow.planes.agregar(plan_basico)
        uow.membresias.agregar(membresia_vigente)  # ana: Premium, vigente
        uow.membresias.agregar(replace(membresia_vigente, socio_id="beto"))
        uow.membresias.agregar(replace(membresia_vigente, socio_id="carla"))
        uow.membresias.agregar(replace(membresia_vigente, socio_id="dani", plan_id="BASICO"))
        uow.membresias.agregar(
            replace(
                membresia_vigente,
                socio_id="eva",
                inicio=membresia_vigente.inicio - timedelta(days=90),
                vencimiento=membresia_vigente.inicio - timedelta(days=1),  # vencio hace 9 dias
            )
        )
        uow.clases.guardar(clase_yoga)
        uow.confirmar()


@pytest.fixture
def notificador():
    """Doble del correo: NO envia nada, solo anota los pedidos."""
    return create_autospec(Notificador, instance=True)


@pytest.fixture
def pasarela():
    """Doble del banco: NO cobra nada, solo anota los pedidos."""
    return create_autospec(PasarelaDePago, instance=True)


@pytest.fixture
def reservas(uow, notificador, datos_en_la_base):
    return ServicioDeReservas(uow, notificador)


@pytest.fixture
def pagos(pasarela, notificador):
    return ServicioDePagos(pasarela, notificador)


def _reservas_guardadas(uow, clase_id="YOGA-1"):
    """Lee la base con una sesion nueva: lo que ve aqui es lo que REALMENTE se guardo."""
    with uow:
        return list(uow.clases.obtener_por_id(clase_id).reservas)


# ---------------------------------------------------------------------------------------
# NOTIFICACIONES al reservar
# ---------------------------------------------------------------------------------------


class TestAvisoAlReservar:
    def test_una_reserva_exitosa_avisa_al_socio_una_sola_vez(
        self, reservas, notificador, socio_ana, ahora
    ):
        # Arrange: ana (Premium, vigente) y una clase de yoga con lugares (fixtures)
        # Act
        resultado = reservas.reservar("YOGA-1", "ana", socio_ana, ahora)
        # Assert: el "actor de ensayo" anoto UN pedido de aviso, dirigido a ana
        notificador.enviar.assert_called_once()
        destinatario, mensaje = notificador.enviar.call_args.args
        assert destinatario == "ana"
        assert "yoga" in mensaje
        assert resultado.aviso_enviado is True

    def test_la_reserva_queda_guardada_en_la_base(self, reservas, uow, socio_ana, ahora):
        reservas.reservar("YOGA-1", "ana", socio_ana, ahora)
        guardadas = _reservas_guardadas(uow)
        assert [(r.socio_id, r.estado) for r in guardadas] == [("ana", EstadoDeReserva.ACTIVA)]

    def test_recepcion_reserva_para_un_socio_y_el_aviso_le_llega_al_socio(
        self, reservas, notificador, recepcion, ahora
    ):
        reservas.reservar("YOGA-1", "ana", recepcion, ahora)
        # El aviso va a ANA (la socia), no a la persona de recepcion.
        assert notificador.enviar.call_args.args[0] == "ana"

    def test_si_el_correo_esta_caido_la_reserva_se_conserva(
        self, reservas, notificador, uow, socio_ana, ahora
    ):
        # Arrange: el servicio de avisos "se cae"
        notificador.enviar.side_effect = ServicioExternoNoDisponible("sin conexion")
        # Act
        resultado = reservas.reservar("YOGA-1", "ana", socio_ana, ahora)
        # Assert: ana conserva su lugar; el sistema solo reporta que el aviso no salio
        assert resultado.aviso_enviado is False
        assert len(_reservas_guardadas(uow)) == 1


class TestSinAvisoCuandoNoSeReserva:
    """Si la reserva se rechaza, NO se debe mandar un aviso de exito (seria confuso)."""

    def test_membresia_vencida_no_avisa_ni_guarda(self, reservas, notificador, uow, ahora):
        with pytest.raises(MembresiaNoVigente):
            reservas.reservar("YOGA-1", "eva", Actor("eva", Rol.SOCIO), ahora)
        notificador.enviar.assert_not_called()
        assert _reservas_guardadas(uow) == []

    def test_socio_sin_membresia_no_avisa(self, reservas, notificador, ahora):
        with pytest.raises(MembresiaNoVigente):
            reservas.reservar("YOGA-1", "fantasma", Actor("fantasma", Rol.SOCIO), ahora)
        notificador.enviar.assert_not_called()

    def test_clase_fuera_del_plan_no_avisa(self, reservas, notificador, ahora):
        with pytest.raises(ClaseFueraDelPlan):
            reservas.reservar("YOGA-1", "dani", Actor("dani", Rol.SOCIO), ahora)
        notificador.enviar.assert_not_called()

    def test_clase_llena_no_avisa_al_que_se_quedo_sin_lugar(
        self, reservas, notificador, socio_ana, socio_beto, ahora
    ):
        reservas.reservar("YOGA-1", "ana", socio_ana, ahora)
        reservas.reservar("YOGA-1", "beto", socio_beto, ahora)
        notificador.enviar.reset_mock()  # borramos el historial de los dos primeros avisos
        with pytest.raises(ClaseLlena):
            reservas.reservar("YOGA-1", "carla", Actor("carla", Rol.SOCIO), ahora)
        notificador.enviar.assert_not_called()

    def test_clase_inexistente(self, reservas, notificador, socio_ana, ahora):
        with pytest.raises(ClaseNoEncontrada):
            reservas.reservar("NO-EXISTE", "ana", socio_ana, ahora)
        notificador.enviar.assert_not_called()

    def test_sin_permiso_se_rechaza_por_permiso_y_no_se_revela_nada_de_la_membresia(
        self, reservas, notificador, socio_beto, ahora
    ):
        # Beto no puede actuar por Eva (cuya membresia esta vencida). El rechazo debe ser por
        # PERMISO: asi Beto no se entera de la situacion de membresia de otra persona.
        with pytest.raises(PermisoDenegado):
            reservas.reservar("YOGA-1", "eva", socio_beto, ahora)
        notificador.enviar.assert_not_called()

    def test_un_socio_no_puede_reservar_por_otro_y_no_hay_aviso(
        self, reservas, notificador, uow, socio_beto, ahora
    ):
        with pytest.raises(PermisoDenegado):
            reservas.reservar("YOGA-1", "ana", socio_beto, ahora)
        notificador.enviar.assert_not_called()
        assert _reservas_guardadas(uow) == []


# ---------------------------------------------------------------------------------------
# NOTIFICACIONES al cancelar una clase
# ---------------------------------------------------------------------------------------


class TestAvisoAlCancelarUnaClase:
    @pytest.fixture
    def clase_con_dos_socios(self, reservas, socio_ana, socio_beto, ahora):
        reservas.reservar("YOGA-1", "ana", socio_ana, ahora)
        reservas.reservar("YOGA-1", "beto", socio_beto, ahora)

    def test_se_avisa_a_cada_socio_con_reserva(
        self, reservas, notificador, clase_con_dos_socios, administrador
    ):
        notificador.enviar.reset_mock()
        resultado = reservas.cancelar_clase("YOGA-1", administrador)
        destinatarios = sorted(llamada.args[0] for llamada in notificador.enviar.call_args_list)
        assert destinatarios == ["ana", "beto"]
        assert resultado.avisados == ("ana", "beto")
        assert resultado.sin_aviso == ()

    def test_si_un_aviso_falla_los_demas_se_envian_igual(
        self, reservas, notificador, clase_con_dos_socios, administrador
    ):
        notificador.enviar.reset_mock()
        # El primer aviso (ana) falla; el segundo (beto) funciona.
        notificador.enviar.side_effect = [ServicioExternoNoDisponible("falla"), None]
        resultado = reservas.cancelar_clase("YOGA-1", administrador)
        assert notificador.enviar.call_count == 2
        assert resultado.sin_aviso == ("ana",)
        assert resultado.avisados == ("beto",)

    def test_la_clase_queda_cancelada_en_la_base(
        self, reservas, uow, clase_con_dos_socios, administrador
    ):
        reservas.cancelar_clase("YOGA-1", administrador)
        with uow:
            assert uow.clases.obtener_por_id("YOGA-1").estado is EstadoDeClase.CANCELADA

    def test_quien_no_es_administrador_no_cancela_ni_avisa(
        self, reservas, notificador, uow, clase_con_dos_socios, recepcion
    ):
        notificador.enviar.reset_mock()
        with pytest.raises(PermisoDenegado):
            reservas.cancelar_clase("YOGA-1", recepcion)
        notificador.enviar.assert_not_called()
        with uow:
            assert uow.clases.obtener_por_id("YOGA-1").estado is EstadoDeClase.PROGRAMADA

    def test_cancelar_una_clase_inexistente(self, reservas, administrador):
        with pytest.raises(ClaseNoEncontrada):
            reservas.cancelar_clase("NO-EXISTE", administrador)


# ---------------------------------------------------------------------------------------
# PASARELA DE PAGO (el banco simulado)
# ---------------------------------------------------------------------------------------


class TestCobros:
    def test_un_cobro_exitoso_pide_exactamente_lo_correcto_y_avisa(
        self, pagos, pasarela, notificador, socio_ana
    ):
        # Arrange: el banco de ensayo responde "aprobado, comprobante C-100"
        pasarela.cobrar.return_value = "C-100"
        # Act
        resultado = pagos.cobrar("ana", 50000, "clase extra de box", socio_ana)
        # Assert: se le pidio al banco UN cobro de 500.00 pesos (50,000 centavos), ni mas ni menos
        pasarela.cobrar.assert_called_once_with("ana", 50000, "clase extra de box")
        assert resultado.comprobante == "C-100"
        notificador.enviar.assert_called_once()
        assert "C-100" in notificador.enviar.call_args.args[1]

    def test_si_el_banco_rechaza_no_hay_aviso_de_pago_exitoso(
        self, pagos, pasarela, notificador, socio_ana
    ):
        pasarela.cobrar.side_effect = PagoRechazado("fondos insuficientes")
        with pytest.raises(PagoRechazado):
            pagos.cobrar("ana", 50000, "clase extra de box", socio_ana)
        notificador.enviar.assert_not_called()

    def test_un_rechazo_no_se_reintenta_solo(self, pagos, pasarela, socio_ana):
        # Reintentar por cuenta propia podria cobrar dos veces: se intenta UNA sola vez.
        pasarela.cobrar.side_effect = PagoRechazado("tarjeta vencida")
        with pytest.raises(PagoRechazado):
            pagos.cobrar("ana", 50000, "clase extra de box", socio_ana)
        assert pasarela.cobrar.call_count == 1

    def test_si_el_banco_no_responde_el_error_se_ve_y_no_hay_aviso(
        self, pagos, pasarela, notificador, socio_ana
    ):
        pasarela.cobrar.side_effect = ServicioExternoNoDisponible("tiempo agotado")
        with pytest.raises(ServicioExternoNoDisponible):
            pagos.cobrar("ana", 50000, "clase extra de box", socio_ana)
        notificador.enviar.assert_not_called()

    def test_si_el_cobro_se_hizo_pero_el_aviso_falla_el_comprobante_no_se_pierde(
        self, pagos, pasarela, notificador, socio_ana
    ):
        pasarela.cobrar.return_value = "C-200"
        notificador.enviar.side_effect = ServicioExternoNoDisponible("sin conexion")
        resultado = pagos.cobrar("ana", 50000, "clase extra de box", socio_ana)
        assert resultado.comprobante == "C-200"  # el dinero SI se cobro: se conserva la prueba
        assert resultado.aviso_enviado is False

    @pytest.mark.parametrize("monto", [0, -1, -50000])
    def test_un_monto_cero_o_negativo_nunca_llega_al_banco(
        self, pagos, pasarela, socio_ana, monto
    ):
        with pytest.raises(MontoInvalido):
            pagos.cobrar("ana", monto, "clase extra", socio_ana)
        pasarela.cobrar.assert_not_called()

    def test_el_monto_minimo_valido_es_un_centavo(self, pagos, pasarela, socio_ana):
        # Caso LIMITE
        pasarela.cobrar.return_value = "C-1"
        pagos.cobrar("ana", 1, "ajuste", socio_ana)
        pasarela.cobrar.assert_called_once_with("ana", 1, "ajuste")

    def test_recepcion_puede_cobrar_a_un_socio(self, pagos, pasarela, recepcion):
        pasarela.cobrar.return_value = "C-300"
        pagos.cobrar("ana", 50000, "clase extra", recepcion)
        pasarela.cobrar.assert_called_once_with("ana", 50000, "clase extra")

    @pytest.mark.parametrize("actor_fixture", ["socio_beto", "instructor", "administrador"])
    def test_quien_no_tiene_permiso_no_dispara_ningun_cobro(
        self, pagos, pasarela, notificador, actor_fixture, request
    ):
        actor = request.getfixturevalue(actor_fixture)
        with pytest.raises(PermisoDenegado):
            pagos.cobrar("ana", 50000, "clase extra", actor)
        pasarela.cobrar.assert_not_called()
        notificador.enviar.assert_not_called()


# ---------------------------------------------------------------------------------------
# Red de seguridad del propio doble
# ---------------------------------------------------------------------------------------


class TestElDobleEsEstricto:
    def test_el_doble_rechaza_metodos_que_el_servicio_real_no_tiene(self, notificador):
        with pytest.raises(AttributeError):
            notificador.mandar_whatsapp("ana", "hola")

    def test_el_doble_rechaza_llamadas_con_argumentos_incorrectos(self, pasarela):
        with pytest.raises(TypeError):
            pasarela.cobrar("ana")  # faltan monto y concepto
