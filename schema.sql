CREATE TYPE location_type AS ENUM ('WAREHOUSE', 'WORK_CENTER');

CREATE TYPE execution_mode AS ENUM ('Single', 'Batch');

CREATE TYPE workcenterstatus AS ENUM ('Available', 'Busy', 'UnderMaintenance');

CREATE TYPE item_type AS ENUM ('RAW_MATERIAL', 'WIP', 'FINISHED_GOOD', 'CONSUMABLE');

CREATE TYPE diestatus AS ENUM ('Draft', 'Waiting', 'Ready', 'InProduction', 'Completed');

CREATE TYPE orderstatus AS ENUM ('Waiting', 'InProgress', 'Completed', 'Cancelled');

CREATE TYPE operation_status AS ENUM ('Waiting', 'InProgress', 'Completed', 'Paused', 'Cancelled');

CREATE TYPE transaction_type AS ENUM ('RECEIVE', 'PARTIAL_CONSUME', 'WIP_CREATED', 'LOCATION_MOVE', 'SCRAP', 'ADJUSTMENT', 'BATCH_PROCESS', 'FINISHED');

CREATE TYPE batch_status AS ENUM ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED');

CREATE TYPE operator_role AS ENUM ('Operator', 'QualityControl', 'Supervisor', 'Manager');

CREATE TABLE users (
	id SERIAL NOT NULL, 
	username VARCHAR(50) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	surname VARCHAR(100) NOT NULL, 
	email VARCHAR(255), 
	password_hash VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	is_admin BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_users_email ON users (email);

CREATE UNIQUE INDEX ix_users_username ON users (username);

CREATE INDEX ix_users_id ON users (id);

CREATE TABLE files (
	id SERIAL NOT NULL, 
	entity_type VARCHAR NOT NULL, 
	entity_id INTEGER NOT NULL, 
	original_name VARCHAR NOT NULL, 
	storage_path VARCHAR NOT NULL, 
	mime_type VARCHAR, 
	size_bytes BIGINT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (storage_path)
);

CREATE INDEX ix_files_id ON files (id);

CREATE TABLE item_category (
	id SERIAL NOT NULL, 
	name VARCHAR NOT NULL, 
	base_uom VARCHAR(20) NOT NULL, 
	is_cuttable BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE INDEX ix_item_category_id ON item_category (id);

CREATE TABLE material_grade (
	id SERIAL NOT NULL, 
	name VARCHAR NOT NULL, 
	composition JSONB, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE INDEX ix_material_grade_id ON material_grade (id);

CREATE TABLE die_type (
	id SERIAL NOT NULL, 
	code VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	description TEXT, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE INDEX ix_die_type_id ON die_type (id);

CREATE TABLE operation_type (
	id SERIAL NOT NULL, 
	code VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	description TEXT, 
	is_active BOOLEAN NOT NULL, 
	is_cutting BOOLEAN NOT NULL DEFAULT false,
	execution_mode execution_mode NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE INDEX ix_operation_type_id ON operation_type (id);

CREATE TABLE work_center (
	id SERIAL NOT NULL, 
	name VARCHAR NOT NULL, 
	status workcenterstatus NOT NULL, 
	location VARCHAR, 
	capacity_per_hour INTEGER, 
	setup_time_minutes INTEGER, 
	cost_per_hour NUMERIC(12, 2), 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_work_center_id ON work_center (id);

CREATE TABLE component_type (
	id SERIAL NOT NULL, 
	code VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	description TEXT, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE INDEX ix_component_type_id ON component_type (id);

CREATE TABLE supplier (
	id SERIAL NOT NULL, 
	name VARCHAR NOT NULL, 
	tax_no VARCHAR, 
	contact_name VARCHAR, 
	phone VARCHAR, 
	email VARCHAR, 
	address TEXT, 
	notes TEXT, 
	contact_info JSONB, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_supplier_name ON supplier (name);

CREATE INDEX ix_supplier_id ON supplier (id);

CREATE TABLE process_batch (
	id SERIAL NOT NULL, 
	batch_number VARCHAR NOT NULL, 
	operation_type VARCHAR NOT NULL, 
	status batch_status NOT NULL, 
	process_parameters JSONB, 
	result_attributes JSONB, 
	start_time TIMESTAMP WITH TIME ZONE, 
	end_time TIMESTAMP WITH TIME ZONE, 
	notes TEXT, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_process_batch_batch_number ON process_batch (batch_number);

CREATE INDEX ix_process_batch_id ON process_batch (id);

CREATE TABLE operator (
	id SERIAL NOT NULL, 
	rfid_code VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	employee_number VARCHAR, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	role operator_role NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (rfid_code)
);

CREATE INDEX ix_operator_id ON operator (id);

CREATE TABLE domain_action_log (
	id SERIAL NOT NULL, 
	action_type VARCHAR NOT NULL, 
	actor_type VARCHAR NOT NULL, 
	actor_id INTEGER, 
	entity_type VARCHAR NOT NULL, 
	entity_id INTEGER NOT NULL, 
	reason VARCHAR, 
	notes TEXT, 
	before_snapshot JSONB, 
	after_snapshot JSONB, 
	meta_data JSONB, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_domain_action_log_action_type ON domain_action_log (action_type);

CREATE INDEX ix_domain_action_log_id ON domain_action_log (id);

CREATE INDEX ix_domain_action_log_entity_type ON domain_action_log (entity_type);

CREATE TABLE operator_work_center (
	operator_id INTEGER NOT NULL, 
	work_center_id INTEGER NOT NULL, 
	PRIMARY KEY (operator_id, work_center_id), 
	FOREIGN KEY(operator_id) REFERENCES operator (id), 
	FOREIGN KEY(work_center_id) REFERENCES work_center (id)
);

CREATE TABLE work_center_operation_type (
	work_center_id INTEGER NOT NULL, 
	operation_type_id INTEGER NOT NULL, 
	PRIMARY KEY (work_center_id, operation_type_id), 
	FOREIGN KEY(work_center_id) REFERENCES work_center (id), 
	FOREIGN KEY(operation_type_id) REFERENCES operation_type (id)
);

CREATE TABLE location (
	id SERIAL NOT NULL, 
	name VARCHAR NOT NULL, 
	location_type location_type NOT NULL, 
	description TEXT, 
	work_center_id INTEGER, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (name), 
	FOREIGN KEY(work_center_id) REFERENCES work_center (id)
);

CREATE INDEX ix_location_id ON location (id);

CREATE TABLE die_type_component (
	id SERIAL NOT NULL, 
	die_type_id INTEGER NOT NULL, 
	component_type_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(die_type_id) REFERENCES die_type (id), 
	FOREIGN KEY(component_type_id) REFERENCES component_type (id)
);

CREATE INDEX ix_die_type_component_id ON die_type_component (id);

CREATE TABLE component_bom (
	id SERIAL NOT NULL, 
	component_type_id INTEGER NOT NULL, 
	sequence_number INTEGER NOT NULL, 
	operation_name VARCHAR NOT NULL, 
	operation_type_id INTEGER NOT NULL, 
	preferred_work_center_id INTEGER, 
	estimated_duration_minutes INTEGER, 
	notes TEXT, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(component_type_id) REFERENCES component_type (id), 
	FOREIGN KEY(operation_type_id) REFERENCES operation_type (id), 
	FOREIGN KEY(preferred_work_center_id) REFERENCES work_center (id)
);

CREATE INDEX ix_component_bom_id ON component_bom (id);

CREATE TABLE lot (
	id SERIAL NOT NULL, 
	lot_number VARCHAR NOT NULL, 
	certificate_number VARCHAR, 
	receive_date TIMESTAMP WITH TIME ZONE NOT NULL, 
	supplier_id INTEGER, 
	material_grade_id INTEGER, 
	notes TEXT, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(supplier_id) REFERENCES supplier (id), 
	FOREIGN KEY(material_grade_id) REFERENCES material_grade (id)
);

CREATE INDEX ix_lot_id ON lot (id);

CREATE UNIQUE INDEX ix_lot_lot_number ON lot (lot_number);

CREATE TABLE die (
	id SERIAL NOT NULL, 
	die_number VARCHAR NOT NULL, 
	die_diameter_mm NUMERIC(10, 2) NOT NULL, 
	total_package_length_mm NUMERIC(10, 2) NOT NULL, 
	die_type_id INTEGER NOT NULL, 
	status diestatus NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	profile_no VARCHAR NOT NULL, 
	figure_count INTEGER NOT NULL, 
	customer_name VARCHAR NOT NULL, 
	press_code VARCHAR NOT NULL, 
	is_revisioned BOOLEAN NOT NULL, 
	expected_completion_date DATE, 
	description TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (die_number), 
	FOREIGN KEY(die_type_id) REFERENCES die_type (id)
);

CREATE INDEX ix_die_id ON die (id);

CREATE TABLE stock_item (
	id SERIAL NOT NULL, 
	item_type item_type NOT NULL, 
	category_id INTEGER NOT NULL, 
	lot_id INTEGER, 
	parent_id INTEGER, 
	location_id INTEGER, 
	quantity NUMERIC(14, 4) NOT NULL, 
	attributes JSONB, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(category_id) REFERENCES item_category (id), 
	FOREIGN KEY(lot_id) REFERENCES lot (id), 
	FOREIGN KEY(parent_id) REFERENCES stock_item (id), 
	FOREIGN KEY(location_id) REFERENCES location (id)
);

CREATE INDEX ix_stock_item_type_active ON stock_item (item_type, is_active);

CREATE INDEX ix_stock_item_item_type ON stock_item (item_type);

CREATE INDEX ix_stock_item_parent_id ON stock_item (parent_id);

CREATE INDEX ix_stock_item_category_id ON stock_item (category_id);

CREATE INDEX ix_stock_item_id ON stock_item (id);

CREATE INDEX ix_stock_item_lot_id ON stock_item (lot_id);

CREATE TABLE production_order (
	id SERIAL NOT NULL, 
	die_id INTEGER NOT NULL, 
	order_number VARCHAR NOT NULL, 
	status orderstatus NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(die_id) REFERENCES die (id), 
	UNIQUE (order_number)
);

CREATE INDEX ix_production_order_id ON production_order (id);

CREATE TABLE batch_stock_item_link (
	process_batch_id INTEGER NOT NULL, 
	stock_item_id INTEGER NOT NULL, 
	PRIMARY KEY (process_batch_id, stock_item_id), 
	FOREIGN KEY(process_batch_id) REFERENCES process_batch (id), 
	FOREIGN KEY(stock_item_id) REFERENCES stock_item (id)
);

CREATE TABLE die_component (
	id SERIAL NOT NULL, 
	die_id INTEGER NOT NULL, 
	component_type_id INTEGER NOT NULL, 
	stock_item_id INTEGER, 
	package_length_mm NUMERIC(10, 2) NOT NULL, 
	theoretical_consumption_kg NUMERIC(12, 3) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(die_id) REFERENCES die (id), 
	FOREIGN KEY(component_type_id) REFERENCES component_type (id), 
	FOREIGN KEY(stock_item_id) REFERENCES stock_item (id)
);

CREATE INDEX ix_die_component_id ON die_component (id);

CREATE TABLE work_order (
	id SERIAL NOT NULL, 
	production_order_id INTEGER, 
	die_component_id INTEGER, 
	stock_item_id INTEGER,
	order_number VARCHAR, 
	pre_machining_order_number VARCHAR,
	status orderstatus NOT NULL, 
	theoretical_consumption_kg NUMERIC(12, 3) NOT NULL, 
	actual_consumption_kg NUMERIC(12, 3), 
	planned_cut_length_mm NUMERIC(10, 2),
	planned_cut_weight_kg NUMERIC(12, 3),
	actual_cut_length_mm NUMERIC(10, 2),
	actual_cut_weight_kg NUMERIC(12, 3),
	lot_id INTEGER, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(production_order_id) REFERENCES production_order (id), 
	FOREIGN KEY(die_component_id) REFERENCES die_component (id), 
	FOREIGN KEY(stock_item_id) REFERENCES stock_item (id),
	UNIQUE (order_number), 
	UNIQUE (pre_machining_order_number),
	FOREIGN KEY(lot_id) REFERENCES lot (id)
);

CREATE INDEX ix_work_order_id ON work_order (id);

CREATE TABLE work_order_operation (
	id SERIAL NOT NULL, 
	work_order_id INTEGER NOT NULL, 
	sequence_number INTEGER NOT NULL, 
	operation_type_id INTEGER NOT NULL, 
	work_center_id INTEGER, 
	operation_name VARCHAR NOT NULL, 
	operator_name VARCHAR, 
	status operation_status NOT NULL, 
	estimated_duration_minutes INTEGER, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	notes TEXT, 
	created_at TIMESTAMP WITH TIME ZONE, 
	meta_data JSONB, 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_order_id) REFERENCES work_order (id), 
	FOREIGN KEY(operation_type_id) REFERENCES operation_type (id), 
	FOREIGN KEY(work_center_id) REFERENCES work_center (id)
);

CREATE INDEX ix_work_order_operation_id ON work_order_operation (id);

CREATE TABLE stock_transaction (
	id SERIAL NOT NULL, 
	stock_item_id INTEGER NOT NULL, 
	transaction_type transaction_type NOT NULL, 
	quantity_change NUMERIC(14, 4) NOT NULL, 
	quantity_after NUMERIC(14, 4) NOT NULL, 
	work_order_id INTEGER, 
	process_batch_id INTEGER, 
	reference_item_id INTEGER, 
	notes TEXT, 
	meta_data JSONB, 
	timestamp TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(stock_item_id) REFERENCES stock_item (id), 
	FOREIGN KEY(work_order_id) REFERENCES work_order (id), 
	FOREIGN KEY(process_batch_id) REFERENCES process_batch (id), 
	FOREIGN KEY(reference_item_id) REFERENCES stock_item (id)
);

CREATE INDEX ix_stock_transaction_stock_item_id ON stock_transaction (stock_item_id);

CREATE INDEX ix_stock_transaction_transaction_type ON stock_transaction (transaction_type);

CREATE INDEX ix_stock_transaction_id ON stock_transaction (id);
