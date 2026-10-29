IF OBJECT_ID('dbo.products') IS NULL
  CREATE TABLE dbo.products (
    sku        NVARCHAR(32)  NOT NULL PRIMARY KEY,
    name       NVARCHAR(100) NOT NULL,
    price      DECIMAL(10,2) NOT NULL
  );
IF OBJECT_ID('dbo.orders') IS NULL
  CREATE TABLE dbo.orders (
    order_id   UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
    drill_id   NVARCHAR(64)     NULL,
    sku        NVARCHAR(32)     NOT NULL REFERENCES dbo.products(sku),
    status     NVARCHAR(16)     NOT NULL,
    created_at DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
  );
IF OBJECT_ID('dbo.payment_authorizations') IS NULL
  CREATE TABLE dbo.payment_authorizations (
    auth_id    UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
    order_id   UNIQUEIDENTIFIER NOT NULL REFERENCES dbo.orders(order_id),
    amount     DECIMAL(10,2)    NOT NULL,
    created_at DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
  );
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_orders_drill_id')
  CREATE INDEX ix_orders_drill_id ON dbo.orders (drill_id);
