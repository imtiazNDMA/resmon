import sqlalchemy
engine = sqlalchemy.create_engine('postgresql+psycopg://nirrp:nirrp_dev_2026@localhost:7544/nirrp')
with engine.connect() as conn:
    conn.execute(sqlalchemy.text('DROP TABLE IF EXISTS alembic_version;'))
    conn.commit()
print('Dropped version table')
