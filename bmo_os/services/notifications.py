"""Disparador de avisos de evento próximo.

Não tem thread própria — é consultado todo frame pelo `frame_hook` do App
(ver main.py). Dado o snapshot do CalendarService e a antecedência configurada
(config['event_warning_min']), decide se algum evento está prestes a começar e
ainda não foi avisado.

Cada evento só avisa uma vez por dia (guarda as chaves já disparadas; o set é
zerado quando vira o dia, pra não crescer pra sempre).
"""
from __future__ import annotations

import datetime as dt

from .gcalendar import CalEvent


def _local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


class EventAlerter:
    def __init__(self) -> None:
        self._fired: set[str] = set()
        self._fired_day: dt.date | None = None

    def check(self, events: list[CalEvent], warning_min: int) -> CalEvent | None:
        """Retorna um evento a avisar agora, ou None.

        Avisa quando faltam <= warning_min minutos pro início (e o evento
        ainda não começou). Eventos all-day não geram aviso.
        """
        now = _local_now()

        # vira o dia -> esquece o que já foi avisado
        if self._fired_day != now.date():
            self._fired_day = now.date()
            self._fired.clear()

        if warning_min <= 0:
            return None
        horizon = now + dt.timedelta(minutes=warning_min)

        for ev in events:
            if ev.all_day:
                continue
            start = ev.start
            if start.tzinfo is None:
                start = start.replace(tzinfo=now.tzinfo)
            # janela: começa entre agora e o horizonte (ainda não começou)
            if now <= start <= horizon:
                k = ev.key()
                if k not in self._fired:
                    self._fired.add(k)
                    return ev
        return None
