"""
registro.py -> Trazabilidad del ETL.

Todo lo que hace el ETL queda apuntado en dos sitios:
  1. Un log de texto (logs/etl.log) para leerlo a mano.
  2. Las tablas etl.ejecucion y etl.paso, para consultarlo con SQL
     ("¿cuántas filas se rechazaron ayer?", "¿qué paso falló?").

Una ejecución puede abrirse en un proceso y continuarse en otros:
Airflow lanza cada paso en un proceso distinto y se pasan el id de la ejecución.
"""
import json
import logging
import time
from contextlib import contextmanager

from configuracion import CARPETA_LOGS

ORDEN_ESTADOS = {"ok": 0, "aviso": 1, "error": 2}


def configurar_logs() -> logging.Logger:
    CARPETA_LOGS.mkdir(exist_ok=True)
    formato = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
    logger = logging.getLogger("etl")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        consola = logging.StreamHandler()
        consola.setFormatter(formato)
        fichero = logging.FileHandler(CARPETA_LOGS / "etl.log", encoding="utf-8")
        fichero.setFormatter(formato)
        logger.addHandler(consola)
        logger.addHandler(fichero)
    return logger


log = configurar_logs()


class ResultadoPaso:
    """Lo que cada paso va rellenando: filas leídas, cargadas, rechazadas..."""

    def __init__(self):
        self.leidas = 0
        self.cargadas = 0
        self.rechazadas = 0
        self.estado = "ok"
        self.detalle = []

    def aviso(self, mensaje):
        self.estado = "aviso" if self.estado == "ok" else self.estado
        self.detalle.append(mensaje)
        log.warning(mensaje)


class Ejecucion:
    """Representa una ejecución completa del ETL (una fila en etl.ejecucion)."""

    def __init__(self, conn_dw, id_ejecucion):
        """Retoma una ejecución que ya existe (la abrió otro proceso o esta misma)."""
        fila = conn_dw.execute(
            "SELECT fecha_proceso FROM etl.ejecucion WHERE id_ejecucion = %s", (id_ejecucion,)
        ).fetchone()
        if fila is None:
            raise ValueError(f"No existe la ejecución {id_ejecucion}")
        self.conn = conn_dw
        self.id = id_ejecucion
        self.fecha_proceso = fila[0]

    @classmethod
    def nueva(cls, conn_dw, fecha_proceso, parametros):
        id_ejecucion = conn_dw.execute(
            "INSERT INTO etl.ejecucion (fecha_proceso, parametros) VALUES (%s, %s) RETURNING id_ejecucion",
            (fecha_proceso, json.dumps(parametros, default=str)),
        ).fetchone()[0]
        conn_dw.commit()
        log.info(f"===== Ejecución #{id_ejecucion} | fecha de proceso {fecha_proceso} =====")
        return cls(conn_dw, id_ejecucion)

    @contextmanager
    def paso(self, nombre):
        """
        Uso:
            with ejecucion.paso("Cargar divisas") as r:
                ...
                r.cargadas = 100

        Si dentro hay una excepción, se deshace lo que hiciera el paso (rollback)
        y se apunta el error. Quien llama decide si continuar o parar.
        """
        id_paso = self.conn.execute(
            "INSERT INTO etl.paso (id_ejecucion, nombre) VALUES (%s, %s) RETURNING id_paso",
            (self.id, nombre),
        ).fetchone()[0]
        self.conn.commit()
        log.info(f"-> {nombre}")
        resultado, inicio = ResultadoPaso(), time.perf_counter()

        try:
            yield resultado
            self.conn.commit()
        except Exception as error:  # noqa: BLE001 - queremos registrar cualquier fallo
            self.conn.rollback()
            resultado.estado = "error"
            resultado.detalle.append(f"{type(error).__name__}: {error}")
            log.exception(f"   ERROR en '{nombre}': {error}")

        segundos = time.perf_counter() - inicio
        self.conn.execute(
            """UPDATE etl.paso SET fin = now(), estado = %s, filas_leidas = %s, filas_cargadas = %s,
                                  filas_rechazadas = %s, detalle = %s
               WHERE id_paso = %s""",
            (resultado.estado, resultado.leidas, resultado.cargadas, resultado.rechazadas,
             "\n".join(resultado.detalle) or None, id_paso),
        )
        self.conn.commit()
        log.info(f"   {resultado.estado.upper()} | leídas {resultado.leidas} | cargadas {resultado.cargadas}"
                 f" | rechazadas {resultado.rechazadas} | {segundos:.1f} s")

    def cerrar(self) -> str:
        """
        El estado final es el PEOR estado del último intento de cada paso
        (si un paso falló y Airflow lo reintentó con éxito, cuenta el éxito).
        """
        estados = [fila[0] for fila in self.conn.execute(
            """SELECT DISTINCT ON (nombre) estado
               FROM etl.paso WHERE id_ejecucion = %s
               ORDER BY nombre, id_paso DESC""",
            (self.id,),
        ).fetchall()]
        estado = max(estados, key=ORDEN_ESTADOS.get, default="ok")
        if estado == "en_curso":
            estado = "error"
        self.conn.execute(
            "UPDATE etl.ejecucion SET fin = now(), estado = %s WHERE id_ejecucion = %s",
            (estado, self.id),
        )
        self.conn.commit()
        log.info(f"===== Ejecución #{self.id} terminada: {estado.upper()} =====")
        return estado