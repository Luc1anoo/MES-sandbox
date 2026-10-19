from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .core import get_db, require, dump, now, InspectionPlan, ensure_draft
from .context_models import RecipeContext, InspectionPlanContext, InspectionItem
from .services.context_resolution import resolve, validate_rule

router = APIRouter(prefix='/api', tags=['Context Management'])


class Conditions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120, pattern=r'\S')
    flow_id: int | None = Field(default=None, gt=0)
    step_id: int | None = Field(default=None, gt=0)
    card_version_id: int | None = Field(default=None, gt=0)
    priority: int = 0
    is_enabled: bool = True
    description: str = ''

    @field_validator('name')
    @classmethod
    def trim_name(cls, value):
        return value.strip()


class RecipeRule(Conditions):
    recipe_id: int = Field(gt=0)
    equipment_id: int | None = Field(default=None, gt=0)
    chamber: str | None = Field(default=None, max_length=80)
    substrate_type: str | None = Field(default=None, max_length=100)

    @field_validator('chamber', 'substrate_type', mode='before')
    @classmethod
    def blank_is_unrestricted(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class InspectionRule(Conditions):
    inspection_plan_id: int = Field(gt=0)
    inspection_type: str | None = Field(default=None, max_length=100)

    @field_validator('inspection_type', mode='before')
    @classmethod
    def blank_is_unrestricted(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class RecipeUpdate(RecipeRule):
    revision: int = Field(gt=0)


class InspectionUpdate(InspectionRule):
    revision: int = Field(gt=0)


class Toggle(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(gt=0)
    is_enabled: bool


class ResolveInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    step_id: int = Field(gt=0)
    flow_id: int | None = Field(default=None, gt=0)
    card_version_id: int | None = Field(default=None, gt=0)


class RecipeInput(ResolveInput):
    equipment_id: int = Field(gt=0)
    chamber: str | None = None

    @field_validator('chamber', mode='before')
    @classmethod
    def empty_chamber(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class InspectionInput(ResolveInput):
    inspection_type: str = Field(min_length=1, max_length=100, pattern=r'\S')

    @field_validator('inspection_type')
    @classmethod
    def trim_condition(cls, value):
        return value.strip()


class ItemInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120, pattern=r'\S')
    inspection_type: str = ''
    sampling_rule: str = ''
    target: float | None = Field(default=None, allow_inf_nan=False)
    usl: float | None = Field(default=None, allow_inf_nan=False)
    lsl: float | None = Field(default=None, allow_inf_nan=False)
    unit: str = 'nm'
    frequency: str = 'Every Lot'

    @model_validator(mode='after')
    def limits(self):
        if self.lsl is not None and self.usl is not None and self.lsl > self.usl:
            raise ValueError('LSL must not exceed USL')
        if self.target is not None and ((self.lsl is not None and self.target < self.lsl) or (self.usl is not None and self.target > self.usl)):
            raise ValueError('Target must be within LSL and USL')
        return self


def commit(db):
    try:
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, '对象仍被引用或关联数据已变化，请刷新后重试') from exc


def register_context_routes(path, model, create_schema, update_schema, input_schema, recipe):
    def listing(flow_id: int | None = None, step_id: int | None = None,
                equipment_id: int | None = None, recipe_id: int | None = None,
                inspection_plan_id: int | None = None, is_enabled: bool | None = None,
                db: Session = Depends(get_db)):
        query = db.query(model)
        for key, value in locals().copy().items():
            if key in ('flow_id', 'step_id', 'equipment_id', 'recipe_id', 'inspection_plan_id', 'is_enabled') and value is not None and hasattr(model, key):
                query = query.filter(getattr(model, key) == value)
        return [dump(row) for row in query.order_by(model.id)]

    def create(data: create_schema, db: Session = Depends(get_db)):
        values = data.model_dump()
        validate_rule(db, values, recipe)
        obj = model(**values)
        db.add(obj)
        commit(db)
        db.refresh(obj)
        return dump(obj)

    def get(id: int, db: Session = Depends(get_db)):
        return dump(require(db, model, id))

    def modify(id: int, data: update_schema, db: Session = Depends(get_db)):
        require(db, model, id)
        values = data.model_dump()
        revision = values.pop('revision')
        validate_rule(db, values, recipe)
        count = db.execute(update(model).where(model.id == id, model.revision == revision)
                           .values(**values, revision=revision + 1, updated_at=now())).rowcount
        if not count:
            db.rollback()
            raise HTTPException(409, '规则已被其他操作修改，请刷新后重试')
        commit(db)
        db.expire_all()
        return dump(require(db, model, id))

    def toggle(id: int, data: Toggle, db: Session = Depends(get_db)):
        require(db, model, id)
        count = db.execute(update(model).where(model.id == id, model.revision == data.revision)
                           .values(is_enabled=data.is_enabled, revision=data.revision + 1, updated_at=now())).rowcount
        if not count:
            db.rollback()
            raise HTTPException(409, '规则已被其他操作修改，请刷新后重试')
        commit(db)
        db.expire_all()
        return dump(require(db, model, id))

    def remove(id: int, revision: int = Query(gt=0), db: Session = Depends(get_db)):
        require(db, model, id)
        count = db.execute(delete(model).where(model.id == id, model.revision == revision)).rowcount
        if not count:
            db.rollback()
            raise HTTPException(409, '规则已被其他操作修改，请刷新后重试')
        commit(db)
        return {'deleted': True}

    def resolution(data: input_schema, db: Session = Depends(get_db)):
        return resolve(db, data, recipe)

    router.add_api_route(path + '/resolve', resolution, methods=['POST'])
    router.add_api_route(path, listing, methods=['GET'])
    router.add_api_route(path, create, methods=['POST'], status_code=201)
    router.add_api_route(path + '/{id}', get, methods=['GET'])
    router.add_api_route(path + '/{id}', modify, methods=['PUT'])
    router.add_api_route(path + '/{id}/enabled', toggle, methods=['PATCH'])
    router.add_api_route(path + '/{id}', remove, methods=['DELETE'])


register_context_routes('/recipe-contexts', RecipeContext, RecipeRule, RecipeUpdate, RecipeInput, True)
register_context_routes('/inspection-plan-contexts', InspectionPlanContext, InspectionRule, InspectionUpdate, InspectionInput, False)


def editable_plan(db, id):
    plan = require(db, InspectionPlan, id)
    if plan.card_version_id:
        ensure_draft(plan.card_version)
    return plan


@router.get('/inspection-plans/{plan_id}/items')
def items(plan_id: int, db: Session = Depends(get_db)):
    require(db, InspectionPlan, plan_id)
    return [dump(row) for row in db.query(InspectionItem).filter_by(inspection_plan_id=plan_id).order_by(InspectionItem.id)]


@router.post('/inspection-plans/{plan_id}/items', status_code=201)
def add_item(plan_id: int, data: ItemInput, db: Session = Depends(get_db)):
    editable_plan(db, plan_id)
    item = InspectionItem(inspection_plan_id=plan_id, **data.model_dump())
    db.add(item)
    commit(db)
    db.refresh(item)
    return dump(item)


@router.put('/inspection-plans/{plan_id}/items/{id}')
def edit_item(plan_id: int, id: int, data: ItemInput, db: Session = Depends(get_db)):
    editable_plan(db, plan_id)
    item = require(db, InspectionItem, id)
    if item.inspection_plan_id != plan_id:
        raise HTTPException(404, 'Item does not belong to this plan')
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    commit(db)
    return dump(item)


@router.delete('/inspection-plans/{plan_id}/items/{id}')
def remove_item(plan_id: int, id: int, db: Session = Depends(get_db)):
    editable_plan(db, plan_id)
    item = require(db, InspectionItem, id)
    if item.inspection_plan_id != plan_id:
        raise HTTPException(404, 'Item does not belong to this plan')
    db.delete(item)
    commit(db)
    return {'deleted': True}
