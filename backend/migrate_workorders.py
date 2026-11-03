"""Additive migration: no changes to existing MES rows or table columns."""
from app.core import Base, engine
from app import workorders

def migrate(bind=engine):
    Base.metadata.create_all(bind, tables=[t for t in Base.metadata.sorted_tables if t.name.startswith('wo_')])

if __name__=='__main__':
    migrate()
    print('Request work order tables ready. Existing MES data unchanged.')
