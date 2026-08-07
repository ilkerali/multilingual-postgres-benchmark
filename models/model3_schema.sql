-- Model 3: Single wide table with columns per language
DROP TABLE IF EXISTS products CASCADE;

CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    price DECIMAL(10,2) NOT NULL,
    sku VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    
    -- Turkish
    name_tr VARCHAR(200),
    description_tr TEXT,
    slug_tr VARCHAR(200),
    meta_title_tr VARCHAR(200),
    meta_description_tr TEXT,
    
    -- English
    name_en VARCHAR(200),
    description_en TEXT,
    slug_en VARCHAR(200),
    meta_title_en VARCHAR(200),
    meta_description_en TEXT,
    
    -- Macedonian
    name_mk VARCHAR(200),
    description_mk TEXT,
    slug_mk VARCHAR(200),
    meta_title_mk VARCHAR(200),
    meta_description_mk TEXT,
    
    -- German
    name_de VARCHAR(200),
    description_de TEXT,
    slug_de VARCHAR(200),
    meta_title_de VARCHAR(200),
    meta_description_de TEXT,
    
    -- French
    name_fr VARCHAR(200),
    description_fr TEXT,
    slug_fr VARCHAR(200),
    meta_title_fr VARCHAR(200),
    meta_description_fr TEXT,
    
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- B-tree indexes on each language's name column
CREATE INDEX idx_products_name_tr ON products(name_tr);
CREATE INDEX idx_products_name_en ON products(name_en);
CREATE INDEX idx_products_name_mk ON products(name_mk);
CREATE INDEX idx_products_name_de ON products(name_de);
CREATE INDEX idx_products_name_fr ON products(name_fr);
CREATE INDEX idx_products_price ON products(price);
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_active ON products(is_active) WHERE is_active = true;

ANALYZE;