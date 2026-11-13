-- =====================================================================
-- Esquema ml: resultados de los modelos de Machine Learning
-- =====================================================================
-- Los modelos leen del esquema en estrella (marts) y escriben aquí sus
-- resultados, para que Metabase y cualquier consulta SQL puedan usarlos.
-- Cada ejecución sustituye los resultados anteriores; el historial de
-- ejecuciones (con sus parámetros y métricas) se guarda en ml.ejecucion.

CREATE SCHEMA IF NOT EXISTS ml;

-- Historial de entrenamientos
CREATE TABLE IF NOT EXISTS ml.ejecucion (
    id_ejecucion  SERIAL PRIMARY KEY,
    modelo        VARCHAR(40)  NOT NULL,          -- segmentacion_clientes | prevision_ventas
    inicio        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    duracion_seg  NUMERIC(8,1),
    datos_hasta   DATE,                           -- último día de datos usado
    parametros    JSONB,
    metricas      JSONB
);

-- ---------------------------------------------------------------------
-- 8a. Segmentación de clientes (K-Means)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ml.segmento_cliente (
    id_cliente       INTEGER PRIMARY KEY,
    cluster          SMALLINT     NOT NULL,
    segmento         VARCHAR(40)  NOT NULL,
    recencia_dias    INTEGER,
    pedidos          INTEGER,
    gasto_neto       NUMERIC(12,2),
    ticket_medio     NUMERIC(10,2),
    pct_web          NUMERIC(5,4),
    tasa_devolucion  NUMERIC(5,4),
    categorias       SMALLINT,
    segmento_rfm     VARCHAR(20),                 -- el segmento por reglas de dbt, para comparar
    id_ejecucion     INTEGER REFERENCES ml.ejecucion
);

CREATE TABLE IF NOT EXISTS ml.segmento_resumen (
    segmento          VARCHAR(40) PRIMARY KEY,
    cluster           SMALLINT,
    clientes          INTEGER,
    pct_clientes      NUMERIC(5,4),
    gasto_total       NUMERIC(14,2),
    pct_gasto         NUMERIC(5,4),
    recencia_media    NUMERIC(8,1),
    pedidos_medio     NUMERIC(8,2),
    gasto_medio       NUMERIC(12,2),
    ticket_medio      NUMERIC(10,2),
    pct_web           NUMERIC(5,4),
    tasa_devolucion   NUMERIC(5,4),
    descripcion       TEXT,
    accion            TEXT,
    id_ejecucion      INTEGER REFERENCES ml.ejecucion
);

-- ---------------------------------------------------------------------
-- 8b. Previsión de ventas
-- ---------------------------------------------------------------------
-- Previsión de los próximos días con su intervalo (80 %)
CREATE TABLE IF NOT EXISTS ml.prevision_ventas (
    fecha            DATE        NOT NULL,
    canal            VARCHAR(10) NOT NULL,
    modelo           VARCHAR(40) NOT NULL,
    prevision        NUMERIC(12,2),
    limite_inferior  NUMERIC(12,2),
    limite_superior  NUMERIC(12,2),
    id_ejecucion     INTEGER REFERENCES ml.ejecucion,
    PRIMARY KEY (fecha, canal)
);

-- Backtest: lo que habría previsto cada modelo en el último trimestre, frente a lo real
CREATE TABLE IF NOT EXISTS ml.backtest_ventas (
    fecha            DATE        NOT NULL,
    canal            VARCHAR(10) NOT NULL,
    real             NUMERIC(12,2),
    media_4_semanas  NUMERIC(12,2),
    anio_anterior    NUMERIC(12,2),
    gradient_boosting NUMERIC(12,2),
    combinado        NUMERIC(12,2),
    PRIMARY KEY (fecha, canal)
);

CREATE TABLE IF NOT EXISTS ml.metricas_prevision (
    canal          VARCHAR(10) NOT NULL,
    modelo         VARCHAR(40) NOT NULL,
    wape           NUMERIC(6,4),     -- error diario: suma de |error| / suma de ventas reales
    error_mensual  NUMERIC(6,4),     -- error medio de los totales de cada mes
    sesgo          NUMERIC(6,4),     -- total previsto / total real - 1 (positivo = se pasa)
    elegido        BOOLEAN,
    id_ejecucion   INTEGER REFERENCES ml.ejecucion,
    PRIMARY KEY (canal, modelo)
);