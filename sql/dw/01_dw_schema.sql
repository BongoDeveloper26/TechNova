-- =====================================================================
--  TechNova Data Platform
--  sql/dw/01_dw_schema.sql  ->  Estructura de la base de datos analítica
--
--  Se ejecuta en la base de datos "technova_dw" (separada de la OLTP).
--  En una empresa, la base de datos de la tienda y la de análisis están
--  separadas: así los informes pesados nunca ralentizan las ventas.
--
--  Esquemas:
--    staging -> datos tal y como llegan de las fuentes (ya validados)
--    etl     -> tablas de control: ejecuciones, rechazos, calidad...
--
--  Es idempotente (IF NOT EXISTS): se puede ejecutar todas las veces que haga falta.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS etl;

-- ---------------------------------------------------------------------
--  CONTROL DEL ETL
-- ---------------------------------------------------------------------

-- Una fila por cada vez que se lanza el ETL
CREATE TABLE IF NOT EXISTS etl.ejecucion (
    id_ejecucion  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha_proceso DATE        NOT NULL,
    inicio        TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin           TIMESTAMPTZ,
    estado        VARCHAR(10) NOT NULL DEFAULT 'en_curso'
                  CHECK (estado IN ('en_curso', 'ok', 'aviso', 'error')),
    parametros    JSONB
);

-- Una fila por cada paso de una ejecución (extraer OLTP, divisas, proveedores...)
CREATE TABLE IF NOT EXISTS etl.paso (
    id_paso          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_ejecucion     BIGINT      NOT NULL REFERENCES etl.ejecucion(id_ejecucion),
    nombre           VARCHAR(80) NOT NULL,
    inicio           TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin              TIMESTAMPTZ,
    estado           VARCHAR(10) NOT NULL DEFAULT 'en_curso'
                     CHECK (estado IN ('en_curso', 'ok', 'aviso', 'error')),
    filas_leidas     INTEGER,
    filas_cargadas   INTEGER,
    filas_rechazadas INTEGER,
    detalle          TEXT
);

-- Marca de agua: hasta dónde se cargó cada tabla en la última ejecución (carga incremental)
CREATE TABLE IF NOT EXISTS etl.watermark (
    tabla          VARCHAR(60) PRIMARY KEY,
    columna        VARCHAR(60) NOT NULL,
    valor          TEXT        NOT NULL,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Filas que no han pasado las validaciones, con el motivo y la fila original
CREATE TABLE IF NOT EXISTS etl.rechazo (
    id_rechazo   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_ejecucion BIGINT      NOT NULL REFERENCES etl.ejecucion(id_ejecucion),
    fuente       VARCHAR(40) NOT NULL,
    fichero      VARCHAR(200),
    num_fila     INTEGER,
    motivo       VARCHAR(40) NOT NULL,
    datos        JSONB,
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rechazo_ejecucion ON etl.rechazo (id_ejecucion);

-- Ficheros ya procesados: evita cargar dos veces el mismo fichero.
-- Si el proveedor reenvía un fichero corregido (mismo nombre, contenido distinto),
-- el hash cambia y se vuelve a procesar.
CREATE TABLE IF NOT EXISTS etl.fichero_procesado (
    nombre_fichero   VARCHAR(200) NOT NULL,
    hash_sha256      CHAR(64)     NOT NULL,
    id_ejecucion     BIGINT       NOT NULL REFERENCES etl.ejecucion(id_ejecucion),
    procesado_en     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    estado           VARCHAR(10)  NOT NULL CHECK (estado IN ('cargado', 'descartado')),
    filas_totales    INTEGER      NOT NULL,
    filas_validas    INTEGER      NOT NULL,
    filas_rechazadas INTEGER      NOT NULL,
    PRIMARY KEY (nombre_fichero, hash_sha256)
);

-- Resultado de cada control de calidad
CREATE TABLE IF NOT EXISTS etl.control_calidad (
    id_control      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_ejecucion    BIGINT      NOT NULL REFERENCES etl.ejecucion(id_ejecucion),
    nombre          VARCHAR(80) NOT NULL,
    severidad       VARCHAR(10) NOT NULL CHECK (severidad IN ('error', 'aviso')),
    filas_afectadas INTEGER     NOT NULL,
    resultado       VARCHAR(10) NOT NULL CHECK (resultado IN ('ok', 'fallo')),
    descripcion     TEXT,
    ejecutado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
--  STAGING DE FUENTES EXTERNAS
--  (las tablas staging.oltp_* se crean solas, copiando la estructura de la OLTP)
-- ---------------------------------------------------------------------

-- Tipos de cambio del BCE: unidades de moneda por 1 €
CREATE TABLE IF NOT EXISTS staging.tipo_cambio (
    fecha          DATE          NOT NULL,
    moneda         CHAR(3)       NOT NULL,
    tasa           NUMERIC(14,6) NOT NULL CHECK (tasa > 0),
    es_interpolado BOOLEAN       NOT NULL DEFAULT FALSE,  -- fin de semana / festivo: se arrastra el último valor
    fuente         VARCHAR(20)   NOT NULL,
    cargado_en     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (fecha, moneda)
);

-- Tarifas diarias que envían los proveedores (ya limpias y convertidas a euros)
CREATE TABLE IF NOT EXISTS staging.proveedor_tarifa (
    fecha_tarifa       DATE          NOT NULL,
    id_proveedor       INTEGER       NOT NULL,
    sku                VARCHAR(30)   NOT NULL,
    descripcion        VARCHAR(200),
    moneda             CHAR(3)       NOT NULL,
    precio_coste       NUMERIC(14,2) NOT NULL CHECK (precio_coste > 0),
    tipo_cambio        NUMERIC(14,6) NOT NULL,
    precio_coste_eur   NUMERIC(12,2) NOT NULL CHECK (precio_coste_eur > 0),
    stock_disponible   INTEGER       NOT NULL CHECK (stock_disponible >= 0),
    plazo_entrega_dias INTEGER       CHECK (plazo_entrega_dias >= 0),
    fichero            VARCHAR(200)  NOT NULL,
    cargado_en         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (fecha_tarifa, id_proveedor, sku)
);

-- ---------------------------------------------------------------------
--  STAGING DE RECURSOS HUMANOS (de los Excel mensuales)
-- ---------------------------------------------------------------------

-- Un fichaje por empleado y día
CREATE TABLE IF NOT EXISTS staging.rrhh_fichaje (
    fecha        DATE         NOT NULL,
    id_empleado  INTEGER      NOT NULL,
    id_ubicacion INTEGER      NOT NULL,
    entrada      TIME         NOT NULL,
    salida       TIME         NOT NULL,
    pausa_min    INTEGER      NOT NULL CHECK (pausa_min >= 0),
    horas        NUMERIC(5,2) NOT NULL CHECK (horas > 0 AND horas <= 14),  -- recalculadas, no las del Excel
    fichero      VARCHAR(200) NOT NULL,
    cargado_en   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (fecha, id_empleado)
);

-- Ausencias (la parte de cada una que cae dentro del mes del fichero)
CREATE TABLE IF NOT EXISTS staging.rrhh_ausencia (
    id_empleado INTEGER      NOT NULL,
    tipo        VARCHAR(20)  NOT NULL
                CHECK (tipo IN ('vacaciones', 'baja_medica', 'asuntos_propios', 'permiso')),
    desde       DATE         NOT NULL,
    hasta       DATE         NOT NULL,
    fichero     VARCHAR(200) NOT NULL,
    cargado_en  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (id_empleado, desde),
    CHECK (hasta >= desde)
);

-- Una nómina por empleado y mes
CREATE TABLE IF NOT EXISTS staging.rrhh_nomina (
    mes                 DATE          NOT NULL,   -- primer día del mes
    id_empleado         INTEGER       NOT NULL,
    salario_base        NUMERIC(10,2) NOT NULL CHECK (salario_base >= 0),
    plus_ventas         NUMERIC(10,2) NOT NULL CHECK (plus_ventas >= 0),
    horas_extra         NUMERIC(6,2)  NOT NULL CHECK (horas_extra >= 0),
    importe_horas_extra NUMERIC(10,2) NOT NULL CHECK (importe_horas_extra >= 0),
    total_devengado     NUMERIC(10,2) NOT NULL,
    ss_empresa          NUMERIC(10,2) NOT NULL,
    coste_total         NUMERIC(10,2) NOT NULL,
    fichero             VARCHAR(200)  NOT NULL,
    cargado_en          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (mes, id_empleado)
);