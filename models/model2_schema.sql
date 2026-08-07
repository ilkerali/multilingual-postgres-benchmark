-- Model 2: Separate table per language
DROP TABLE IF EXISTS products_de CASCADE;
DROP TABLE IF EXISTS products_fr CASCADE;
DROP TABLE IF EXISTS products_mk CASCADE;
DROP TABLE IF EXISTS products_en CASCADE;
DROP TABLE IF EXISTS products_tr CASCADE;
DROP TABLE IF EXISTS products CASCADE;

-- Base product table (identical in Models 1, 2 and 3)
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    price DECIMAL(10,2) NOT NULL,
    sku VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Turkish
CREATE TABLE products_tr (
    product_id INTEGER PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    slug VARCHAR(200),
    meta_title VARCHAR(200),
    meta_description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- English
CREATE TABLE products_en (
    product_id INTEGER PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    slug VARCHAR(200),
    meta_title VARCHAR(200),
    meta_description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Macedonian
CREATE TABLE products_mk (
    product_id INTEGER PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    slug VARCHAR(200),
    meta_title VARCHAR(200),
    meta_description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- German
CREATE TABLE products_de (
    product_id INTEGER PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    slug VARCHAR(200),
    meta_title VARCHAR(200),
    meta_description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- French
CREATE TABLE products_fr (
    product_id INTEGER PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    slug VARCHAR(200),
    meta_title VARCHAR(200),
    meta_description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for text search
CREATE INDEX idx_products_tr_name ON products_tr(name);
CREATE INDEX idx_products_en_name ON products_en(name);
CREATE INDEX idx_products_mk_name ON products_mk(name);
CREATE INDEX idx_products_de_name ON products_de(name);
CREATE INDEX idx_products_fr_name ON products_fr(name);
CREATE INDEX idx_products_price ON products(price);
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_active ON products(is_active) WHERE is_active = true;

ANALYZE;