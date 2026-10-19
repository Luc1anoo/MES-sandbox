"""Additive models; existing InspectionPlan rows and API remain compatible."""
from sqlalchemy import Boolean
from .core import (Base, Column, Integer, String, Text, DateTime, ForeignKey,
                   Float, relationship, now)


class InspectionItem(Base):
    __tablename__ = 'inspection_items'
    id = Column(Integer, primary_key=True)
    inspection_plan_id = Column(Integer, ForeignKey('inspection_plans.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    inspection_type = Column(String(100), default='')
    sampling_rule = Column(String(120), default='')
    target = Column(Float)
    usl = Column(Float)
    lsl = Column(Float)
    unit = Column(String(40), default='nm')
    frequency = Column(String(80), default='Every Lot')
    plan = relationship('InspectionPlan', back_populates='items')


class ContextColumns:
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    flow_id = Column(Integer, ForeignKey('process_flows.id', ondelete='RESTRICT'), index=True)
    step_id = Column(Integer, ForeignKey('operation_steps.id', ondelete='RESTRICT'), index=True)
    card_version_id = Column(Integer, ForeignKey('operation_card_versions.id', ondelete='RESTRICT'), index=True)
    priority = Column(Integer, nullable=False, default=0)
    is_enabled = Column(Boolean, nullable=False, default=True)
    description = Column(Text, nullable=False, default='')
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=now)
    updated_at = Column(DateTime, nullable=False, default=now, onupdate=now)


class RecipeContext(ContextColumns, Base):
    __tablename__ = 'recipe_contexts'
    equipment_id = Column(Integer, ForeignKey('equipment.id', ondelete='RESTRICT'), index=True)
    chamber = Column(String(80))
    substrate_type = Column(String(100))
    recipe_id = Column(Integer, ForeignKey('recipes.id', ondelete='RESTRICT'), nullable=False, index=True)


class InspectionPlanContext(ContextColumns, Base):
    __tablename__ = 'inspection_plan_contexts'
    inspection_type = Column(String(100))
    inspection_plan_id = Column(Integer, ForeignKey('inspection_plans.id', ondelete='RESTRICT'), nullable=False, index=True)


from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from .core import OperationCardVersion, InspectionPlan


@event.listens_for(Session, 'before_flush')
def protect_inspection_items(session, flush_context, instances):
    for item in set(session.new) | set(session.dirty) | set(session.deleted):
        if not isinstance(item, InspectionItem):
            continue
        plan_ids = {item.inspection_plan_id}
        plan_ids.update(inspect(item).attrs.inspection_plan_id.history.deleted)
        plans = [session.get(InspectionPlan, id) for id in plan_ids if id]
        if item.plan is not None:
            plans.append(item.plan)
        for plan in plans:
            if plan and plan.card_version_id:
                version = session.get(OperationCardVersion, plan.card_version_id)
                if version and version.status != 'Draft':
                    raise ValueError('Approved inspection plan items are immutable')
