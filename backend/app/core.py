import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import HTTPException
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Float, JSON, UniqueConstraint, event
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from sqlalchemy.pool import StaticPool

BASE_DIR=Path(__file__).resolve().parents[2]
DATABASE_URL=os.getenv('DATABASE_URL',f'sqlite:///{BASE_DIR / "mes.db"}')
opts={'connect_args':{'check_same_thread':False}} if DATABASE_URL.startswith('sqlite') else {}
if DATABASE_URL == 'sqlite://': opts['poolclass']=StaticPool
engine=create_engine(DATABASE_URL,**opts)
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine,"connect")
    def sqlite_fk_on(dbapi_connection,connection_record):
        cur=dbapi_connection.cursor();cur.execute("PRAGMA foreign_keys=ON");cur.close()
SessionLocal=sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
Base=declarative_base()
def now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def get_db():
    with SessionLocal() as db: yield db

class Product(Base):
    __tablename__='products'
    id=Column(Integer,primary_key=True); name=Column(String(120),nullable=False,unique=True); family=Column(String(120),default='Reticle'); description=Column(Text,default='')
    revisions=relationship('ProductRevision',back_populates='product',cascade='all, delete-orphan')
class ProductRevision(Base):
    __tablename__='product_revisions'; __table_args__=(UniqueConstraint('product_id','version'),)
    id=Column(Integer,primary_key=True); product_id=Column(Integer,ForeignKey('products.id',ondelete='CASCADE'),nullable=False); version=Column(String(40),nullable=False); effective_date=Column(DateTime,default=now); status=Column(String(20),default='Draft')
    product=relationship('Product',back_populates='revisions'); flows=relationship('ProcessFlow',back_populates='revision',cascade='all, delete-orphan')
class ProcessFlow(Base):
    __tablename__='process_flows'; __table_args__=(UniqueConstraint('revision_id','name'),)
    id=Column(Integer,primary_key=True); revision_id=Column(Integer,ForeignKey('product_revisions.id',ondelete='CASCADE'),nullable=False); name=Column(String(150),nullable=False)
    revision=relationship('ProductRevision',back_populates='flows'); groups=relationship('OperationGroup',back_populates='flow',cascade='all, delete-orphan',order_by='OperationGroup.sequence')
class OperationGroup(Base):
    __tablename__='operation_groups'; __table_args__=(UniqueConstraint('flow_id','sequence'),)
    id=Column(Integer,primary_key=True); flow_id=Column(Integer,ForeignKey('process_flows.id',ondelete='CASCADE'),nullable=False); name=Column(String(120),nullable=False); sequence=Column(Integer,nullable=False)
    flow=relationship('ProcessFlow',back_populates='groups'); steps=relationship('OperationStep',back_populates='group',cascade='all, delete-orphan',order_by='OperationStep.sequence')
class OperationStep(Base):
    __tablename__='operation_steps'; __table_args__=(UniqueConstraint('group_id','sequence'),)
    id=Column(Integer,primary_key=True); group_id=Column(Integer,ForeignKey('operation_groups.id',ondelete='CASCADE'),nullable=False); name=Column(String(120),nullable=False); sequence=Column(Integer,nullable=False); card_version_id=Column(Integer,ForeignKey('operation_card_versions.id',ondelete='RESTRICT'),nullable=True)
    group=relationship('OperationGroup',back_populates='steps'); card_version=relationship('OperationCardVersion')
class OperationCard(Base):
    __tablename__='operation_cards'
    id=Column(Integer,primary_key=True); code=Column(String(100),nullable=False,unique=True); name=Column(String(120),nullable=False); description=Column(Text,default=''); created_at=Column(DateTime,default=now)
    versions=relationship('OperationCardVersion',back_populates='card',order_by='OperationCardVersion.id')
class OperationCardVersion(Base):
    __tablename__ = 'operation_card_versions'
    __table_args__ = (UniqueConstraint('card_id', 'version'),)

    id = Column(Integer, primary_key=True)
    card_id = Column(
        Integer,
        ForeignKey('operation_cards.id', ondelete='RESTRICT'),
        nullable=False
    )
    version = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False, default='Draft')
    description = Column(Text, default='')

    # 原有物料要求
    material_type = Column(String(100), default='')
    substrate_type = Column(String(100), default='')
    film_requirement = Column(String(255), default='')

    # 新增：工序责任人
    responsible_person = Column(String(120), default='')

    # 新增：设备要求，可关联现有 Equipment 主数据
    equipment_id = Column(
        Integer,
        ForeignKey('equipment.id', ondelete='SET NULL'),
        nullable=True
    )

    # 新增：工装要求
    tooling_requirement = Column(Text, default='')

    # 新增：图纸信息
    drawing_number = Column(String(120), default='')
    drawing_version = Column(String(40), default='')
    drawing_url = Column(Text, default='')

    # 新增：SOP 信息
    sop_number = Column(String(120), default='')
    sop_version = Column(String(40), default='')
    sop_url = Column(Text, default='')

    created_at = Column(DateTime, default=now)

    card = relationship('OperationCard', back_populates='versions')
    equipment = relationship('Equipment')

    recipes = relationship(
        'Recipe',
        back_populates='card_version',
        cascade='all, delete-orphan'
    )
    inspections = relationship(
        'InspectionPlan',
        back_populates='card_version',
        cascade='all, delete-orphan'
    )

class Equipment(Base):
    __tablename__='equipment'
    id=Column(Integer,primary_key=True); name=Column(String(120),unique=True,nullable=False); model=Column(String(120),default=''); kind=Column(String(100),default=''); chambers=Column(JSON,default=list)
class Recipe(Base):
    __tablename__='recipes'
    id=Column(Integer,primary_key=True); card_version_id=Column(Integer,ForeignKey('operation_card_versions.id',ondelete='RESTRICT'),nullable=True); name=Column(String(120),nullable=False); version=Column(String(40),default='1.0'); equipment_id=Column(Integer,ForeignKey('equipment.id',ondelete='SET NULL')); chamber=Column(String(80),default=''); parameters=Column(JSON,default=dict)
    equipment=relationship('Equipment'); card_version=relationship('OperationCardVersion',back_populates='recipes')
class InspectionPlan(Base):
    __tablename__='inspection_plans'
    id=Column(Integer,primary_key=True); card_version_id=Column(Integer,ForeignKey('operation_card_versions.id',ondelete='RESTRICT'),nullable=True); name=Column(String(120),nullable=False); version=Column(String(40),default='1.0'); inspection_type=Column(String(100),default=''); equipment_id=Column(Integer,ForeignKey('equipment.id',ondelete='SET NULL')); sampling_rule=Column(String(120),default=''); target=Column(Float,nullable=True); usl=Column(Float,nullable=True); lsl=Column(Float,nullable=True); unit=Column(String(40),default='nm'); frequency=Column(String(80),default='Every Lot')
    equipment=relationship('Equipment'); card_version=relationship('OperationCardVersion',back_populates='inspections')

# Prevent mutations of approved snapshots even through ORM updates to child rows.
@event.listens_for(Session,'before_flush')
def prevent_immutable_changes(session,flush_context,instances):
    for obj in session.dirty:
        if isinstance(obj,OperationCardVersion) and obj.status!='Draft':
            from sqlalchemy import inspect
            state=inspect(obj)
            if any(
                    state.attrs[key].history.has_changes()
                    for key in [
                        'version',
                        'description',
                        'material_type',
                        'substrate_type',
                        'film_requirement',
                        'responsible_person',
                        'equipment_id',
                        'tooling_requirement',
                        'drawing_number',
                        'drawing_version',
                        'drawing_url',
                        'sop_number',
                        'sop_version',
                        'sop_url',
                        'card_id',
                    ]
            ):
                raise ValueError('Released/Obsolete version payload is immutable')
        if isinstance(obj,(Recipe,InspectionPlan)) and obj.card_version_id:
            parent=session.get(OperationCardVersion,obj.card_version_id)
            if parent and parent.status!='Draft': raise ValueError('Approved card recipe/inspection is immutable')
    for obj in session.deleted:
        if isinstance(obj,OperationCardVersion) and obj.status!='Draft':raise ValueError('Approved card version cannot be deleted')
        if isinstance(obj,(Recipe,InspectionPlan)) and obj.card_version_id:
            parent=session.get(OperationCardVersion,obj.card_version_id)
            if parent and parent.status!='Draft':raise ValueError('Approved card recipe/inspection cannot be deleted')

def require(db,model,id):
    obj=db.get(model,id)
    if not obj: raise HTTPException(404,f'{model.__name__} {id} not found')
    return obj

def ensure_draft(v):
    if v.status!='Draft':raise HTTPException(409,'Only Draft versions are editable; clone a new version')

def ensure_released(db,vid):
    v=require(db,OperationCardVersion,vid)
    if v.status!='Released':raise HTTPException(409,'Steps may reference Released card versions only')
    return v

def dump(obj):
    return {col.name:getattr(obj,col.name) for col in obj.__table__.columns}

def card_view(c):
    return {**dump(c),'versions':[version_view(v) for v in c.versions]}

def version_view(v):
    return {**dump(v),'recipes':[dump(x) for x in v.recipes], 'inspections':[dump(x) for x in v.inspections]}

def flow_view(f):
    return {**dump(f),'groups':[{**dump(g),'steps':[{**dump(s),'card_code':s.card_version.card.code if s.card_version else None,'card_version':s.card_version.version if s.card_version else None} for s in g.steps]} for g in f.groups]}
