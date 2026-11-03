import pytest
from test_business import post, setup, make_product
from app.core import SessionLocal
from app.workorders import GroupSection


@pytest.fixture(autouse=True)
def isolated_files(tmp_path,monkeypatch):
    monkeypatch.setattr('app.workorders.FILES',tmp_path/'uploads')


def account(c,name):
    assert c.post('/api/workorders/register',json={'name':name,'password':'password123'}).status_code==201
    r=c.post('/api/workorders/login',json={'name':name,'password':'password123'})
    assert r.status_code==200
    return r.json()['member']['id'], {'Authorization':'Bearer '+r.json()['token']}


def world(c,review=True):
    people=[account(c,n) for n in ('Owner','Executor','Expert','Other')]
    owner,executor,expert,other=people
    _,v,_=setup(c)
    _,_,flow,group,step=make_product(c,'Orders','1',v['id'])
    def req(method,path,data=None,who=owner):
        return c.request(method,'/api/workorders'+path,json=data,headers=who[1])
    assert req('PUT',f'/steps/{step["id"]}/policy',{'needs_ticket':True,'kind':'processing','responsible_id':executor[0]}).status_code==200
    fields=[{'key':'depth','label':'深度','type':'quantity','unit':'nm','required':True},{'key':'created','label':'创建者','type':'created_by'}]
    t=req('POST','/templates',{'name':'Etch','kind':'processing','needs_review':review,'scopes':[{'card_id':v['card_id']}],'fields':fields})
    assert t.status_code==201,t.text
    o=req('POST','/orders',{'name':'Order','flow_id':flow['id'],'owner_id':owner[0],'expert_id':expert[0]}).json()
    f=c.post('/api/workorders/files',headers={**owner[1],'X-Filename':'bom.csv'},content=b'part,count\na,1').json()
    assert req('POST',f'/orders/{o["id"]}/stage',{'stage':'bom','bom_file_id':f['id']}).status_code==200
    assert req('POST',f'/orders/{o["id"]}/stage',{'stage':'process_design'}).status_code==200
    return req,people,v,flow,group,step,t.json(),o


def trigger(req,order):
    r=req('POST',f'/orders/{order["id"]}/stage',{'stage':'step_design'})
    assert r.status_code==200,r.text
    return req('GET','/tickets').json()[0]


def test_no_review_draft_confirmation_archive_and_production(client):
    req,people,v,flow,group,step,template,order=world(client,False)
    ticket=trigger(req,order)
    assert ticket['status']=='unfilled' and not ticket['transfer_complete']
    assert len(req('GET','/notifications').json())==1
    assert req('POST',f'/orders/{order["id"]}/stage',{'stage':'step_design'}).status_code==200
    assert len(req('GET','/notifications').json())==1
    assert req('POST',f'/orders/{order["id"]}/stage',{'stage':'production'}).status_code==409
    url=f'/tickets/{ticket["id"]}'
    draft=req('PUT',url,{'revision':1,'values':{},'action':'draft'})
    assert draft.status_code==200 and draft.json()['status']=='draft'
    assert req('PUT',url,{'revision':2,'values':{},'action':'confirm'}).status_code==422
    content={'depth':{'value':100,'unit':'nm'}}
    result=req('PUT',url,{'revision':2,'values':content,'action':'confirm'})
    assert result.status_code==200,result.text
    assert result.json()['transfer_complete']
    assert req('GET',url+'/archive').json()['values']==content
    assert req('PUT',url,{'revision':3,'values':content,'action':'draft'}).status_code==409
    assert req('POST',f'/orders/{order["id"]}/stage',{'stage':'production'}).status_code==200


def test_review_reject_resubmit_unanimity_permissions_and_revisions(client):
    req,people,v,flow,group,step,t,order=world(client)
    ticket=trigger(req,order);url=f'/tickets/{ticket["id"]}'
    values={'depth':{'value':100,'unit':'nm'}}
    assert req('PUT',url,{'revision':1,'values':values,'action':'confirm'}).status_code==422
    assert req('PUT',url,{'revision':1,'values':values,'action':'review'},people[1]).status_code==403
    assert req('GET',url,who=people[3]).status_code==403
    r=req('PUT',url,{'revision':1,'values':values,'action':'review'}).json()
    assert r['status']=='reviewing' and r['transfer_complete']
    assert len(req('GET','/notifications',who=people[1]).json())==1
    assert req('POST',url+'/vote',{'revision':2,'approve':False,'comment':'深度需调整'},people[1]).json()['status']=='rejected'
    assert req('POST',url+'/vote',{'revision':3,'approve':True,'comment':'同意'},people[2]).status_code==409
    values['depth']['value']=90
    r=req('PUT',url,{'revision':3,'values':values,'action':'review'}).json()
    assert r['round']==2 and r['votes']=={}
    for index,who in enumerate(people[:3]):
        r=req('POST',url+'/vote',{'revision':4+index,'approve':True,'comment':'同意'},who)
        assert r.status_code==200,r.text
        assert r.json()['status']==('approved' if index==2 else 'reviewing')
    assert req('GET',url+'/archive').json()['values']['depth']['value']==90
    assert '深度需调整' in str(req('GET',url).json()['events'])
    assert req('POST',url+'/vote',{'revision':7,'approve':False,'comment':'重复'},people[1]).status_code==409


def test_template_specificity_continuity_ambiguity_and_snapshot(client):
    req,people,v,flow,group,step,t,order=world(client,False)
    section=req('POST','/sections',{'name':'FAB1'}).json()
    assert req('PUT',f'/groups/{group["id"]}/section',{'section_id':section['id']}).status_code==200
    payload={'name':'Specific','kind':'processing','scopes':[{'card_id':v['card_id'],'group_id':group['id'],'section_id':section['id']}],'fields':[]}
    invalid={**payload,'scopes':[{'card_id':v['card_id'],'section_id':section['id']}]}
    assert req('POST','/templates',invalid).status_code==422
    a=req('POST','/templates',payload).json();b=req('POST','/templates',{**payload,'name':'Conflict'}).json()
    ticket=trigger(req,order);url=f'/tickets/{ticket["id"]}'
    assert ticket['snapshot'] is None and {x['id'] for x in ticket['candidates']}=={a['id'],b['id']}
    assert req('POST',url+'/template',{'revision':1,'template_id':t['id']}).status_code==422
    chosen=req('POST',url+'/template',{'revision':1,'template_id':a['id']}).json()
    assert chosen['snapshot']['name']=='Specific'
    assert req('PUT',f'/templates/{a["id"]}',{**payload,'name':'Changed','revision':1}).status_code==200
    assert req('GET',url).json()['snapshot']['name']=='Specific'
    assert req('DELETE',f'/templates/{a["id"]}?revision=2').status_code==409
    assert req('PUT',url,{'revision':1,'values':{},'action':'draft'}).status_code==409


def test_properties_validation_and_files_access(client):
    req,people,v,flow,group,step,t,order=world(client,False)
    fields=[{'key':'p','label':'坐标','type':'coordinate','dimensions':3,'unit':'um','required':True},{'key':'email','label':'邮箱','type':'email'},{'key':'files','label':'附件','type':'files'}]
    payload={'name':'Fields','kind':'processing','scopes':[{'card_id':v['card_id']}],'fields':fields,'revision':1}
    assert req('PUT',f'/templates/{t["id"]}',payload).status_code==200
    ticket=trigger(req,order);url=f'/tickets/{ticket["id"]}'
    bad={'p':{'values':[1,2],'unit':'um'}}
    assert req('PUT',url,{'revision':1,'values':bad,'action':'confirm'}).status_code==422
    f=client.post('/api/workorders/files',headers={**people[0][1],'X-Filename':'test.pdf'},content=b'pdf').json()
    assert client.get('/api/workorders/files/'+f['id'],headers=people[1][1]).status_code==403
    values={'p':{'values':[1,2,3],'unit':'um'},'email':'a@b.com','files':[f['id']]}
    assert req('PUT',url,{'revision':1,'values':values,'action':'confirm'}).status_code==200
    assert client.get('/api/workorders/files/'+f['id'],headers=people[1][1]).status_code==200
    assert client.get('/api/workorders/files/'+f['id'],headers=people[3][1]).status_code==403
    assert client.get('/api/workorders/tickets').status_code==401


def test_migration_repeatable_and_no_legacy_changes(tmp_path):
    import sqlalchemy as sa
    from app.core import Base
    from migrate_workorders import migrate
    engine=sa.create_engine(f'sqlite:///{tmp_path / "old.db"}')
    Base.metadata.create_all(engine,tables=[t for t in Base.metadata.sorted_tables if not t.name.startswith('wo_')])
    with engine.begin() as conn:conn.execute(sa.text("INSERT INTO products (id,name) VALUES (1,'Existing')"))
    migrate(engine);migrate(engine)
    with engine.connect() as conn:assert conn.execute(sa.text('SELECT name FROM products')).scalar()=='Existing'


def test_order_path_freezing(client):
    req,people,v,flow,group,step,t,order=world(client,False)
    trigger(req,order)
    assert client.put(f'/api/steps/{step["id"]}',json={'name':'Changed'}).status_code==409
    assert req('PUT',f'/steps/{step["id"]}/policy',{'needs_ticket':False}).status_code==409
    assert client.post('/api/steps',json={'group_id':group['id'],'name':'Late step','sequence':20}).status_code==409


@pytest.mark.parametrize('kind,config,valid,invalid',[
 ('number',{},85,'85'),('select',{'options':['A','B']},'A','C'),
 ('multi_select',{'options':['A','B']},['A','B'],['A','A']),
 ('status',{'options':['Learning','Done']},'Done','Unknown'),
 ('date',{},['2026-11-01','2026-11-03'],['2026-11-03','2026-11-01']),
 ('url',{},'https://example.com','javascript:alert(1)'),
 ('email',{},'a@example.com','not-email'),('phone',{},'+65 12345678','words'),
 ('quantity',{'unit':'nm'},{'value':200,'unit':'nm'},{'value':200,'unit':'mm'}),
 ('coordinate',{'unit':'um','dimensions':2},{'values':[1,2],'unit':'um'},{'values':[1,2,3],'unit':'um'}),
])
def test_typed_properties(kind,config,valid,invalid,client):
    from app.workorders import Ticket,validate_values,Property
    from fastapi import HTTPException
    ticket=Ticket(snapshot={'fields':[Property(key='value',label='Value',type=kind,**config).model_dump()]})
    with SessionLocal() as db:
        validate_values(db,ticket,{'value':valid},True)
        with pytest.raises(HTTPException):validate_values(db,ticket,{'value':invalid},True)
        with pytest.raises(HTTPException):validate_values(db,ticket,{'unknown':'x'},True)
