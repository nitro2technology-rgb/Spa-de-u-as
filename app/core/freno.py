"""
EL FRENO A LOS INTENTOS DE CLAVE
=================================
Quien prueba contraseñas a lo bruto se queda fuera un rato. Nada más.

Vive aquí y no en el panel porque hay DOS puertas que proteger, y la que
más importa no es la del panel:

    /admin        la de cada negocio: abre sus conversaciones
    /superadmin   la de la plataforma: abre las de TODOS, el alta, la
                  pausa y las credenciales cifradas de cada cliente

Hasta ahora solo frenaba la primera. Estaba al revés de como tiene que
estar: la puerta más privilegiada era la menos protegida, y detrás hay una
clave que se inventó un humano.

EN MEMORIA, A PROPÓSITO
-----------------------
Sin Redis ni tabla nueva. Se pierde al reiniciar el servicio y no se
comparte entre procesos — que hoy da igual, porque el bus de avisos en
vivo ya obliga a un solo proceso (ver `app/core/eventos.py`).

Cuenta por IP y no por negocio: es más estricto de lo necesario, no menos,
y sin sesión todavía no hay negocio que contar.
"""

import time

from app import config


def ip_de(request) -> str:
    """
    Quién está llamando. Detrás del proxy de Render la IP real viene en
    X-Forwarded-For; `request.client` sería siempre la del proxy.
    """
    reenviado = request.headers.get("X-Forwarded-For", "")
    if reenviado:
        return reenviado.split(",")[0].strip()
    return request.client.host if request.client else "desconocida"


class Freno:
    """
    Un contador de fallos por IP, con su ventana de olvido.

    Los plazos se leen de `config` en cada llamada, no al construirlo: son
    ajustes del sistema (los mismos para todo el despliegue), pero leerlos
    tarde permite cambiarlos en las pruebas sin rehacer el objeto.
    """

    def __init__(self, etiqueta: str):
        self.etiqueta = etiqueta      # lo que sale en el log: [panel], [superadmin]
        self._intentos: dict[str, list[float]] = {}

    @property
    def minutos(self) -> int:
        return config.PANEL_BLOQUEO_LOGIN_MINUTOS

    @property
    def maximo(self) -> int:
        return config.PANEL_MAX_INTENTOS_LOGIN

    def bloqueado(self, request) -> bool:
        limite = time.time() - self.minutos * 60
        ip = ip_de(request)
        fallos = [t for t in self._intentos.get(ip, []) if t > limite]
        self._intentos[ip] = fallos
        return len(fallos) >= self.maximo

    # Por encima de esto se barren las IPs cuyos fallos ya caducaron. Sin
    # barrido, cada IP que falla una vez se quedaba en memoria para siempre,
    # y quien cambie de IP en cada intento haría crecer esto sin límite.
    TOPE_IPS = 5000

    def anotar_fallo(self, request):
        ip = ip_de(request)
        self._intentos.setdefault(ip, []).append(time.time())
        if len(self._intentos) > self.TOPE_IPS:
            self._barrer()
        print(f"[{self.etiqueta}] Clave incorrecta desde {ip}.")

    def _barrer(self):
        limite = time.time() - self.minutos * 60
        for ip in [i for i, fallos in self._intentos.items()
                   if not any(t > limite for t in fallos)]:
            self._intentos.pop(ip, None)

    def olvidar(self, request):
        """Entró bien: se le perdonan los fallos anteriores."""
        self._intentos.pop(ip_de(request), None)

    def aviso(self) -> str:
        return (f"Demasiados intentos fallidos. Espera {self.minutos} "
                f"minutos e inténtalo otra vez.")

    def clear(self):
        """Solo para las pruebas: olvida a todo el mundo."""
        self._intentos.clear()
