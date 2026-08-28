import os
import pytest
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_URL = os.environ.get('DATABASE_URL') or os.environ.get('SUPABASE_DB_URL')


@pytest.mark.skipif(not DB_URL, reason="DATABASE_URL not configured for live postgres execution")
def test_lockin_database_constraints():
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()
    
    # Read verify_constraints.sql script
    sql_path = os.path.join(os.path.dirname(__file__), '..', '..', 'supabase', 'verify_constraints.sql')
    with open(sql_path, 'r', encoding='utf-8') as f:
        verify_sql = f.read()

    # Execute constraint verification DO block
    cursor.execute(verify_sql)
    conn.commit()
    cursor.close()
    conn.close()
