def post(c,path,data):
    r=c.post('/api'+path,json=data);assert r.status_code==201,r.text;return r.json()
def setup(c):
    card=post(c,'/operation-cards',{'code':'EBL','name':'EBL'})
    v=post(c,f'/operation-cards/{card["id"]}/versions',{'version':'1.0'})
    eq=post(c,'/equipment',{'name':'EBPG5200'})
    rec=post(c,'/recipes',{'card_version_id':v['id'],'name':'Exposure','equipment_id':eq['id'],'parameters':{'dose':120}})
    assert c.post(f'/api/card-versions/{v["id"]}/release').status_code==200
    return card,v,rec

def make_product(c,name,revver,vid):
    p=post(c,'/products',{'name':name});rev=post(c,'/revisions',{'product_id':p['id'],'version':revver});f=post(c,'/flows',{'revision_id':rev['id'],'name':'Flow'});g=post(c,'/groups',{'flow_id':f['id'],'name':'Lithography','sequence':10});s=post(c,'/steps',{'group_id':g['id'],'name':'EBL','sequence':10,'card_version_id':vid});return p,rev,f,g,s

def test_shared_master_data_and_product_deletion(client):
    c=client;card,v,_=setup(c)
    p1,_,_,_,s1=make_product(c,'Product A','1.0',v['id'])
    p2,_,_,_,s2=make_product(c,'Product B','2.0',v['id'])
    assert s1['card_version_id']==s2['card_version_id']
    assert c.delete(f'/api/products/{p1["id"]}').status_code==200
    assert c.get(f'/api/operation-cards/{card["id"]}').status_code==200
    assert c.get(f'/api/steps/{s2["id"]}').status_code==200

def test_clone_version_preserves_old_data_and_history(client):
    c=client;card,v,rec=setup(c)
    p,rev,f,g,s=make_product(c,'CGH','1.0',v['id'])
    assert c.post(f'/api/revisions/{rev["id"]}/release').status_code==200
    v2=post(c,f'/card-versions/{v["id"]}/clone',{'version':'2.0'})
    r2=v2['recipes'][0];r2['parameters']={'dose':130}
    assert c.put(f'/api/recipes/{r2["id"]}',json={k:r2[k] for k in ['card_version_id','name','version','equipment_id','chamber','parameters']}).status_code==200
    assert c.post(f'/api/card-versions/{v2["id"]}/release').status_code==200
    newrev=post(c,f'/revisions/{rev["id"]}/clone',{'version':'2.0'})
    newflow=c.get('/api/flows').json()[-1]
    newstep=newflow['groups'][0]['steps'][0]
    assert c.put(f'/api/steps/{newstep["id"]}',json={'card_version_id':v2['id']}).status_code==200
    assert c.get(f'/api/steps/{s["id"]}').json()['card_version_id']==v['id']
    assert c.get(f'/api/card-versions/{v["id"]}').json()['recipes'][0]['parameters']['dose']==120
    assert c.get(f'/api/card-versions/{v2["id"]}').json()['recipes'][0]['parameters']['dose']==130
    assert c.put(f'/api/steps/{s["id"]}',json={'card_version_id':v2['id']}).status_code==409

def test_released_immutable_and_no_draft_bind(client):
    c=client;card,v,recipe=setup(c)
    assert c.put(f'/api/card-versions/{v["id"]}',json={'description':'tamper'}).status_code==409
    assert c.put(f'/api/recipes/{recipe["id"]}',json={'card_version_id':v['id'],'name':'bad','parameters':{'dose':999}}).status_code==409
    assert c.delete(f'/api/card-versions/{v["id"]}').status_code==409
    draft=post(c,f'/operation-cards/{card["id"]}/versions',{'version':'2.0'})
    p=post(c,'/products',{'name':'Test'});rev=post(c,'/revisions',{'product_id':p['id'],'version':'1.0'});f=post(c,'/flows',{'revision_id':rev['id'],'name':'f'});g=post(c,'/groups',{'flow_id':f['id'],'name':'g','sequence':10})
    assert c.post('/api/steps',json={'group_id':g['id'],'name':'bad','sequence':10,'card_version_id':draft['id']}).status_code==409

def test_duplicate_versions_rejected(client):
    c=client;card,v,_=setup(c)
    assert c.post(f'/api/operation-cards/{card["id"]}/versions',json={'version':'1.0'}).status_code==409
