from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func
from .core import *

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    yield
app=FastAPI(title='MES Sandbox — Operation Card Master Data',version='1.0.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

def save(db,obj):
    try:
        db.add(obj);db.commit();db.refresh(obj);return obj
    except IntegrityError as e:
        db.rollback();raise HTTPException(409,'Unique constraint or foreign key conflict') from e
    except ValueError as e:
        db.rollback();raise HTTPException(409,str(e)) from e

def erase(db,obj):
    try:db.delete(obj);db.commit()
    except (IntegrityError,ValueError) as e:
        db.rollback();raise HTTPException(409,'Referenced or approved master data cannot be deleted') from e
    return {'deleted':True}
class ProductIn(BaseModel):
    name:str;family:str='Reticle';description:str=''
class RevisionIn(BaseModel):
    product_id:int;version:str;status:str='Draft'
class FlowIn(BaseModel):
    revision_id:int;name:str
class GroupIn(BaseModel):
    flow_id:int;name:str;sequence:int
class StepIn(BaseModel):
    group_id:int;name:str;sequence:int;card_version_id:int|None=None
class StepPatch(BaseModel):
    name:str|None=None;sequence:int|None=None;card_version_id:int|None=None
class CardIn(BaseModel):
    code:str;name:str;description:str=''
class CardUpdate(BaseModel):
    name:str|None=None;description:str|None=None

class VersionIn(BaseModel):
    version: str
    description: str = ''
    material_type: str = ''
    substrate_type: str = ''
    film_requirement: str = ''

    responsible_person: str = ''
    equipment_id: int | None = None
    tooling_requirement: str = ''

    drawing_number: str = ''
    drawing_version: str = ''
    drawing_url: str = ''

    sop_number: str = ''
    sop_version: str = ''
    sop_url: str = ''


class VersionEdit(BaseModel):
    description: str | None = None
    material_type: str | None = None
    substrate_type: str | None = None
    film_requirement: str | None = None

    responsible_person: str | None = None
    equipment_id: int | None = None
    tooling_requirement: str | None = None

    drawing_number: str | None = None
    drawing_version: str | None = None
    drawing_url: str | None = None

    sop_number: str | None = None
    sop_version: str | None = None
    sop_url: str | None = None

class VersionClone(BaseModel):
    version:str
class StatusIn(BaseModel):
    status:str
class EquipmentIn(BaseModel):
    name:str=Field(min_length=1,pattern=r'\S');model:str='';kind:str='';chambers:list[str]=Field(default_factory=list)
class RecipeIn(BaseModel):
    card_version_id:int|None=None;name:str;version:str='1.0';equipment_id:int|None=None;chamber:str='';parameters:dict=Field(default_factory=dict)
class InspectionIn(BaseModel):
    card_version_id:int|None=None;name:str;version:str='1.0';inspection_type:str='';equipment_id:int|None=None;sampling_rule:str='';target:float|None=None;usl:float|None=None;lsl:float|None=None;unit:str='nm';frequency:str='Every Lot'

@app.get('/api/health')
def health():return {'status':'ok','service':'MES Sandbox'}
@app.get('/api/products')
def products(db:Session=Depends(get_db)):
    return [{**dump(p),'revisions':[{**dump(r),'flows':[dump(f) for f in r.flows]} for r in p.revisions]} for p in db.query(Product).order_by(Product.id).all()]
@app.post('/api/products',status_code=201)
def product_create(data:ProductIn,db:Session=Depends(get_db)):return dump(save(db,Product(**data.model_dump())))
@app.get('/api/products/{id}')
def product_get(id:int,db:Session=Depends(get_db)):return dump(require(db,Product,id))
@app.put('/api/card-versions/{id}')
def version_put(id: int, data: VersionEdit, db: Session = Depends(get_db)):
    v = require(db, OperationCardVersion, id)
    ensure_draft(v)

    changes = data.model_dump(exclude_unset=True)

    if changes.get('equipment_id') is not None:
        require(db, Equipment, changes['equipment_id'])

    for k, val in changes.items():
        setattr(v, k, val)

    return version_view(save(db, v))
@app.delete('/api/products/{id}')
def product_delete(id:int,db:Session=Depends(get_db)):return erase(db,require(db,Product,id))

@app.get('/api/revisions')
def revisions(db:Session=Depends(get_db)):return [dump(x) for x in db.query(ProductRevision).all()]
@app.post('/api/revisions',status_code=201)
def revision_create(data:RevisionIn,db:Session=Depends(get_db)):
    require(db,Product,data.product_id);return dump(save(db,ProductRevision(**data.model_dump())))
@app.get('/api/revisions/{id}')
def revision_get(id:int,db:Session=Depends(get_db)):return dump(require(db,ProductRevision,id))
@app.put('/api/revisions/{id}')
def revision_put(id:int,data:RevisionIn,db:Session=Depends(get_db)):
    r=require(db,ProductRevision,id)
    if r.status!='Draft':raise HTTPException(409,'Released revisions are frozen')
    require(db,Product,data.product_id)
    for k,v in data.model_dump().items():setattr(r,k,v)
    return dump(save(db,r))
@app.post('/api/revisions/{id}/release')
def revision_release(id:int,db:Session=Depends(get_db)):
    r=require(db,ProductRevision,id)
    if r.status!='Draft':raise HTTPException(409,'Only Draft may be released')
    r.status='Released';return dump(save(db,r))
@app.delete('/api/revisions/{id}')
def revision_delete(id:int,db:Session=Depends(get_db)):return erase(db,require(db,ProductRevision,id))

@app.get('/api/flows')
def flows(db:Session=Depends(get_db)):return [flow_view(x) for x in db.query(ProcessFlow).all()]
@app.post('/api/flows',status_code=201)
def flow_create(data:FlowIn,db:Session=Depends(get_db)):
    rev=require(db,ProductRevision,data.revision_id)
    if rev.status!='Draft':raise HTTPException(409,'Revision frozen')
    return dump(save(db,ProcessFlow(**data.model_dump())))
@app.get('/api/flows/{id}')
def flow_get(id:int,db:Session=Depends(get_db)):return flow_view(require(db,ProcessFlow,id))
@app.put('/api/flows/{id}')
def flow_put(id:int,data:FlowIn,db:Session=Depends(get_db)):
    f=require(db,ProcessFlow,id);editable(f.revision);rev=require(db,ProductRevision,data.revision_id);editable(rev)
    for k,v in data.model_dump().items():setattr(f,k,v)
    return dump(save(db,f))
@app.delete('/api/flows/{id}')
def flow_delete(id:int,db:Session=Depends(get_db)):
    f=require(db,ProcessFlow,id);editable(f.revision);return erase(db,f)

def editable(rev):
    if rev.status!='Draft':raise HTTPException(409,'Released product revision is frozen; create a new revision')

@app.get('/api/groups')
def groups(db:Session=Depends(get_db)):return [dump(x) for x in db.query(OperationGroup).all()]
@app.post('/api/groups',status_code=201)
def group_create(data:GroupIn,db:Session=Depends(get_db)):
    f=require(db,ProcessFlow,data.flow_id);editable(f.revision)
    return dump(save(db,OperationGroup(**data.model_dump())))
@app.get('/api/groups/{id}')
def group_get(id:int,db:Session=Depends(get_db)):return dump(require(db,OperationGroup,id))
@app.put('/api/groups/{id}')
def group_put(id:int,data:GroupIn,db:Session=Depends(get_db)):
    g=require(db,OperationGroup,id);editable(g.flow.revision);f=require(db,ProcessFlow,data.flow_id);editable(f.revision)
    for k,v in data.model_dump().items():setattr(g,k,v)
    return dump(save(db,g))
@app.delete('/api/groups/{id}')
def group_delete(id:int,db:Session=Depends(get_db)):
    g=require(db,OperationGroup,id);editable(g.flow.revision);return erase(db,g)

@app.get('/api/steps')
def steps(db:Session=Depends(get_db)):return [dump(x) for x in db.query(OperationStep).all()]
@app.post('/api/steps',status_code=201)
def step_create(data:StepIn,db:Session=Depends(get_db)):
    g=require(db,OperationGroup,data.group_id);editable(g.flow.revision)
    if data.card_version_id is not None:ensure_released(db,data.card_version_id)
    return dump(save(db,OperationStep(**data.model_dump())))
@app.get('/api/steps/{id}')
def step_get(id:int,db:Session=Depends(get_db)):return dump(require(db,OperationStep,id))
@app.put('/api/steps/{id}')
def step_put(id:int,data:StepPatch,db:Session=Depends(get_db)):
    s=require(db,OperationStep,id);editable(s.group.flow.revision)
    changes=data.model_dump(exclude_unset=True)
    if 'card_version_id' in changes and changes['card_version_id'] is not None:ensure_released(db,changes['card_version_id'])
    for k,v in changes.items():setattr(s,k,v)
    return dump(save(db,s))
@app.delete('/api/steps/{id}')
def step_delete(id:int,db:Session=Depends(get_db)):
    s=require(db,OperationStep,id);editable(s.group.flow.revision);return erase(db,s)

@app.get('/api/operation-cards')
def cards(db:Session=Depends(get_db)):return [card_view(x) for x in db.query(OperationCard).all()]
@app.post('/api/operation-cards',status_code=201)
def card_create(data:CardIn,db:Session=Depends(get_db)):return card_view(save(db,OperationCard(**data.model_dump())))
@app.get('/api/operation-cards/{id}')
def card_get(id:int,db:Session=Depends(get_db)):return card_view(require(db,OperationCard,id))
@app.put('/api/operation-cards/{id}')
def card_put(id:int,data:CardUpdate,db:Session=Depends(get_db)):
    c=require(db,OperationCard,id)
    for k,v in data.model_dump(exclude_unset=True).items():setattr(c,k,v)
    return card_view(save(db,c))
@app.delete('/api/operation-cards/{id}')
def card_delete(id:int,db:Session=Depends(get_db)):
    c=require(db,OperationCard,id)
    if c.versions:raise HTTPException(409,'Delete versions first; cards referenced by steps must be retained')
    return erase(db,c)
@app.get('/api/operation-cards/{id}/versions')
def card_versions(id:int,db:Session=Depends(get_db)):return [version_view(v) for v in require(db,OperationCard,id).versions]
@app.post('/api/operation-cards/{id}/versions',status_code=201)
def version_create(id:int,data:VersionIn,db:Session=Depends(get_db)):
    require(db,OperationCard,id);return version_view(save(db,OperationCardVersion(card_id=id,**data.model_dump(),status='Draft')))
@app.get('/api/card-versions')
def versions(db:Session=Depends(get_db)):return [version_view(x) for x in db.query(OperationCardVersion).all()]
@app.get('/api/card-versions/{id}')
def version_get(id:int,db:Session=Depends(get_db)):return version_view(require(db,OperationCardVersion,id))
@app.put('/api/card-versions/{id}')
def version_put(id:int,data:VersionEdit,db:Session=Depends(get_db)):
    v=require(db,OperationCardVersion,id);ensure_draft(v)
    for k,val in data.model_dump(exclude_unset=True).items():setattr(v,k,val)
    return version_view(save(db,v))
@app.post('/api/card-versions/{id}/release')
def version_release(id:int,db:Session=Depends(get_db)):
    v=require(db,OperationCardVersion,id);ensure_draft(v)
    # reject empty released records without linked content only if no material info? allowed for Cleaning
    v.status='Released';return version_view(save(db,v))
@app.post('/api/card-versions/{id}/obsolete')
def version_obsolete(id:int,db:Session=Depends(get_db)):
    v=require(db,OperationCardVersion,id)
    if v.status!='Released':raise HTTPException(409,'Only Released may become Obsolete')
    v.status='Obsolete';return version_view(save(db,v))
@app.post('/api/card-versions/{id}/clone',status_code=201)
def version_clone(id:int,data:VersionClone,db:Session=Depends(get_db)):
    old=require(db,OperationCardVersion,id)

    new = OperationCardVersion(
        card_id=old.card_id,
        version=data.version,
        status='Draft',
        description=old.description,

        material_type=old.material_type,
        substrate_type=old.substrate_type,
        film_requirement=old.film_requirement,

        responsible_person=old.responsible_person,
        equipment_id=old.equipment_id,
        tooling_requirement=old.tooling_requirement,

        drawing_number=old.drawing_number,
        drawing_version=old.drawing_version,
        drawing_url=old.drawing_url,

        sop_number=old.sop_number,
        sop_version=old.sop_version,
        sop_url=old.sop_url,
    )
    for r in old.recipes:new.recipes.append(Recipe(name=r.name,version=r.version,equipment_id=r.equipment_id,chamber=r.chamber,parameters=dict(r.parameters or {})))
    for p in old.inspections:new.inspections.append(InspectionPlan(name=p.name,version=p.version,inspection_type=p.inspection_type,equipment_id=p.equipment_id,sampling_rule=p.sampling_rule,target=p.target,usl=p.usl,lsl=p.lsl,unit=p.unit,frequency=p.frequency))
    return version_view(save(db,new))
@app.delete('/api/card-versions/{id}')
def version_delete(id:int,db:Session=Depends(get_db)):
    v=require(db,OperationCardVersion,id);ensure_draft(v)
    if db.query(OperationStep).filter_by(card_version_id=id).first():raise HTTPException(409,'Version referenced by a step')
    return erase(db,v)

# Generic CRUD for supporting master data; linked records in a released card stay immutable.
def child_editable(db,obj):
    if obj.card_version_id:ensure_draft(require(db,OperationCardVersion,obj.card_version_id))

def validate_child(db,data):
    if data.card_version_id:ensure_draft(require(db,OperationCardVersion,data.card_version_id))
    if data.equipment_id is not None:require(db,Equipment,data.equipment_id)

@app.get('/api/equipment')
def equipment_list(db:Session=Depends(get_db)):return [dump(x) for x in db.query(Equipment).all()]
@app.post('/api/equipment',status_code=201)
def equipment_create(data:EquipmentIn,db:Session=Depends(get_db)):return dump(save(db,Equipment(**data.model_dump())))
@app.get('/api/equipment/{id}')
def equipment_get(id:int,db:Session=Depends(get_db)):return dump(require(db,Equipment,id))
@app.put('/api/equipment/{id}')
def equipment_put(id:int,data:EquipmentIn,db:Session=Depends(get_db)):
    e=require(db,Equipment,id)
    for k,v in data.model_dump().items():setattr(e,k,v)
    return dump(save(db,e))
@app.delete('/api/equipment/{id}')
def equipment_delete(id:int,db:Session=Depends(get_db)):
    equipment=require(db,Equipment,id)
    for model,label in [(OperationCardVersion,'工序卡版本'),(Recipe,'Recipe'),(InspectionPlan,'Inspection Plan')]:
        if db.query(model).filter_by(equipment_id=id).first():
            raise HTTPException(409,f'设备已被{label}引用，无法删除；请先解除引用')
    return erase(db,equipment)

for singular,model,Schema in [('recipes',Recipe,RecipeIn),('inspection-plans',InspectionPlan,InspectionIn)]:
    def make_list(M):
        def f(db:Session=Depends(get_db)):return [dump(x) for x in db.query(M).all()]
        return f
    def make_create(M,S):
        def f(data:S,db:Session=Depends(get_db)):
            validate_child(db,data)
            return dump(save(db,M(**data.model_dump())))
        return f
    def make_get(M):
        def f(id:int,db:Session=Depends(get_db)):return dump(require(db,M,id))
        return f
    def make_put(M,S):
        def f(id:int,data:S,db:Session=Depends(get_db)):
            obj=require(db,M,id);child_editable(db,obj);validate_child(db,data)
            for k,v in data.model_dump().items():setattr(obj,k,v)
            return dump(save(db,obj))
        return f
    def make_delete(M):
        def f(id:int,db:Session=Depends(get_db)):
            obj=require(db,M,id);child_editable(db,obj);return erase(db,obj)
        return f
    app.add_api_route('/api/'+singular,make_list(model),methods=['GET'],tags=[singular])
    app.add_api_route('/api/'+singular,make_create(model,Schema),methods=['POST'],status_code=201,tags=[singular])
    app.add_api_route('/api/'+singular+'/{id}',make_get(model),methods=['GET'],tags=[singular])
    app.add_api_route('/api/'+singular+'/{id}',make_put(model,Schema),methods=['PUT'],tags=[singular])
    app.add_api_route('/api/'+singular+'/{id}',make_delete(model),methods=['DELETE'],tags=[singular])

@app.post('/api/revisions/{id}/clone',status_code=201)
def clone_revision(id:int,data:VersionClone,db:Session=Depends(get_db)):
    old=require(db,ProductRevision,id)
    rev=ProductRevision(product_id=old.product_id,version=data.version,status='Draft')
    for flow in old.flows:
        nf=ProcessFlow(name=flow.name);rev.flows.append(nf)
        for g in flow.groups:
            ng=OperationGroup(name=g.name,sequence=g.sequence);nf.groups.append(ng)
            for s in g.steps:ng.steps.append(OperationStep(name=s.name,sequence=s.sequence,card_version_id=s.card_version_id))
    save(db,rev)
    return dump(rev)
