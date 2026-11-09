-- =====================================================================
--  TechNova Data Platform
--  02_indices.sql  ->  Índices del esquema OLTP
--
--  PostgreSQL crea índices automáticamente para PRIMARY KEY y UNIQUE,
--  pero NO para las claves foráneas. Sin ellos, cada JOIN o búsqueda
--  por FK recorre la tabla entera (Seq Scan).
--
--  Regla del "prefijo izquierdo": un índice compuesto (a, b) sirve para
--  buscar por "a" o por "a + b", pero NO solo por "b". Por eso, cuando
--  una PK/UNIQUE compuesta ya empieza por una FK, no repetimos el índice.
-- =====================================================================

SET search_path TO oltp;

-- ---------------------------------------------------------------------
--  1. Índices en claves foráneas (los más importantes)
-- ---------------------------------------------------------------------

-- Clientes
CREATE INDEX idx_cliente_nivel            ON cliente (id_nivel);
CREATE INDEX idx_direccion_cliente        ON direccion (id_cliente);
CREATE INDEX idx_direccion_ciudad         ON direccion (id_ciudad);

-- Catálogo
CREATE INDEX idx_categoria_padre          ON categoria (id_categoria_padre);
CREATE INDEX idx_producto_categoria       ON producto (id_categoria);
CREATE INDEX idx_producto_marca           ON producto (id_marca);

-- Ubicaciones y personal
CREATE INDEX idx_ubicacion_ciudad         ON ubicacion (id_ciudad);
CREATE INDEX idx_stock_ubicacion          ON stock (id_ubicacion);      -- la PK ya empieza por id_producto
CREATE INDEX idx_empleado_ubicacion       ON empleado (id_ubicacion);
CREATE INDEX idx_empleado_jefe            ON empleado (id_jefe);

-- Compras
CREATE INDEX idx_pedido_compra_proveedor  ON pedido_compra (id_proveedor);
CREATE INDEX idx_pedido_compra_ubicacion  ON pedido_compra (id_ubicacion);
CREATE INDEX idx_linea_compra_producto    ON linea_compra (id_producto); -- la PK ya empieza por id_pedido_compra

-- Marketing
CREATE INDEX idx_promocion_producto_prod  ON promocion_producto (id_producto);
CREATE INDEX idx_cupon_promocion          ON cupon (id_promocion);

-- Ventas
CREATE INDEX idx_pedido_cliente           ON pedido (id_cliente);
CREATE INDEX idx_pedido_ubicacion         ON pedido (id_ubicacion);
CREATE INDEX idx_pedido_empleado          ON pedido (id_empleado);
CREATE INDEX idx_linea_pedido_producto    ON linea_pedido (id_producto); -- UNIQUE(id_pedido, id_producto) ya cubre id_pedido
CREATE INDEX idx_pago_pedido              ON pago (id_pedido);
CREATE INDEX idx_envio_direccion          ON envio (id_direccion);       -- id_pedido ya es UNIQUE

-- Postventa
CREATE INDEX idx_devolucion_linea         ON devolucion (id_linea);
CREATE INDEX idx_garantia_linea           ON garantia (id_linea);

-- ---------------------------------------------------------------------
--  2. Índices para consultas frecuentes (no son FK)
-- ---------------------------------------------------------------------

-- Informes por fechas: "ventas de noviembre", "pedidos de hoy"...
CREATE INDEX idx_pedido_fecha             ON pedido (fecha);

-- ÍNDICE PARCIAL: solo indexa las filas que cumplen el WHERE.
-- Atención al cliente consulta a diario las devoluciones sin resolver,
-- que son muy pocas: el índice es diminuto y rapidísimo.
CREATE INDEX idx_devolucion_pendiente     ON devolucion (fecha) WHERE estado = 'solicitada';

-- Cupones: solo un pequeño % de pedidos lo usa, no tiene sentido indexar los NULL
CREATE INDEX idx_pedido_cupon             ON pedido (id_cupon) WHERE id_cupon IS NOT NULL;

-- ÍNDICE DE EXPRESIÓN: el login busca el email sin distinguir mayúsculas.
-- Un índice normal sobre "email" NO sirve para WHERE LOWER(email) = '...'
CREATE INDEX idx_cliente_email_lower      ON cliente (LOWER(email));

-- ÍNDICE COMPUESTO: "historial de pedidos de un cliente, del más reciente al más antiguo"
-- Resuelve el filtro y el ORDER BY con un solo índice (sin ordenar después).
CREATE INDEX idx_pedido_cliente_fecha     ON pedido (id_cliente, fecha DESC);