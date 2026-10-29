MERGE dbo.products AS target
USING (VALUES
  ('SKU-001', N'Recovery Kit', 49.00),
  ('SKU-002', N'Backup Drive', 89.00)
) AS source (sku, name, price)
ON target.sku = source.sku
WHEN MATCHED THEN UPDATE SET name = source.name, price = source.price
WHEN NOT MATCHED THEN INSERT (sku, name, price) VALUES (source.sku, source.name, source.price);
