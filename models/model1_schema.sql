-- Model 1: Row-based translation table (Normalized)
DROP TABLE IF EXISTS product_translations CASCADE;
DROP TABLE IF EXISTS products CASCADE;

-- Base product table
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    price DECIMAL(10,2) NOT NULL,
    sku VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Translation table
CREATE TABLE product_translations (
    product_id INTEGER NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    lang_code VARCHAR(5) NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    slug VARCHAR(200),
    meta_title VARCHAR(200),
    meta_description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (product_id, lang_code)
);

-- Indexes
CREATE INDEX idx_translations_lang_name ON product_translations(lang_code, name);
CREATE INDEX idx_translations_slug ON product_translations(slug);
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_active ON products(is_active) WHERE is_active = true;
CREATE INDEX idx_products_price ON products(price);

ANALYZE products;
ANALYZE product_translations;
