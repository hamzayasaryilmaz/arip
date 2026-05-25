-- ARIP demo inventory schema.
CREATE TABLE IF NOT EXISTS inventory (
    sku   TEXT PRIMARY KEY,
    stock INTEGER NOT NULL CHECK (stock >= 0)
);

INSERT INTO inventory (sku, stock) VALUES
    ('SKU-001', 100),
    ('SKU-002', 50),
    ('SKU-003', 0)
ON CONFLICT (sku) DO NOTHING;
