"""Pruebas de la clase grupal: cupo (BR-05), reservas, lista de espera, asistencia y no-shows.

Idea central: sin importar cuanta gente intente reservar, NUNCA se supera la capacidad.
"""

from datetime import timedelta

import pytest

from src.domain import (
    Capacidad,
    CapacidadInvalida,
    ClaseLlena,
    ClaseNoHaTerminado,
    ClaseNoProgramada,
    EstadoDeClase,
    EstadoDeReserva,
    Horario,
    HorarioInvalido,
    ListaDeEsperaNoPermitida,
    PermisoDenegado,
    ReservaDuplicada,
    ReservaNoEncontrada,
)


class TestCapacidadYHorario:
    @pytest.mark.parametrize("valor", [0, -1, -20])
    def test_capacidad_debe_ser_mayor_que_cero(self, valor):
        with pytest.raises(CapacidadInvalida):
            Capacidad(valor)

    def test_capacidad_de_un_lugar_es_valida(self):
        # Caso LIMITE: el minimo permitido.
        assert Capacidad(1).valor == 1

    def test_horario_con_inicio_igual_al_fin_es_invalido(self, ahora):
        with pytest.raises(HorarioInvalido):
            Horario(ahora, ahora)

    def test_horario_con_inicio_despues_del_fin_es_invalido(self, ahora):
        with pytest.raises(HorarioInvalido):
            Horario(ahora + timedelta(hours=1), ahora)


class TestReservar:
    """BR-05: la capacidad maxima nunca se supera."""

    def test_reservar_con_lugares_disponibles_registra_la_reserva(
        self, clase_yoga, socio_ana, ahora
    ):
        # Arrange: clase de 2 lugares, vacia (fixture)
        # Act
        reserva = clase_yoga.reservar("ana", socio_ana, ahora)
        # Assert
        assert reserva.socio_id == "ana"
        assert reserva.estado is EstadoDeReserva.ACTIVA
        assert clase_yoga.lugares_disponibles() == 1

    def test_el_ultimo_lugar_se_puede_reservar(self, clase_yoga, socio_ana, socio_beto, ahora):
        # Caso LIMITE: queda exactamente 1 lugar.
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.reservar("beto", socio_beto, ahora)
        assert clase_yoga.lugares_disponibles() == 0
        assert clase_yoga.esta_llena() is True

    def test_clase_llena_rechaza_una_reserva_mas(
        self, clase_yoga, socio_ana, socio_beto, recepcion, ahora
    ):
        # Arrange: se llenan los 2 lugares
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.reservar("beto", socio_beto, ahora)
        # Act + Assert: el tercero es rechazado y NO se guarda nada
        with pytest.raises(ClaseLlena):
            clase_yoga.reservar("carla", recepcion, ahora)
        assert len(clase_yoga.reservas) == 2

    def test_no_se_puede_reservar_en_una_clase_cancelada(
        self, clase_yoga, socio_ana, administrador, ahora
    ):
        clase_yoga.cancelar(administrador)
        with pytest.raises(ClaseNoProgramada):
            clase_yoga.reservar("ana", socio_ana, ahora)

    def test_recepcion_puede_reservar_en_nombre_de_un_socio(self, clase_yoga, recepcion, ahora):
        # BR-03
        reserva = clase_yoga.reservar("ana", recepcion, ahora)
        assert reserva.socio_id == "ana"

    def test_un_socio_no_puede_reservar_en_nombre_de_otro(self, clase_yoga, socio_beto, ahora):
        with pytest.raises(PermisoDenegado):
            clase_yoga.reservar("ana", socio_beto, ahora)

    def test_un_instructor_no_puede_reservar(self, clase_yoga, instructor, ahora):
        with pytest.raises(PermisoDenegado):
            clase_yoga.reservar("ana", instructor, ahora)


class TestNoReservarDosVeces:
    """TDD (Seccion 1): INV-4, un socio no puede tener dos lugares en la misma clase."""

    def test_un_socio_no_puede_reservar_dos_veces_la_misma_clase(
        self, clase_yoga, socio_ana, ahora
    ):
        # Arrange: Ana ya tiene su lugar
        clase_yoga.reservar("ana", socio_ana, ahora)
        # Act + Assert: el segundo intento se rechaza y no ocupa otro lugar
        with pytest.raises(ReservaDuplicada):
            clase_yoga.reservar("ana", socio_ana, ahora)
        assert clase_yoga.lugares_disponibles() == 1

    def test_si_cancelo_su_reserva_puede_volver_a_reservar(self, clase_yoga, socio_ana, ahora):
        # Una reserva CANCELADA ya no cuenta como "lugar vigente".
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.cancelar_reserva("ana", socio_ana)
        nueva = clase_yoga.reservar("ana", socio_ana, ahora)
        assert nueva.estado is EstadoDeReserva.ACTIVA

    def test_recepcion_tampoco_puede_duplicar_la_reserva_de_un_socio(
        self, clase_yoga, socio_ana, recepcion, ahora
    ):
        clase_yoga.reservar("ana", socio_ana, ahora)
        with pytest.raises(ReservaDuplicada):
            clase_yoga.reservar("ana", recepcion, ahora)


class TestCancelarReserva:
    def test_cancelar_libera_el_lugar(self, clase_yoga, socio_ana, ahora):
        clase_yoga.reservar("ana", socio_ana, ahora)
        reserva = clase_yoga.cancelar_reserva("ana", socio_ana)
        assert reserva.estado is EstadoDeReserva.CANCELADA
        assert clase_yoga.lugares_disponibles() == 2

    def test_recepcion_puede_cancelar_en_nombre_del_socio(
        self, clase_yoga, socio_ana, recepcion, ahora
    ):
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.cancelar_reserva("ana", recepcion)
        assert clase_yoga.lugares_disponibles() == 2

    def test_otro_socio_no_puede_cancelar_la_reserva_ajena(
        self, clase_yoga, socio_ana, socio_beto, ahora
    ):
        clase_yoga.reservar("ana", socio_ana, ahora)
        with pytest.raises(PermisoDenegado):
            clase_yoga.cancelar_reserva("ana", socio_beto)

    def test_cancelar_sin_tener_reserva_se_rechaza(self, clase_yoga, socio_ana):
        with pytest.raises(ReservaNoEncontrada):
            clase_yoga.cancelar_reserva("ana", socio_ana)


class TestListaDeEspera:
    """US-05: solo cuando la clase esta llena, y respetando el orden de llegada."""

    def _llenar(self, clase, socio_ana, socio_beto, ahora):
        clase.reservar("ana", socio_ana, ahora)
        clase.reservar("beto", socio_beto, ahora)

    def test_con_clase_llena_el_socio_entra_al_final_y_conoce_su_posicion(
        self, clase_yoga, socio_ana, socio_beto, recepcion, ahora
    ):
        self._llenar(clase_yoga, socio_ana, socio_beto, ahora)
        assert clase_yoga.unir_a_lista_de_espera("carla", recepcion, ahora) == 1
        assert clase_yoga.unir_a_lista_de_espera("dani", recepcion, ahora) == 2
        assert clase_yoga.posicion_en_lista("dani") == 2

    def test_no_se_puede_entrar_a_la_lista_si_aun_hay_lugares(self, clase_yoga, socio_ana, ahora):
        with pytest.raises(ListaDeEsperaNoPermitida):
            clase_yoga.unir_a_lista_de_espera("ana", socio_ana, ahora)

    def test_quien_ya_tiene_lugar_no_puede_entrar_a_la_lista(
        self, clase_yoga, socio_ana, socio_beto, ahora
    ):
        self._llenar(clase_yoga, socio_ana, socio_beto, ahora)
        with pytest.raises(ReservaDuplicada):
            clase_yoga.unir_a_lista_de_espera("ana", socio_ana, ahora)

    def test_no_se_puede_entrar_dos_veces_a_la_lista(
        self, clase_yoga, socio_ana, socio_beto, recepcion, ahora
    ):
        self._llenar(clase_yoga, socio_ana, socio_beto, ahora)
        clase_yoga.unir_a_lista_de_espera("carla", recepcion, ahora)
        with pytest.raises(ReservaDuplicada):
            clase_yoga.unir_a_lista_de_espera("carla", recepcion, ahora)

    def test_un_socio_no_puede_apuntar_a_otro_en_la_lista(
        self, clase_yoga, socio_ana, socio_beto, ahora
    ):
        self._llenar(clase_yoga, socio_ana, socio_beto, ahora)
        with pytest.raises(PermisoDenegado):
            clase_yoga.unir_a_lista_de_espera("carla", socio_ana, ahora)

    def test_no_hay_lista_de_espera_en_una_clase_cancelada(
        self, clase_yoga, socio_ana, socio_beto, administrador, recepcion, ahora
    ):
        self._llenar(clase_yoga, socio_ana, socio_beto, ahora)
        clase_yoga.cancelar(administrador)
        with pytest.raises(ClaseNoProgramada):
            clase_yoga.unir_a_lista_de_espera("carla", recepcion, ahora)

    def test_posicion_de_quien_no_esta_en_lista_es_none(self, clase_yoga):
        assert clase_yoga.posicion_en_lista("nadie") is None


class TestAsistenciaYNoShows:
    """BR-08: no-show = reserva que no se cancelo y a la que el socio no llego."""

    def test_recepcion_registra_asistencia(self, clase_yoga, socio_ana, recepcion, ahora):
        clase_yoga.reservar("ana", socio_ana, ahora)
        reserva = clase_yoga.registrar_asistencia("ana", recepcion)
        assert reserva.estado is EstadoDeReserva.ASISTIDA

    def test_quien_asistio_sigue_ocupando_su_lugar(self, clase_yoga, socio_ana, recepcion, ahora):
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.registrar_asistencia("ana", recepcion)
        assert clase_yoga.lugares_disponibles() == 1

    def test_un_socio_no_puede_registrar_su_propia_asistencia(self, clase_yoga, socio_ana, ahora):
        clase_yoga.reservar("ana", socio_ana, ahora)
        with pytest.raises(PermisoDenegado):
            clase_yoga.registrar_asistencia("ana", socio_ana)

    def test_asistencia_sin_reserva_se_rechaza(self, clase_yoga, recepcion):
        with pytest.raises(ReservaNoEncontrada):
            clase_yoga.registrar_asistencia("ana", recepcion)

    def test_al_terminar_la_clase_quien_no_llego_queda_como_no_show(
        self, clase_yoga, socio_ana, socio_beto, recepcion, sistema
    ):
        ahora = clase_yoga.horario.inicio - timedelta(days=1)
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.reservar("beto", socio_beto, ahora)
        clase_yoga.registrar_asistencia("ana", recepcion)  # Ana si fue; Beto no
        ausentes = clase_yoga.registrar_no_shows(sistema, clase_yoga.horario.fin)
        assert ausentes == ["beto"]
        assert clase_yoga.reservas[1].estado is EstadoDeReserva.NO_SHOW
        assert clase_yoga.reservas[0].estado is EstadoDeReserva.ASISTIDA

    def test_quien_cancelo_a_tiempo_no_es_no_show(self, clase_yoga, socio_ana, sistema, ahora):
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.cancelar_reserva("ana", socio_ana)
        assert clase_yoga.registrar_no_shows(sistema, clase_yoga.horario.fin) == []

    def test_no_se_registran_no_shows_antes_de_que_termine_la_clase(self, clase_yoga, sistema):
        # Caso LIMITE: un segundo antes del fin todavia no se puede cerrar.
        justo_antes = clase_yoga.horario.fin - timedelta(seconds=1)
        with pytest.raises(ClaseNoHaTerminado):
            clase_yoga.registrar_no_shows(sistema, justo_antes)

    def test_solo_el_sistema_cierra_la_clase(self, clase_yoga, recepcion):
        with pytest.raises(PermisoDenegado):
            clase_yoga.registrar_no_shows(recepcion, clase_yoga.horario.fin)


class TestAdministracionDeClases:
    """BR-01 y BR-05: solo el Administrador cancela clases y fija capacidad."""

    def test_administrador_cancela_una_clase(self, clase_yoga, administrador):
        clase_yoga.cancelar(administrador)
        assert clase_yoga.estado is EstadoDeClase.CANCELADA

    @pytest.mark.parametrize("rol_actor", ["recepcion", "instructor", "socio_ana"])
    def test_otros_roles_no_pueden_cancelar_una_clase(self, clase_yoga, rol_actor, request):
        actor = request.getfixturevalue(rol_actor)
        with pytest.raises(PermisoDenegado):
            clase_yoga.cancelar(actor)
        assert clase_yoga.estado is EstadoDeClase.PROGRAMADA

    def test_administrador_fija_la_capacidad(self, clase_yoga, administrador):
        clase_yoga.configurar_capacidad(Capacidad(10), administrador)
        assert clase_yoga.capacidad.valor == 10

    def test_recepcion_no_puede_fijar_la_capacidad(self, clase_yoga, recepcion):
        with pytest.raises(PermisoDenegado):
            clase_yoga.configurar_capacidad(Capacidad(10), recepcion)

    def test_no_se_puede_bajar_la_capacidad_por_debajo_de_los_lugares_ocupados(
        self, clase_yoga, socio_ana, socio_beto, administrador, ahora
    ):
        clase_yoga.reservar("ana", socio_ana, ahora)
        clase_yoga.reservar("beto", socio_beto, ahora)
        with pytest.raises(CapacidadInvalida):
            clase_yoga.configurar_capacidad(Capacidad(1), administrador)
        assert clase_yoga.capacidad.valor == 2
