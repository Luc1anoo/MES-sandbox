"""Idempotent additive migration. Run from backend; never drops or rewrites old data."""
from app.core import engine
from app.context_models import InspectionItem, RecipeContext, InspectionPlanContext


def migrate(bind=engine):
    for table in (InspectionItem.__table__, RecipeContext.__table__, InspectionPlanContext.__table__):
        table.create(bind, checkfirst=True)


if __name__ == '__main__':
    migrate()
    print('Context tables and inspection items ready; existing rows unchanged.')
