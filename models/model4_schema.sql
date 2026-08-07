-- Model 4: JSONB column for all translations
DROP TABLE IF EXISTS products_json CASCADE;

CREATE TABLE products_json (
    product_id SERIAL PRIMARY KEY,
    price DECIMAL(10,2) NOT NULL,
    sku VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    translations JSONB,          -- All translations as JSON
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_products_json_sku ON products_json(sku);
CREATE INDEX idx_products_json_active ON products_json(is_active) WHERE is_active = true;

-- GIN index for fast JSON traversal
CREATE INDEX idx_products_json_translations ON products_json USING GIN (translations jsonb_path_ops);

-- Optional: Expression index for specific language name lookups (e.g., Turkish)
-- Note: This does NOT help with LIKE '%a%' (substring), hence the benchmark findings.
CREATE INDEX idx_products_json_name_tr ON products_json ((translations->'tr'->>'name'));

CREATE INDEX idx_products_json_price ON products_json(price); 
ANALYZE;