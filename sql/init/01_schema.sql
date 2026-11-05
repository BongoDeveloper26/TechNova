-- =====================================================================
--  TechNova Data Platform
--  01_schema.sql  ->  Esquema OLTP (base de datos operacional de la tienda)
--  22 tablas. El orden importa: una tabla solo puede apuntar (FK)
--  a tablas que ya existen.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS oltp;
SET search_path TO oltp;

-- =====================================================================
--  1. CLIENTES
-- =====================================================================

CREATE TABLE nivel_fidelidad (
    id_nivel        SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre          VARCHAR(20)  NOT NULL UNIQUE,
    puntos_minimos  INTEGER      NOT NULL CHECK (puntos_minimos >= 0),
    descuento_pct   NUMERIC(5,2) NOT NULL DEFAULT 0
                    CHECK (descuento_pct BETWEEN 0 AND 100)
);

CREATE TABLE ciudad (
    id_ciudad  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre     VARCHAR(100) NOT NULL,
    provincia  VARCHAR(100) NOT NULL,
    pais       VARCHAR(60)  NOT NULL DEFAULT 'España',
    UNIQUE (nombre, provincia)
);

CREATE TABLE cliente (
    id_cliente       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre           VARCHAR(60)  NOT NULL,
    apellidos        VARCHAR(100) NOT NULL,
    email            VARCHAR(150) NOT NULL UNIQUE,
    telefono         VARCHAR(20),
    fecha_nacimiento DATE,
    fecha_registro   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    puntos           INTEGER      NOT NULL DEFAULT 0 CHECK (puntos >= 0),
    id_nivel         SMALLINT     NOT NULL REFERENCES nivel_fidelidad(id_nivel)
);

CREATE TABLE direccion (
    id_direccion  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_cliente    INTEGER      NOT NULL REFERENCES cliente(id_cliente) ON DELETE CASCADE,
    calle         VARCHAR(200) NOT NULL,
    codigo_postal VARCHAR(10)  NOT NULL,
    id_ciudad     INTEGER      NOT NULL REFERENCES ciudad(id_ciudad),
    es_principal  BOOLEAN      NOT NULL DEFAULT FALSE
);

-- =====================================================================
--  2. CATÁLOGO
-- =====================================================================

CREATE TABLE categoria (
    id_categoria       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre             VARCHAR(100) NOT NULL,
    id_categoria_padre INTEGER REFERENCES categoria(id_categoria)  -- auto-relación
);

CREATE TABLE marca (
    id_marca    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre      VARCHAR(100) NOT NULL UNIQUE,
    pais_origen VARCHAR(60)
);

CREATE TABLE producto (
    id_producto    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku            VARCHAR(30)   NOT NULL UNIQUE,
    nombre         VARCHAR(200)  NOT NULL,
    id_categoria   INTEGER       NOT NULL REFERENCES categoria(id_categoria),
    id_marca       INTEGER       NOT NULL REFERENCES marca(id_marca),
    precio_venta   NUMERIC(10,2) NOT NULL CHECK (precio_venta > 0),
    coste          NUMERIC(10,2) NOT NULL CHECK (coste > 0),
    meses_garantia SMALLINT      NOT NULL DEFAULT 24 CHECK (meses_garantia >= 0),
    activo         BOOLEAN       NOT NULL DEFAULT TRUE,
    fecha_alta     DATE          NOT NULL DEFAULT CURRENT_DATE,
    CHECK (precio_venta >= coste)
);

-- =====================================================================
--  3. UBICACIONES, STOCK Y PERSONAL
-- =====================================================================

CREATE TABLE ubicacion (
    id_ubicacion   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre         VARCHAR(100) NOT NULL,
    tipo           VARCHAR(10)  NOT NULL CHECK (tipo IN ('tienda', 'almacen')),
    id_ciudad      INTEGER      NOT NULL REFERENCES ciudad(id_ciudad),
    direccion      VARCHAR(200) NOT NULL,
    fecha_apertura DATE         NOT NULL
);

CREATE TABLE stock (
    id_producto         INTEGER   NOT NULL REFERENCES producto(id_producto),
    id_ubicacion        INTEGER   NOT NULL REFERENCES ubicacion(id_ubicacion),
    cantidad            INTEGER   NOT NULL DEFAULT 0 CHECK (cantidad >= 0),
    stock_minimo        INTEGER   NOT NULL DEFAULT 5 CHECK (stock_minimo >= 0),
    fecha_actualizacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id_producto, id_ubicacion)                -- clave compuesta
);

CREATE TABLE empleado (
    id_empleado        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre             VARCHAR(60)  NOT NULL,
    apellidos          VARCHAR(100) NOT NULL,
    puesto             VARCHAR(50)  NOT NULL,
    id_ubicacion       INTEGER      NOT NULL REFERENCES ubicacion(id_ubicacion),
    id_jefe            INTEGER      REFERENCES empleado(id_empleado),  -- auto-relación
    fecha_contratacion DATE         NOT NULL
);

-- =====================================================================
--  4. COMPRAS A PROVEEDORES
-- =====================================================================

CREATE TABLE proveedor (
    id_proveedor INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre       VARCHAR(150) NOT NULL,
    cif          VARCHAR(20)  NOT NULL UNIQUE,
    pais         VARCHAR(60)  NOT NULL,
    moneda       CHAR(3)      NOT NULL DEFAULT 'EUR',
    email        VARCHAR(150)
);

CREATE TABLE pedido_compra (
    id_pedido_compra INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_proveedor     INTEGER       NOT NULL REFERENCES proveedor(id_proveedor),
    id_ubicacion     INTEGER       NOT NULL REFERENCES ubicacion(id_ubicacion),
    fecha_pedido     DATE          NOT NULL,
    fecha_recepcion  DATE,
    estado           VARCHAR(15)   NOT NULL DEFAULT 'pendiente'
                     CHECK (estado IN ('pendiente', 'enviado', 'recibido', 'cancelado')),
    tipo_cambio      NUMERIC(10,6) NOT NULL DEFAULT 1 CHECK (tipo_cambio > 0),
    CHECK (fecha_recepcion IS NULL OR fecha_recepcion >= fecha_pedido)
);

CREATE TABLE linea_compra (
    id_pedido_compra INTEGER       NOT NULL REFERENCES pedido_compra(id_pedido_compra) ON DELETE CASCADE,
    id_producto      INTEGER       NOT NULL REFERENCES producto(id_producto),
    cantidad         INTEGER       NOT NULL CHECK (cantidad > 0),
    coste_unitario   NUMERIC(10,2) NOT NULL CHECK (coste_unitario > 0),
    PRIMARY KEY (id_pedido_compra, id_producto)
);

-- =====================================================================
--  5. MARKETING (va antes que ventas porque pedido apunta a cupon)
-- =====================================================================

CREATE TABLE promocion (
    id_promocion   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre         VARCHAR(100)  NOT NULL,
    tipo_descuento VARCHAR(10)   NOT NULL CHECK (tipo_descuento IN ('porcentaje', 'fijo')),
    valor          NUMERIC(10,2) NOT NULL CHECK (valor > 0),
    fecha_inicio   DATE          NOT NULL,
    fecha_fin      DATE          NOT NULL,
    CHECK (fecha_fin >= fecha_inicio),
    CHECK (tipo_descuento <> 'porcentaje' OR valor <= 100)
);

CREATE TABLE promocion_producto (                          -- tabla intermedia N:M
    id_promocion INTEGER NOT NULL REFERENCES promocion(id_promocion) ON DELETE CASCADE,
    id_producto  INTEGER NOT NULL REFERENCES producto(id_producto),
    PRIMARY KEY (id_promocion, id_producto)
);

CREATE TABLE cupon (
    id_cupon        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo          VARCHAR(30) NOT NULL UNIQUE,
    id_promocion    INTEGER     NOT NULL REFERENCES promocion(id_promocion),
    fecha_caducidad DATE        NOT NULL,
    usos_maximos    INTEGER     NOT NULL DEFAULT 1 CHECK (usos_maximos > 0)
);

-- =====================================================================
--  6. VENTAS
-- =====================================================================

CREATE TABLE pedido (
    id_pedido    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_cliente   INTEGER     NOT NULL REFERENCES cliente(id_cliente),
    canal        VARCHAR(10) NOT NULL CHECK (canal IN ('web', 'tienda')),
    id_ubicacion INTEGER     REFERENCES ubicacion(id_ubicacion),
    id_empleado  INTEGER     REFERENCES empleado(id_empleado),
    id_cupon     INTEGER     REFERENCES cupon(id_cupon),
    fecha        TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    estado       VARCHAR(15) NOT NULL DEFAULT 'pendiente'
                 CHECK (estado IN ('pendiente', 'pagado', 'enviado', 'entregado', 'cancelado', 'devuelto')),
    -- Regla de negocio: venta en tienda => tienda y empleado obligatorios
    --                   venta web       => sin empleado
    CHECK (
        (canal = 'tienda' AND id_ubicacion IS NOT NULL AND id_empleado IS NOT NULL)
        OR
        (canal = 'web' AND id_empleado IS NULL)
    )
);

CREATE TABLE linea_pedido (
    id_linea        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_pedido       INTEGER       NOT NULL REFERENCES pedido(id_pedido) ON DELETE CASCADE,
    id_producto     INTEGER       NOT NULL REFERENCES producto(id_producto),
    cantidad        INTEGER       NOT NULL CHECK (cantidad > 0),
    precio_unitario NUMERIC(10,2) NOT NULL CHECK (precio_unitario >= 0),  -- precio histórico
    descuento       NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (descuento >= 0),
    UNIQUE (id_pedido, id_producto)
);

CREATE TABLE pago (
    id_pago   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_pedido INTEGER       NOT NULL REFERENCES pedido(id_pedido),
    metodo    VARCHAR(15)   NOT NULL
              CHECK (metodo IN ('tarjeta', 'paypal', 'bizum', 'efectivo', 'financiado')),
    importe   NUMERIC(10,2) NOT NULL CHECK (importe > 0),
    fecha     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    estado    VARCHAR(15)   NOT NULL DEFAULT 'completado'
              CHECK (estado IN ('pendiente', 'completado', 'fallido', 'reembolsado'))
);

CREATE TABLE envio (
    id_envio      INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_pedido     INTEGER     NOT NULL UNIQUE REFERENCES pedido(id_pedido),  -- 1:1
    id_direccion  INTEGER     NOT NULL REFERENCES direccion(id_direccion),
    transportista VARCHAR(50) NOT NULL,
    fecha_envio   TIMESTAMP,
    fecha_entrega TIMESTAMP,
    estado        VARCHAR(15) NOT NULL DEFAULT 'preparando'
                  CHECK (estado IN ('preparando', 'en_transito', 'entregado', 'incidencia')),
    CHECK (fecha_entrega IS NULL OR fecha_entrega >= fecha_envio)
);

-- =====================================================================
--  7. POSTVENTA
-- =====================================================================

CREATE TABLE devolucion (
    id_devolucion     INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_linea          INTEGER       NOT NULL REFERENCES linea_pedido(id_linea),
    cantidad          INTEGER       NOT NULL CHECK (cantidad > 0),
    motivo            VARCHAR(30)   NOT NULL
                      CHECK (motivo IN ('defectuoso', 'no_es_lo_esperado', 'error_pedido', 'llego_tarde', 'otro')),
    fecha             TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    estado            VARCHAR(15)   NOT NULL DEFAULT 'solicitada'
                      CHECK (estado IN ('solicitada', 'aceptada', 'rechazada', 'reembolsada')),
    importe_reembolso NUMERIC(10,2) CHECK (importe_reembolso >= 0)
);

CREATE TABLE garantia (
    id_garantia       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_linea          INTEGER      NOT NULL REFERENCES linea_pedido(id_linea),
    fecha_reclamacion DATE         NOT NULL DEFAULT CURRENT_DATE,
    problema          VARCHAR(255) NOT NULL,
    estado            VARCHAR(15)  NOT NULL DEFAULT 'abierta'
                      CHECK (estado IN ('abierta', 'en_reparacion', 'reparado', 'sustituido', 'rechazada'))
);
