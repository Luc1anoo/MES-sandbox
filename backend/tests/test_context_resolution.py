from test_business import post, setup, make_product


def fixture(c):
    _, version, recipe = setup(c)
    equipment = c.get('/api/equipment').json()[0]
    assert c.put(f'/api/equipment/{equipment["id"]}', json={'name':equipment['name'],'chambers':['A','B']}).status_code == 200
    _, _, flow, _, step = make_product(c, 'Context Product', '1', version['id'])
    return version, recipe, equipment, flow, step


def rule(c, **values):
    return post(c, '/recipe-contexts', {'name':'Rule', **values})


def resolve(c, step, equipment, **values):
    r = c.post('/api/recipe-contexts/resolve', json={'step_id':step['id'],'equipment_id':equipment['id'], **values})
    assert r.status_code == 200, r.text
    return r.json()


def test_specificity_ambiguity_disable_no_fallback(client):
    c = client
    v, recipe, eq, flow, step = fixture(c)
    assert resolve(c, step, eq)['resolution_status'] == 'unresolved'
    standalone = post(c, '/recipes', {'name':'Universal','parameters':{'depth':25}})
    general = rule(c, recipe_id=standalone['id'], priority=999)
    conditions = dict(flow_id=flow['id'], step_id=step['id'], equipment_id=eq['id'], chamber='A', priority=-1)
    specific = rule(c, recipe_id=recipe['id'], **conditions)
    assert resolve(c, step, eq, chamber='A')['matched_context_id'] == specific['id']
    assert resolve(c, step, eq, chamber='B')['matched_context_id'] == general['id']
    conflict = rule(c, recipe_id=standalone['id'], **conditions)
    result = resolve(c, step, eq, chamber='A')
    assert result['resolution_status'] == 'ambiguous' and result['target_id'] is None
    assert result['conflicting_context_ids'] == [specific['id'], conflict['id']]
    url = f'/api/recipe-contexts/{conflict["id"]}'
    assert c.patch(url+'/enabled', json={'revision':1,'is_enabled':False}).status_code == 200
    assert resolve(c, step, eq, chamber='A')['target_id'] == recipe['id']
    assert c.patch(url+'/enabled', json={'revision':1,'is_enabled':True}).status_code == 409
    assert c.delete(url+'?revision=1').status_code == 409
    assert c.delete(url+'?revision=2').status_code == 200


def test_priority_same_target_ties_and_optimistic_update(client):
    c = client
    _, recipe, eq, _, step = fixture(c)
    first = rule(c, recipe_id=recipe['id'], step_id=step['id'])
    second = rule(c, recipe_id=recipe['id'], step_id=step['id'])
    result = resolve(c, step, eq)
    assert result['resolution_status'] == 'resolved'
    assert result['matched_context_id'] == first['id']
    assert len(result['match_details']['matched_rules']) == 2
    payload = {k:v for k,v in second.items() if k not in ('id','created_at','updated_at')}
    payload['priority'] = 1
    url = f'/api/recipe-contexts/{second["id"]}'
    assert c.put(url, json=payload).status_code == 200
    assert resolve(c, step, eq)['matched_context_id'] == second['id']
    assert c.put(url, json=payload).status_code == 409


def test_direct_flow_same_named_steps_validation_and_restrict_delete(client):
    c = client
    v, recipe, eq, flow, step = fixture(c)
    _, _, other_flow, _, other_step = make_product(c, 'Other', '1', v['id'])
    assert step['name'] == other_step['name']
    chosen = rule(c, recipe_id=recipe['id'], flow_id=flow['id'], step_id=step['id'])
    assert resolve(c, step, eq)['matched_context_id'] == chosen['id']
    assert resolve(c, other_step, eq)['resolution_status'] == 'unresolved'
    for values in ({'flow_id':other_flow['id']},{'chamber':'invalid'},{'equipment_id':999},{'card_version_id':999}):
        r = c.post('/api/recipe-contexts/resolve', json={'step_id':step['id'],'equipment_id':eq['id'], **values})
        assert r.status_code in (404,422)
    assert c.post('/api/recipe-contexts/resolve', json={'step_id':step['id']}).status_code == 422
    assert c.post('/api/recipe-contexts/resolve', json={'step_id':step['id'],'equipment_id':eq['id'],'recipe_id':recipe['id']}).status_code == 422
    assert c.post('/api/recipe-contexts', json={'name':'bad','recipe_id':recipe['id'],'flow_id':other_flow['id'],'step_id':step['id']}).status_code == 422
    assert c.post('/api/recipe-contexts', json={'name':'bad','recipe_id':recipe['id'],'chamber':'A'}).status_code == 422
    assert c.post('/api/recipe-contexts', json={'name':'bad','recipe_id':999}).status_code == 404
    assert c.delete('/api/products/1').status_code == 409


def test_substrate_and_invalid_targets(client):
    c = client
    v, recipe, eq, flow, step = fixture(c)
    rule(c, recipe_id=recipe['id'], substrate_type='Quartz')
    assert resolve(c, step, eq)['resolution_status'] == 'unresolved'
    draft = post(c, f'/operation-cards/{v["card_id"]}/versions', {'version':'2'})
    draft_recipe = post(c, '/recipes', {'name':'draft','card_version_id':draft['id']})
    assert c.post('/api/recipe-contexts', json={'name':'invalid','recipe_id':draft_recipe['id']}).status_code == 422
    valid = rule(c, recipe_id=recipe['id'])
    assert resolve(c, step, eq)['matched_context_id'] == valid['id']
    assert c.post(f'/api/card-versions/{v["id"]}/obsolete').status_code == 200
    assert resolve(c, step, eq)['resolution_status'] == 'unresolved'


def test_inspection_items_and_independent_rules(client):
    c = client
    _, recipe, eq, flow, step = fixture(c)
    plan = post(c, '/inspection-plans', {'name':'Etch Plan'})
    post(c, f'/inspection-plans/{plan["id"]}/items', {'name':'Depth','target':100,'lsl':95,'usl':105,'unit':'nm'})
    post(c, f'/inspection-plans/{plan["id"]}/items', {'name':'CD','target':20})
    assert len(c.get(f'/api/inspection-plans/{plan["id"]}').json()['items']) == 2
    context = post(c, '/inspection-plan-contexts', {'name':'After Etch','inspection_plan_id':plan['id'],'flow_id':flow['id'],'inspection_type':'刻蚀后检测'})
    payload = {'step_id':step['id'],'inspection_type':'刻蚀后检测'}
    result = c.post('/api/inspection-plan-contexts/resolve', json=payload).json()
    assert result['resolution_status'] == 'resolved' and result['target_id'] == plan['id']
    assert len(result['target']['items']) == 2
    assert c.get('/api/recipe-contexts').json() == []
    assert c.post('/api/inspection-plan-contexts/resolve', json={'step_id':step['id'],'inspection_type':'其他'}).json()['resolution_status'] == 'unresolved'
    assert c.post('/api/inspection-plan-contexts/resolve', json={'step_id':step['id'],'inspection_type':' '}).status_code == 422
    assert c.post(f'/api/inspection-plans/{plan["id"]}/items', json={'name':'bad','lsl':10,'usl':1}).status_code == 422
    assert c.delete(f'/api/inspection-plans/{plan["id"]}').status_code == 409
    assert c.delete(f'/api/inspection-plan-contexts/{context["id"]}?revision=1').status_code == 200
    assert c.delete(f'/api/inspection-plans/{plan["id"]}').status_code == 200


def test_items_freeze_clone_legacy_compatibility(client):
    c = client
    card = post(c, '/operation-cards', {'code':'IP','name':'Inspection'})
    v = post(c, f'/operation-cards/{card["id"]}/versions', {'version':'1'})
    plan = post(c, '/inspection-plans', {'name':'Plan','card_version_id':v['id'],'target':100,'usl':105,'lsl':95})
    assert plan['target'] == 100 and plan['items'] == []
    item = post(c, f'/inspection-plans/{plan["id"]}/items', {'name':'Thickness','target':50})
    assert c.post(f'/api/card-versions/{v["id"]}/release').status_code == 200
    url = f'/api/inspection-plans/{plan["id"]}/items'
    assert c.post(url, json={'name':'extra'}).status_code == 409
    assert c.put(url+f'/{item["id"]}', json={'name':'changed'}).status_code == 409
    assert c.delete(url+f'/{item["id"]}').status_code == 409
    cloned = post(c, f'/card-versions/{v["id"]}/clone', {'version':'2'})
    assert cloned['inspections'][0]['items'][0]['name'] == 'Thickness'
    assert cloned['inspections'][0]['items'][0]['id'] != item['id']
    assert cloned['inspections'][0]['target'] == 100


def test_migration_additive_repeatable(tmp_path):
    import sqlalchemy as sa
    from migrate_context_resolution import migrate
    from app.core import Base
    bind = sa.create_engine(f'sqlite:///{tmp_path / "legacy.db"}')
    new_tables = {'inspection_items','recipe_contexts','inspection_plan_contexts'}
    Base.metadata.create_all(bind, tables=[t for t in Base.metadata.sorted_tables if t.name not in new_tables])
    with bind.begin() as conn:
        conn.execute(sa.text("INSERT INTO inspection_plans (id,name,target,unit) VALUES (1,'Legacy',100,'nm')"))
    migrate(bind)
    migrate(bind)
    with bind.connect() as conn:
        assert conn.execute(sa.text('SELECT name,target,unit FROM inspection_plans WHERE id=1')).one() == ('Legacy',100,'nm')
        assert conn.execute(sa.text('SELECT count(*) FROM inspection_items')).scalar() == 0
    assert new_tables.issubset(sa.inspect(bind).get_table_names())
    bind.dispose()


def test_inspection_priority_conflict_filter_and_live_edit(client):
    c = client
    _, _, eq, flow, step = fixture(c)
    plans = [post(c, '/inspection-plans', {'name':f'Plan {i}'}) for i in (1,2)]
    generic = post(c, '/inspection-plan-contexts', {'name':'generic','inspection_plan_id':plans[0]['id'],'priority':100})
    values = {'name':'specific','inspection_plan_id':plans[1]['id'],'step_id':step['id'],'inspection_type':'After'}
    specific = post(c, '/inspection-plan-contexts', values)
    payload = {'step_id':step['id'],'inspection_type':'After'}
    def resolve_plan():
        return c.post('/api/inspection-plan-contexts/resolve', json=payload).json()
    assert resolve_plan()['target_id'] == plans[1]['id']
    conflict = post(c, '/inspection-plan-contexts', {**values,'inspection_plan_id':plans[0]['id']})
    assert resolve_plan()['resolution_status'] == 'ambiguous'
    assert set(resolve_plan()['conflicting_context_ids']) == {specific['id'],conflict['id']}
    assert c.get(f'/api/inspection-plan-contexts?step_id={step["id"]}').json() == [specific,conflict]
    url = f'/api/inspection-plan-contexts/{conflict["id"]}'
    assert c.put(url,json={**values,'inspection_plan_id':plans[0]['id'],'priority':1,'revision':1}).status_code == 200
    assert resolve_plan()['matched_context_id'] == conflict['id']
    assert c.patch(url+'/enabled',json={'revision':2,'is_enabled':False}).status_code == 200
    assert resolve_plan()['matched_context_id'] == specific['id']
    assert c.delete(url+'?revision=2').status_code == 409
    assert c.delete(url+'?revision=3').status_code == 200


def test_valid_substrate_and_target_equipment_membership(client):
    c = client
    card = post(c, '/operation-cards', {'code':'SUB','name':'Substrate'})
    v = post(c, f'/operation-cards/{card["id"]}/versions', {'version':'1','substrate_type':'Quartz'})
    eq = post(c, '/equipment', {'name':'Etcher','chambers':['A']})
    r = post(c, '/recipes', {'name':'Quartz Etch','card_version_id':v['id'],'equipment_id':eq['id'],'chamber':'A'})
    assert c.post(f'/api/card-versions/{v["id"]}/release').status_code == 200
    _, _, flow, _, step = make_product(c, 'Quartz', '1', v['id'])
    ctx = rule(c, recipe_id=r['id'], substrate_type='Quartz')
    assert resolve(c,step,eq,chamber='A')['matched_context_id'] == ctx['id']
    assert resolve(c,step,eq)['resolution_status'] == 'unresolved'
    other = post(c, '/equipment', {'name':'Other','chambers':['A']})
    assert resolve(c,step,other,chamber='A')['resolution_status'] == 'unresolved'
    assert c.post('/api/recipe-contexts',json={'name':'bad','recipe_id':r['id'],'equipment_id':other['id']}).status_code == 422


def test_context_reference_and_item_membership_protection(client):
    c = client
    _, recipe, eq, flow, step = fixture(c)
    standalone = post(c, '/recipes', {'name':'Standalone'})
    ctx = rule(c, recipe_id=standalone['id'], equipment_id=eq['id'])
    assert c.delete(f'/api/recipes/{standalone["id"]}').status_code == 409
    plans = [post(c, '/inspection-plans', {'name':f'P{i}'}) for i in (1,2)]
    item = post(c, f'/inspection-plans/{plans[0]["id"]}/items', {'name':'CD'})
    assert c.put(f'/api/inspection-plans/{plans[1]["id"]}/items/{item["id"]}',json={'name':'Wrong'}).status_code == 404
    assert c.delete(f'/api/inspection-plans/{plans[1]["id"]}/items/{item["id"]}').status_code == 404
    assert c.put(f'/api/inspection-plans/{plans[0]["id"]}/items/{item["id"]}',json={'name':'Updated','target':5,'usl':10,'lsl':0}).status_code == 200
    assert c.delete(f'/api/inspection-plans/{plans[0]["id"]}/items/{item["id"]}').status_code == 200
