"""Database-driven resolution. Specificity first, priority second; never first-row fallback."""
from fastapi import HTTPException
from ..core import (require, dump, OperationStep, OperationCardVersion, Equipment,
                    ProcessFlow, Recipe, InspectionPlan)
from ..context_models import RecipeContext, InspectionPlanContext

COMMON = ('flow_id', 'step_id', 'card_version_id')
RECIPE_FIELDS = COMMON + ('equipment_id', 'chamber', 'substrate_type')
INSPECTION_FIELDS = COMMON + ('inspection_type',)


def direct_context(db, data, recipe=False):
    step = require(db, OperationStep, data.step_id)
    flow_id = step.group.flow_id  # Immediate parent, never an inferred top-level flow.
    if data.flow_id is not None and data.flow_id != flow_id:
        raise HTTPException(422, 'Flow must be the Step’s direct parent Flow')
    if data.card_version_id is not None and data.card_version_id != step.card_version_id:
        raise HTTPException(422, 'Card version must equal the Step’s bound card version')
    version = require(db, OperationCardVersion, step.card_version_id) if step.card_version_id else None
    context = dict(flow_id=flow_id, step_id=step.id, card_version_id=step.card_version_id)
    if recipe:
        equipment = require(db, Equipment, data.equipment_id)
        if data.chamber is not None and data.chamber not in (equipment.chambers or []):
            raise HTTPException(422, 'Chamber does not belong to the selected equipment')
        context.update(equipment_id=equipment.id, chamber=data.chamber,
                       substrate_type=(version.substrate_type or None) if version else None)
    else:
        context['inspection_type'] = data.inspection_type
    return context


def target_valid(db, target, context, recipe):
    # Standalone master data is valid; linked targets must belong to this snapshot.
    if target.card_version_id is not None:
        version = db.get(OperationCardVersion, target.card_version_id)
        if not version or version.status != 'Released' or target.card_version_id != context['card_version_id']:
            return False
    if recipe:
        if target.equipment_id is not None and target.equipment_id != context['equipment_id']:
            return False
        if target.chamber and target.chamber != context['chamber']:
            return False
    return True


def resolve(db, data, recipe=False):
    context = direct_context(db, data, recipe)
    model, target_model, target_key, fields = (
        (RecipeContext, Recipe, 'recipe_id', RECIPE_FIELDS) if recipe else
        (InspectionPlanContext, InspectionPlan, 'inspection_plan_id', INSPECTION_FIELDS))
    candidates = []
    for rule in db.query(model).filter(model.is_enabled.is_(True)).all():
        conditions = {field: getattr(rule, field) for field in fields if getattr(rule, field) is not None}
        if not all(context[field] == value for field, value in conditions.items()):
            continue
        target = db.get(target_model, getattr(rule, target_key))
        if target is not None and target_valid(db, target, context, recipe):
            candidates.append(((len(conditions), rule.priority), rule, target, conditions))
    result = dict(resolution_status='unresolved', target_id=None, target_name=None,
                  matched_context_id=None, matched_context_name=None,
                  match_details={'input': context, 'ranking': 'specificity DESC, priority DESC'},
                  message='没有匹配的有效规则；不会隐式选择默认目标', conflicting_context_ids=[])
    if not candidates:
        return result
    best = max(row[0] for row in candidates)
    winners = sorted((row for row in candidates if row[0] == best), key=lambda row: row[1].id)
    result['match_details'].update(specificity=best[0], priority=best[1],
                                  matched_rules=[{'id': row[1].id, 'name': row[1].name, 'conditions': row[3]} for row in winners])
    if len({row[2].id for row in winners}) > 1:
        result.update(resolution_status='ambiguous', conflicting_context_ids=[row[1].id for row in winners],
                      message='最高优先级规则指向不同目标，请管理员修复冲突配置')
        return result
    _, rule, target, conditions = winners[0]
    result.update(resolution_status='resolved', target_id=target.id, target_name=target.name,
                  target=dump(target), matched_context_id=rule.id, matched_context_name=rule.name,
                  message='解析成功；同目标并列规则按最小规则 ID 展示，全部命中列于 match_details')
    return result


def validate_rule(db, values, recipe):
    for field, model in [('flow_id', ProcessFlow), ('step_id', OperationStep),
                         ('card_version_id', OperationCardVersion), ('equipment_id', Equipment)]:
        if values.get(field) is not None:
            require(db, model, values[field])
    step = db.get(OperationStep, values['step_id']) if values.get('step_id') else None
    if step and values.get('flow_id') is not None and step.group.flow_id != values['flow_id']:
        raise HTTPException(422, 'Step does not belong to Flow')
    if step and values.get('card_version_id') is not None and step.card_version_id != values['card_version_id']:
        raise HTTPException(422, 'Step does not reference this card version')
    version_id = values.get('card_version_id') or (step.card_version_id if step else None)
    target = require(db, Recipe if recipe else InspectionPlan, values['recipe_id' if recipe else 'inspection_plan_id'])
    if target.card_version_id is not None:
        version = require(db, OperationCardVersion, target.card_version_id)
        if version.status != 'Released':
            raise HTTPException(422, 'Target linked to a card must belong to a Released version')
        if version_id is not None and version_id != target.card_version_id:
            raise HTTPException(422, 'Target belongs to a different card version')
    if recipe:
        equipment = db.get(Equipment, values['equipment_id']) if values.get('equipment_id') else None
        if values.get('chamber') is not None:
            if not equipment or values['chamber'] not in (equipment.chambers or []):
                raise HTTPException(422, 'Chamber requires equipment and must belong to it')
        if equipment and target.equipment_id is not None and target.equipment_id != equipment.id:
            raise HTTPException(422, 'Recipe equipment conflicts with rule')
        if values.get('chamber') and target.chamber and values['chamber'] != target.chamber:
            raise HTTPException(422, 'Recipe chamber conflicts with rule')
