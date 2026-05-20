import sqlite3
from datetime import datetime, timedelta

def setup_database():
    """Sets up an in-memory SQLite database for WooCommerce order simulation."""
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()

    # Create wp_posts table for orders
    cursor.execute('''
        CREATE TABLE wp_posts (
            ID INTEGER PRIMARY KEY,
            post_type TEXT,
            post_status TEXT,
            post_date TEXT
        )
    ''')

    # Create wp_postmeta table for order metadata
    cursor.execute('''
        CREATE TABLE wp_postmeta (
            meta_id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER,
            meta_key TEXT,
            meta_value TEXT,
            FOREIGN KEY (post_id) REFERENCES wp_posts(ID)
        )
    ''')
    conn.commit()
    return conn

def insert_sample_data(conn):
    """Inserts sample WooCommerce order data into the database."""
    cursor = conn.cursor()

    # Helper to insert an order and its meta
    def add_order(order_id, status, date_offset_days, payment_method=None, order_total='0.00'):
        order_date = (datetime.now() - timedelta(days=date_offset_days)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("INSERT INTO wp_posts (ID, post_type, post_status, post_date) VALUES (?, 'shop_order', ?, ?)",
                       (order_id, status, order_date))
        if payment_method:
            cursor.execute("INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES (?, '_payment_method', ?)",
                           (order_id, payment_method))
        cursor.execute("INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES (?, '_order_total', ?)",
                       (order_id, order_total))

    # Sample data:
    # 1. Completed order
    add_order(101, 'wc-completed', 5, 'stripe', '120.50')
    # 2. Processing order
    add_order(102, 'wc-processing', 2, 'paypal', '85.00')
    # 3. Pending order (recent)
    add_order(103, 'wc-pending', 0.5, 'bacs', '45.00')
    # 4. Old pending order (should be flagged)
    add_order(104, 'wc-pending', 3, 'bacs', '60.00')
    # 5. Failed order (should be flagged)
    add_order(105, 'wc-failed', 1, 'stripe', '30.00')
    # 6. Order missing payment method (should be flagged)
    add_order(106, 'wc-processing', 1, None, '75.00')
    # 7. Another completed order
    add_order(107, 'wc-completed', 10, 'stripe', '200.00')
    # 8. Processing order with zero total (potential issue)
    add_order(108, 'wc-processing', 0.5, 'paypal', '0.00')

    conn.commit()

def run_check(conn, title, query):
    """Executes a given SQL query and prints its results."""
    cursor = conn.cursor()
    print(f"\n--- {title} ---")
    cursor.execute(query)
    results = cursor.fetchall()
    if results:
        for row in results:
            print(row)
    else:
        print("No issues found.")

def main():
    conn = setup_database()
    insert_sample_data(conn)

    print("Simulating WooCommerce Payment Health Checks...")

    # --- Critical Control 1: Identify Old Pending Orders ---
    # This query finds orders that are still 'pending payment' after a certain time (e.g., 24 hours).
    # Such orders might indicate a payment gateway issue, a customer abandonment, or a manual review need.
    run_check(conn, "1. Old 'Pending payment' Orders (older than 1 day)", """
        SELECT p.ID, p.post_date, pm_total.meta_value AS order_total
        FROM wp_posts p
        JOIN wp_postmeta pm_total ON p.ID = pm_total.post_id AND pm_total.meta_key = '_order_total'
        WHERE p.post_type = 'shop_order'
          AND p.post_status = 'wc-pending'
          AND p.post_date < datetime('now', '-1 day');
    """)

    # --- Critical Control 2: Identify Failed Orders ---
    # This query lists all orders that have a 'failed' status. These usually require manual investigation
    # to understand why the payment failed and if the customer needs to be contacted.
    run_check(conn, "2. 'Failed' Orders", """
        SELECT p.ID, p.post_date, pm_total.meta_value AS order_total
        FROM wp_posts p
        JOIN wp_postmeta pm_total ON p.ID = pm_total.post_id AND pm_total.meta_key = '_order_total'
        WHERE p.post_type = 'shop_order'
          AND p.post_status = 'wc-failed';
    """)

    # --- Critical Control 3: Identify Orders Missing Payment Method ---
    # Orders should always have a payment method recorded. If this meta key is missing,
    # it could indicate a problem during the checkout process or a data integrity issue.
    run_check(conn, "3. Orders Missing Payment Method Information", """
        SELECT p.ID, p.post_date
        FROM wp_posts p
        LEFT JOIN wp_postmeta pm ON p.ID = pm.post_id AND pm.meta_key = '_payment_method'
        WHERE p.post_type = 'shop_order'
          AND pm.meta_value IS NULL;
    """)

    # --- Critical Control 4: Identify Processing Orders with Zero Total ---
    # An order in 'processing' status typically means payment has been received. If its total is 0,
    # it might be a free order, but for paid products, it could signal a payment processing error
    # or a misconfiguration. This check helps identify such anomalies.
    run_check(conn, "4. 'Processing' Orders with Zero Total", """
        SELECT p.ID, p.post_date, pm_total.meta_value AS order_total
        FROM wp_posts p
        JOIN wp_postmeta pm_total ON p.ID = pm_total.post_id
        WHERE p.post_type = 'shop_order'
          AND p.post_status = 'wc-processing'
          AND pm_total.meta_key = '_order_total'
          AND CAST(pm_total.meta_value AS REAL) = 0;
    """)

    conn.close()

if __name__ == "__main__":
    main()
