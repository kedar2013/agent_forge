"""Hand-written, concise grounding context for the `sales_analytics` MySQL
database — fed into the NL->SQL prompt in slide_reporting_server.py instead
of raw DDL, so the model sees exactly the tables/columns/relationships it
needs and nothing else. Captured directly from the live schema (DESCRIBE +
information_schema.KEY_COLUMN_USAGE), not guessed.
"""

SCHEMA_CONTEXT = """\
Database: sales_analytics (MySQL). All questions must be answered with a
single read-only SELECT statement against these tables:

regions(region_id PK, region_name, country)
  6 regions across US/India/UK/Singapore.

sales_reps(rep_id PK, rep_name, region_id FK->regions, hire_date, email)
  A rep belongs to exactly one region.

categories(category_id PK, category_name, parent_category_id FK->categories, nullable)
  Two-level category tree: top-level categories have parent_category_id
  IS NULL; child categories point at their parent's category_id.

products(product_id PK, product_name, category_id FK->categories,
         unit_price DECIMAL, unit_cost DECIMAL, launch_date, is_active BOOL)
  unit_price is the list price; unit_cost is what it costs to make/source
  (unit_price - unit_cost = gross margin per unit before discount).

customers(customer_id PK, customer_name,
          segment ENUM('Enterprise','SMB','Consumer'),
          region_id FK->regions, signup_date)

orders(order_id PK, customer_id FK->customers, rep_id FK->sales_reps,
       order_date, order_status ENUM('Completed','Pending','Cancelled','Returned'))
  order_status defaults to 'Completed'. Revenue/sales questions should
  normally filter order_status = 'Completed' unless the user asks about
  pending/cancelled/returned orders specifically.

order_items(order_item_id PK, order_id FK->orders, product_id FK->products,
            quantity INT, unit_price DECIMAL, discount_pct DECIMAL(5,2))
  unit_price here is the price actually charged on that line (may differ
  from products.unit_price). discount_pct is a percentage (e.g. 10.00 = 10%),
  already reflected in unit_price is NOT assumed -- to get the actual line
  revenue, compute: quantity * unit_price * (1 - discount_pct / 100).

sales_targets(target_id PK, rep_id FK->sales_reps, target_month DATE,
              target_amount DECIMAL)
  target_month is always the first day of a month. Use this table for
  target-vs-actual comparisons (join actual revenue, grouped by month and
  rep, against target_amount for that rep+month).

Common patterns:
- "Revenue" = SUM(order_items.quantity * order_items.unit_price * (1 - order_items.discount_pct / 100))
  from order_items joined to orders (filtered to order_status='Completed'
  unless told otherwise).
- "By region" needs orders -> customers -> regions (customer's region) or
  orders -> sales_reps -> regions (rep's region) -- prefer the customer's
  region for revenue-by-region questions unless the question is clearly
  about rep/territory performance.
- Monthly trends: GROUP BY DATE_FORMAT(order_date, '%Y-%m') or
  YEAR(order_date), MONTH(order_date).
- "Top N customers/products/reps" needs ORDER BY <metric> DESC LIMIT N.
- Category tree: to roll a child category up to its parent, self-join
  categories c JOIN categories p ON c.parent_category_id = p.category_id.
"""
