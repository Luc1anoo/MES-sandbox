"""Request work orders: immutable snapshots, explicit matching, authenticated actions."""
import hashlib
import hmac
import json
import math
import os
import secrets
from datetime import timedelta, date
from pathlib import Path
from typing import Literal
from urllib.parse import unquote
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .core import Base, Column, Integer, String, Text, DateTime, ForeignKey, JSON, now, get_db, require, dump, OperationStep, OperationGroup, OperationCard, ProcessFlow

class Member(Base):
    __tablename__='wo_members'
    id=Column(Integer,primary_key=True)
    name=Column(String(120),nullable=False,unique=True)
    password_hash=Column(Text,nullable=False)
class LoginSession(Base):
    __tablename__='wo_sessions'
    token=Column(String(64),primary_key=True)
    member_id=Column(Integer,ForeignKey('wo_members.id'),nullable=False)
    expires=Column(DateTime,nullable=False)
class Section(Base):
    __tablename__='wo_sections'
    id=Column(Integer,primary_key=True)
    name=Column(String(120),unique=True,nullable=False)
class StepPolicy(Base):
    __tablename__='wo_step_policies'
    step_id=Column(Integer,ForeignKey('operation_steps.id',ondelete='CASCADE'),primary_key=True)
    needs_ticket=Column(Boolean,nullable=False,default=False)
    kind=Column(String(20),nullable=False,default='processing')
    responsible_id=Column(Integer,ForeignKey('wo_members.id'))
class GroupSection(Base):
    __tablename__='wo_group_sections'
    group_id=Column(Integer,ForeignKey('operation_groups.id',ondelete='CASCADE'),primary_key=True)
    section_id=Column(Integer,ForeignKey('wo_sections.id',ondelete='RESTRICT'),nullable=False)
class TicketTemplate(Base):
    __tablename__='wo_templates'
    id=Column(Integer,primary_key=True)
    name=Column(String(120),nullable=False)
    kind=Column(String(20),nullable=False)
    needs_review=Column(Boolean,nullable=False)
    is_enabled=Column(Boolean,nullable=False,default=True)
    scopes=Column(JSON,nullable=False)
    fields=Column(JSON,nullable=False)
    revision=Column(Integer,nullable=False,default=1)
    created_at=Column(DateTime,default=now,nullable=False)
class ProductionOrder(Base):
    __tablename__='wo_orders'
    id=Column(Integer,primary_key=True)
    name=Column(String(120),nullable=False,unique=True)
    flow_id=Column(Integer,ForeignKey('process_flows.id',ondelete='RESTRICT'),nullable=False)
    owner_id=Column(Integer,ForeignKey('wo_members.id'),nullable=False)
    expert_id=Column(Integer,ForeignKey('wo_members.id'),nullable=False)
    stage=Column(String(30),nullable=False,default='created')
    bom_file_id=Column(String(64),ForeignKey('wo_files.id'))
    created_at=Column(DateTime,default=now)
class Ticket(Base):
    __tablename__='wo_tickets'
    __table_args__=(__import__('sqlalchemy').UniqueConstraint('order_id','step_id'),)
    id=Column(Integer,primary_key=True)
    order_id=Column(Integer,ForeignKey('wo_orders.id',ondelete='RESTRICT'),nullable=False)
    step_id=Column(Integer,ForeignKey('operation_steps.id',ondelete='RESTRICT'),nullable=False)
    template_id=Column(Integer,ForeignKey('wo_templates.id',ondelete='RESTRICT'))
    snapshot=Column(JSON)
    values=Column(JSON,nullable=False,default=dict)
    status=Column(String(30),nullable=False,default='unfilled')
    requester_id=Column(Integer,ForeignKey('wo_members.id'),nullable=False)
    responsible_id=Column(Integer,ForeignKey('wo_members.id'),nullable=False)
    expert_id=Column(Integer,ForeignKey('wo_members.id'),nullable=False)
    revision=Column(Integer,nullable=False,default=1)
    round=Column(Integer,nullable=False,default=0)
    votes=Column(JSON,nullable=False,default=dict)
    events=Column(JSON,nullable=False,default=list)
    archive=Column(JSON)
    created_at=Column(DateTime,default=now)
    updated_at=Column(DateTime,default=now)
    edited_by=Column(Integer,ForeignKey('wo_members.id'),nullable=False)
class Notification(Base):
    __tablename__='wo_notifications'
    id=Column(Integer,primary_key=True)
    member_id=Column(Integer,ForeignKey('wo_members.id'),nullable=False)
    ticket_id=Column(Integer,ForeignKey('wo_tickets.id'),nullable=False)
    message=Column(Text,nullable=False)
    is_read=Column(Boolean,default=False,nullable=False)
    created_at=Column(DateTime,default=now)
class StoredFile(Base):
    __tablename__='wo_files'
    id=Column(String(64),primary_key=True)
    name=Column(Text,nullable=False)
    owner_id=Column(Integer,ForeignKey('wo_members.id'),nullable=False)
    size=Column(Integer,nullable=False)

router=APIRouter(prefix='/api/workorders',tags=['Request Work Orders'])
class Input(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Credentials(Input):
    name:str=Field(min_length=1,max_length=120,pattern=r'\S')
    password:str=Field(min_length=8,max_length=256)

def commit(db):
    try: db.commit()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409,'名称重复或对象仍被引用') from exc

def actor(authorization:str=Header(default=''),db:Session=Depends(get_db)):
    token=authorization.removeprefix('Bearer ')
    login=db.get(LoginSession,hashlib.sha256(token.encode()).hexdigest())
    if not login or login.expires<now(): raise HTTPException(401,'请先登录工单工作区')
    return require(db,Member,login.member_id)

@router.post('/register',status_code=201)
def register(data:Credentials,db:Session=Depends(get_db)):
    salt=secrets.token_hex(16)
    hashed=hashlib.scrypt(data.password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
    member=Member(name=data.name.strip(),password_hash=salt+':'+hashed)
    db.add(member);commit(db)
    return {'id':member.id,'name':member.name}
@router.post('/login')
def login(data:Credentials,db:Session=Depends(get_db)):
    member=db.query(Member).filter_by(name=data.name.strip()).first()
    if not member: raise HTTPException(401,'账号或密码错误')
    salt,expected=member.password_hash.split(':')
    actual=hashlib.scrypt(data.password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
    if not hmac.compare_digest(expected,actual): raise HTTPException(401,'账号或密码错误')
    token=secrets.token_urlsafe(32)
    db.add(LoginSession(token=hashlib.sha256(token.encode()).hexdigest(),member_id=member.id,expires=now()+timedelta(hours=12)));commit(db)
    return {'token':token,'member':{'id':member.id,'name':member.name}}
@router.post('/logout')
def logout(authorization:str=Header(default=''),user=Depends(actor),db:Session=Depends(get_db)):
    login=db.get(LoginSession,hashlib.sha256(authorization.removeprefix('Bearer ').encode()).hexdigest())
    db.delete(login);commit(db);return {'logged_out':True}
@router.get('/members')
def members(user=Depends(actor),db:Session=Depends(get_db)):
    return [{'id':m.id,'name':m.name} for m in db.query(Member).order_by(Member.id)]

class Named(Input):
    name:str=Field(min_length=1,max_length=120,pattern=r'\S')
@router.post('/sections',status_code=201)
def add_section(data:Named,user=Depends(actor),db:Session=Depends(get_db)):
    obj=Section(name=data.name.strip());db.add(obj);commit(db);return dump(obj)
class GroupBinding(Input):
    section_id:int|None=None
@router.put('/groups/{id}/section')
def bind_section(id:int,data:GroupBinding,user=Depends(actor),db:Session=Depends(get_db)):
    group=require(db,OperationGroup,id)
    if db.query(Ticket).join(OperationStep,Ticket.step_id==OperationStep.id).filter(OperationStep.group_id==id).first():raise HTTPException(409,'群组已有订单工单，不可重新划分工段')
    if group.flow.revision.status!='Draft': raise HTTPException(409,'已发布流程不可修改工段')
    old=db.get(GroupSection,id)
    if data.section_id is None:
        if old: db.delete(old)
    else:
        require(db,Section,data.section_id)
        if old: old.section_id=data.section_id
        else: db.add(GroupSection(group_id=id,section_id=data.section_id))
    commit(db);return {'saved':True}
class PolicyInput(Input):
    needs_ticket:bool
    kind:Literal['processing','inspection']='processing'
    responsible_id:int|None=None
@router.put('/steps/{id}/policy')
def policy(id:int,data:PolicyInput,user=Depends(actor),db:Session=Depends(get_db)):
    step=require(db,OperationStep,id)
    if db.query(Ticket).filter_by(step_id=id).first():raise HTTPException(409,'工序已有订单工单，不可修改工单策略')
    if step.group.flow.revision.status!='Draft': raise HTTPException(409,'已发布工序不可修改工单属性')
    if data.needs_ticket and (not data.responsible_id or not step.card_version_id): raise HTTPException(422,'需要工单的工序必须绑定工序卡并指定责任人')
    if data.responsible_id: require(db,Member,data.responsible_id)
    obj=db.get(StepPolicy,id)
    if not obj: obj=StepPolicy(step_id=id);db.add(obj)
    for key,value in data.model_dump().items():setattr(obj,key,value)
    commit(db);return dump(obj)

TYPES={'text','number','quantity','coordinate','select','multi_select','status','date','person','created_time','created_by','edited_time','edited_by','files','url','email','phone'}
SYSTEM={'created_time','created_by','edited_time','edited_by'}
class Property(Input):
    key:str=Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,63}$')
    label:str=Field(min_length=1,max_length=120,pattern=r'\S')
    type:str
    required:bool=False
    options:list[str]=Field(default_factory=list)
    unit:str=''
    dimensions:Literal[2,3]=2
    status_groups:dict[str,list[str]]=Field(default_factory=dict)
    number_format:Literal['decimal','percent','currency']='decimal'
class Scope(Input):
    card_id:int
    group_id:int|None=None
    section_id:int|None=None
class TemplateInput(Named):
    kind:Literal['processing','inspection']
    needs_review:bool=False
    is_enabled:bool=True
    scopes:list[Scope]=Field(min_length=1)
    fields:list[Property]=Field(default_factory=list)
    revision:int|None=None

def validate_template(db,data):
    keys=set()
    for field in data.fields:
        if field.type not in TYPES or field.key in keys: raise HTTPException(422,'属性类型不支持或 key 重复')
        keys.add(field.key)
        if field.type in ('select','multi_select','status') and (not field.options or len(set(field.options))!=len(field.options) or any(not x.strip() for x in field.options)):raise HTTPException(422,'选项必须非空且不重复')
        if field.type=='status' and field.status_groups:
            grouped=[v for group in field.status_groups.values() for v in group]
            if len(grouped)!=len(set(grouped)) or set(grouped)!=set(field.options):raise HTTPException(422,'状态分组必须覆盖全部状态且不能重复')
        if field.type in ('quantity','coordinate') and not field.unit.strip():raise HTTPException(422,'物理量/坐标必须配置单位')
    for scope in data.scopes:
        require(db,OperationCard,scope.card_id)
        if scope.section_id and not scope.group_id:raise HTTPException(422,'选择工段前必须选择工序群组')
        if scope.group_id:require(db,OperationGroup,scope.group_id)
        if scope.section_id:
            require(db,Section,scope.section_id)
            binding=db.get(GroupSection,scope.group_id)
            if not binding or binding.section_id!=scope.section_id:raise HTTPException(422,'工段与群组不一致')

@router.get('/templates')
def templates(user=Depends(actor),db:Session=Depends(get_db)):
    return [dump(x) for x in db.query(TicketTemplate).order_by(TicketTemplate.id)]
@router.post('/templates',status_code=201)
def create_template(data:TemplateInput,user=Depends(actor),db:Session=Depends(get_db)):
    validate_template(db,data)
    obj=TicketTemplate(**data.model_dump(exclude={'revision'}));db.add(obj);commit(db);return dump(obj)
@router.put('/templates/{id}')
def edit_template(id:int,data:TemplateInput,user=Depends(actor),db:Session=Depends(get_db)):
    require(db,TicketTemplate,id);validate_template(db,data)
    result=db.execute(update(TicketTemplate).where(TicketTemplate.id==id,TicketTemplate.revision==data.revision).values(**data.model_dump(exclude={'revision'}),revision=(data.revision or 0)+1))
    if not result.rowcount:raise HTTPException(409,'模板已变更，请刷新')
    commit(db);db.expire_all();return dump(require(db,TicketTemplate,id))
@router.delete('/templates/{id}')
def delete_template(id:int,revision:int,user=Depends(actor),db:Session=Depends(get_db)):
    if db.query(Ticket).filter_by(template_id=id).first():raise HTTPException(409,'已使用模板请停用，不能删除')
    from sqlalchemy import delete
    if not db.execute(delete(TicketTemplate).where(TicketTemplate.id==id,TicketTemplate.revision==revision)).rowcount:raise HTTPException(409,'模板不存在或已变更')
    commit(db);return {'deleted':True}

def candidates(db,step,kind):
    if not step.card_version:return []
    binding=db.get(GroupSection,step.group_id)
    matches=[]
    for template in db.query(TicketTemplate).filter_by(is_enabled=True,kind=kind):
        scores=[1+int(s['group_id'] is not None)+int(s['section_id'] is not None) for s in template.scopes if s['card_id']==step.card_version.card_id and (s['group_id'] is None or s['group_id']==step.group_id) and (s['section_id'] is None or binding and s['section_id']==binding.section_id)]
        if scores:matches.append((max(scores),template))
    best=max((s for s,t in matches),default=0)
    return [{'id':t.id,'name':t.name,'specificity':score,'revision':t.revision} for score,t in sorted(matches,key=lambda x:x[1].id) if score==best]

class OrderInput(Named):
    flow_id:int
    owner_id:int
    expert_id:int
@router.post('/orders',status_code=201)
def create_order(data:OrderInput,user=Depends(actor),db:Session=Depends(get_db)):
    require(db,ProcessFlow,data.flow_id);require(db,Member,data.owner_id);require(db,Member,data.expert_id)
    obj=ProductionOrder(**data.model_dump());db.add(obj);commit(db);return dump(obj)
@router.get('/orders')
def orders(user=Depends(actor),db:Session=Depends(get_db)):
    return [dump(x) for x in db.query(ProductionOrder).order_by(ProductionOrder.id)]
class StageInput(Input):
    stage:Literal['bom','process_design','step_design','production']
    bom_file_id:str|None=None

def notify(db,ticket,ids,text):
    for id in set(ids):db.add(Notification(member_id=id,ticket_id=ticket.id,message=text))
@router.post('/orders/{id}/stage')
def stage(id:int,data:StageInput,user=Depends(actor),db:Session=Depends(get_db)):
    order=require(db,ProductionOrder,id)
    if order.owner_id!=user.id:raise HTTPException(403,'仅产线 Owner 可推进订单')
    stages=['created','bom','process_design','step_design','production']
    if data.stage==order.stage:return dump(order)
    if stages.index(data.stage)!=stages.index(order.stage)+1:raise HTTPException(409,'必须按订单阶段顺序推进')
    if data.stage=='bom':
        file=require(db,StoredFile,data.bom_file_id or '')
        if file.owner_id!=user.id:raise HTTPException(403,'请选择本人上传的 BOM')
        order.bom_file_id=file.id
    steps=[s for g in require(db,ProcessFlow,order.flow_id).groups for s in g.steps]
    if data.stage=='step_design':
        for step in steps:
            policy=db.get(StepPolicy,step.id)
            if not policy or not policy.needs_ticket:continue
            if not policy.responsible_id:raise HTTPException(422,'工序缺少责任人')
            if db.query(Ticket).filter_by(order_id=id,step_id=step.id).first():continue
            ticket=Ticket(order_id=id,step_id=step.id,requester_id=order.owner_id,responsible_id=policy.responsible_id,expert_id=order.expert_id,edited_by=user.id,values={},events=[],votes={})
            matches=candidates(db,step,policy.kind)
            if len(matches)==1:
                template=require(db,TicketTemplate,matches[0]['id'])
                if template.needs_review and len({order.owner_id,policy.responsible_id,order.expert_id})!=3:raise HTTPException(422,'评审模板需要需求人、责任人、专家为三个独立账号')
                ticket.template_id=template.id;ticket.snapshot=jsonable_encoder(dump(template))
            db.add(ticket)
            try: db.flush()
            except IntegrityError as exc:
                db.rollback();raise HTTPException(409,'工单已由另一次操作创建，请刷新') from exc
            notify(db,ticket,[order.owner_id],f'订单 {order.name} / {step.name} 请填写需求工单')
    if data.stage=='production':
        tickets=db.query(Ticket).filter_by(order_id=id).all()
        required=[s for s in steps if (db.get(StepPolicy,s.id) and db.get(StepPolicy,s.id).needs_ticket)]
        if any(not any(t.step_id==s.id and t.status in ('confirmed','approved') for t in tickets) for s in required):raise HTTPException(409,'存在未完成确认/评审的必需工单')
    # Compare-and-set prevents concurrent stage transitions and duplicate notifications.
    old=order.stage
    if not db.execute(update(ProductionOrder).where(ProductionOrder.id==id,ProductionOrder.stage==old).values(stage=data.stage)).rowcount:raise HTTPException(409,'订单阶段已改变，请刷新')
    commit(db);db.refresh(order);return dump(order)

def participant(ticket,user):
    if user.id not in (ticket.requester_id,ticket.responsible_id,ticket.expert_id):raise HTTPException(403,'不属于本工单参与人')
def ticket_view(db,ticket):
    data=dump(ticket)
    policy=db.get(StepPolicy,ticket.step_id)
    data['candidates']=candidates(db,require(db,OperationStep,ticket.step_id),policy.kind if policy else 'processing') if not ticket.snapshot else []
    ids={id for f in (ticket.snapshot or {}).get('fields',[]) if f['type']=='files' for id in (ticket.values.get(f['key']) or [])}
    data['attachments']=[dump(file) for id in ids if (file:=db.get(StoredFile,id))]
    data['system_properties']={'created_time':ticket.created_at.isoformat(),'created_by':ticket.requester_id,'edited_time':ticket.updated_at.isoformat(),'edited_by':ticket.edited_by}
    data['transfer_complete']=ticket.status in ('confirmed','reviewing','approved')
    data['archive_url']=f'/api/workorders/tickets/{ticket.id}/archive' if ticket.archive else None
    return data
@router.get('/tickets')
def tickets(order_id:int|None=None,user=Depends(actor),db:Session=Depends(get_db)):
    query=db.query(Ticket)
    if order_id:query=query.filter_by(order_id=order_id)
    return [ticket_view(db,t) for t in query.order_by(Ticket.id) if user.id in (t.requester_id,t.responsible_id,t.expert_id)]
@router.get('/tickets/{id}')
def ticket_detail(id:int,user=Depends(actor),db:Session=Depends(get_db)):
    ticket=require(db,Ticket,id);participant(ticket,user);return ticket_view(db,ticket)
class Choice(Input):
    template_id:int
    revision:int
@router.post('/tickets/{id}/template')
def choose(id:int,data:Choice,user=Depends(actor),db:Session=Depends(get_db)):
    ticket=require(db,Ticket,id)
    if user.id!=ticket.requester_id or ticket.snapshot:raise HTTPException(409,'模板已确定或不是需求人')
    matches=ticket_view(db,ticket)['candidates']
    if data.template_id not in [x['id'] for x in matches]:raise HTTPException(422,'只能选择当前最高匹配精度的模板')
    template=require(db,TicketTemplate,data.template_id)
    if template.needs_review and len({ticket.requester_id,ticket.responsible_id,ticket.expert_id})!=3:raise HTTPException(422,'评审模板需要三个独立参与人，请重新配置订单/工序')
    return change(db,ticket,data.revision,user,'选择模板',template_id=template.id,snapshot=jsonable_encoder(dump(template)))

def change(db,ticket,revision,user,event,**values):
    events=ticket.events+[{'time':now().isoformat(),'actor_id':user.id,'action':event,'round':values.get('round',ticket.round),'values':values.get('values'),'votes':values.get('votes')}]
    if not db.execute(update(Ticket).where(Ticket.id==ticket.id,Ticket.revision==revision).values(**values,events=events,updated_at=now(),edited_by=user.id,revision=revision+1)).rowcount:raise HTTPException(409,'工单已被修改，请刷新后重试')
    commit(db);db.expire_all();return ticket_view(db,require(db,Ticket,ticket.id))

class Content(Input):
    revision:int
    values:dict
    action:Literal['draft','confirm','review']='draft'

def validate_values(db,ticket,values,complete):
    fields={f['key']:f for f in ticket.snapshot['fields']}
    if any(key not in fields or fields[key]['type'] in SYSTEM for key in values):raise HTTPException(422,'未知属性或试图修改系统属性')
    def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    for key,f in fields.items():
        if f['type'] in SYSTEM:continue
        value=values.get(key)
        empty=value is None or (isinstance(value,str) and not value.strip()) or value==[]
        if empty:
            if complete and f['required']:raise HTTPException(422,f"{f['label']} 必填")
            continue
        t=f['type'];valid=True
        if t=='number':valid=number(value)
        elif t=='quantity':valid=isinstance(value,dict) and set(value)=={'value','unit'} and number(value['value']) and value['unit']==f['unit']
        elif t=='coordinate':valid=isinstance(value,dict) and set(value)=={'values','unit'} and isinstance(value['values'],list) and len(value['values'])==f['dimensions'] and all(number(v) for v in value['values']) and value['unit']==f['unit']
        elif t in ('select','status'):valid=value in f['options']
        elif t=='multi_select':valid=isinstance(value,list) and all(isinstance(v,str) and v in f['options'] for v in value) and len(set(value))==len(value)
        elif t=='person':valid=isinstance(value,int) and not isinstance(value,bool) and db.get(Member,value) is not None
        elif t=='files':valid=isinstance(value,list) and all(isinstance(v,str) and db.get(StoredFile,v) is not None and db.get(StoredFile,v).owner_id==ticket.requester_id for v in value)
        elif t=='date':
            try:
                dates=[value] if isinstance(value,str) else value
                valid=isinstance(dates,list) and len(dates) in (1,2) and all(isinstance(v,str) and date.fromisoformat(v) for v in dates) and (len(dates)==1 or dates[0]<=dates[1])
            except (ValueError,TypeError):valid=False
        else:
            valid=isinstance(value,str)
            if t=='url':valid=valid and value.startswith(('https://','http://'))
            if t=='email':valid=valid and __import__('re').fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value) is not None
            if t=='phone':valid=valid and __import__('re').fullmatch(r'[+\d][\d ()-]{2,30}',value) is not None
        if not valid:raise HTTPException(422,f"{f['label']} 格式错误")

@router.put('/tickets/{id}')
def fill(id:int,data:Content,user=Depends(actor),db:Session=Depends(get_db)):
    ticket=require(db,Ticket,id)
    if user.id!=ticket.requester_id:raise HTTPException(403,'仅需求人可填写')
    if not ticket.snapshot or ticket.status not in ('unfilled','draft','rejected'):raise HTTPException(409,'当前工单不可编辑')
    validate_values(db,ticket,data.values,data.action!='draft')
    review=ticket.snapshot['needs_review']
    if data.action=='confirm' and review or data.action=='review' and not review:raise HTTPException(422,'确认方式与评审要求不一致')
    status={'draft':'draft','confirm':'confirmed','review':'reviewing'}[data.action]
    archive=None
    if status=='confirmed':archive={'ticket_id':id,'template':ticket.snapshot,'values':data.values,'confirmed_by':user.id,'time':now().isoformat(),'message':'无需评审，需求人已确认'}
    if status=='reviewing' and len({ticket.requester_id,ticket.responsible_id,ticket.expert_id})!=3:raise HTTPException(422,'评审需要需求人、责任人、专家三个独立账号')
    if status=='confirmed':notify(db,ticket,[ticket.requester_id,ticket.responsible_id],'需求工单已确认，请工序执行人查看加工/检测需求')
    if status=='reviewing':notify(db,ticket,[ticket.requester_id,ticket.responsible_id,ticket.expert_id],'需求工单已发起评审，请审阅并提交意见')
    return change(db,ticket,data.revision,user,data.action,values=data.values,status=status,round=ticket.round+(status=='reviewing'),votes={},archive=archive)
class Vote(Input):
    revision:int
    approve:bool
    comment:str=Field(min_length=1,max_length=10000,pattern=r'\S')
@router.post('/tickets/{id}/vote')
def vote(id:int,data:Vote,user=Depends(actor),db:Session=Depends(get_db)):
    ticket=require(db,Ticket,id);participant(ticket,user)
    if ticket.status!='reviewing' or str(user.id) in ticket.votes:raise HTTPException(409,'当前不可评审或已投票')
    votes={**ticket.votes,str(user.id):{'approve':data.approve,'comment':data.comment,'time':now().isoformat(),'actor_name':user.name}}
    status='rejected' if not data.approve else 'approved' if len(votes)==3 else 'reviewing'
    archive=None
    if status=='approved':archive={'ticket_id':id,'round':ticket.round,'template':ticket.snapshot,'values':ticket.values,'votes':votes,'events':ticket.events,'archived_at':now().isoformat(),'message':'三方一致通过，在线归档'}
    if status in ('approved','rejected'):notify(db,ticket,[ticket.requester_id,ticket.responsible_id,ticket.expert_id],f'工单评审结果：{status}')
    return change(db,ticket,data.revision,user,'评审意见',votes=votes,status=status,archive=archive)
@router.get('/tickets/{id}/archive')
def archive(id:int,user=Depends(actor),db:Session=Depends(get_db)):
    ticket=require(db,Ticket,id);participant(ticket,user)
    if not ticket.archive:raise HTTPException(404,'尚无归档纪要')
    return ticket.archive
@router.get('/notifications')
def notifications(user=Depends(actor),db:Session=Depends(get_db)):
    return [dump(x) for x in db.query(Notification).filter_by(member_id=user.id).order_by(Notification.id.desc())]
@router.post('/notifications/{id}/read')
def read(id:int,user=Depends(actor),db:Session=Depends(get_db)):
    obj=require(db,Notification,id)
    if obj.member_id!=user.id:raise HTTPException(403,'无权访问')
    obj.is_read=True;commit(db);return dump(obj)

FILES=Path(os.getenv('MES_WORKORDER_FILES',str(Path(__file__).resolve().parents[2]/'.workorder-files')))
@router.post('/files',status_code=201)
async def upload(request:Request,x_filename:str=Header(default='attachment'),user=Depends(actor),db:Session=Depends(get_db)):
    FILES.mkdir(parents=True,exist_ok=True)
    id=secrets.token_hex(24);path=FILES/id;size=0
    try:
        with path.open('xb') as handle:
            async for chunk in request.stream():
                size+=len(chunk)
                if size>10*1024*1024:raise HTTPException(413,'单文件不能超过 10 MB')
                handle.write(chunk)
        obj=StoredFile(id=id,name=Path(unquote(x_filename).replace('\\','/')).name[:255] or 'attachment',size=size,owner_id=user.id)
        db.add(obj);commit(db);return dump(obj)
    except BaseException:
        path.unlink(missing_ok=True);raise
@router.get('/files/{id}')
def download(id:str,user=Depends(actor),db:Session=Depends(get_db)):
    obj=require(db,StoredFile,id)
    allowed=obj.owner_id==user.id or any(user.id in (t.requester_id,t.responsible_id,t.expert_id) and any(f['type']=='files' and id in (t.values.get(f['key']) or []) for f in (t.snapshot or {}).get('fields',[])) for t in db.query(Ticket))
    if not allowed:raise HTTPException(403,'无权访问附件')
    if not (FILES/id).is_file():raise HTTPException(404,'附件文件不存在')
    return FileResponse(FILES/id,filename=obj.name,media_type='application/octet-stream',headers={'X-Content-Type-Options':'nosniff'})
@router.get('/configuration')
def configuration(user=Depends(actor),db:Session=Depends(get_db)):
    return {'sections':[dump(x) for x in db.query(Section)],'groups':[dump(x) for x in db.query(GroupSection)],'policies':[dump(x) for x in db.query(StepPolicy)]}


# Once an order reaches step design, its shared path must remain stable.
# Revise by cloning the product revision/flow rather than rewriting a live order's path.
from sqlalchemy import event, inspect
@event.listens_for(Session,'before_flush')
def protect_order_paths(session,flush_context,instances):
    for obj in set(session.new)|set(session.dirty)|set(session.deleted):
        flow_ids=set()
        if isinstance(obj,ProcessFlow):flow_ids.add(obj.id)
        elif isinstance(obj,OperationGroup):
            flow_ids.add(obj.flow_id)
            flow_ids.update(inspect(obj).attrs.flow_id.history.deleted)
        elif isinstance(obj,OperationStep):
            ids={obj.group_id,*inspect(obj).attrs.group_id.history.deleted}
            for id in ids:
                group=session.get(OperationGroup,id) if id else obj.group
                if group:flow_ids.add(group.flow_id)
        else:continue
        if obj in session.dirty and not session.is_modified(obj,include_collections=False):continue
        if any(session.query(ProductionOrder).filter(ProductionOrder.flow_id==id,ProductionOrder.stage.in_(['step_design','production'])).first() for id in flow_ids if id):
            raise ValueError('订单已进入工序设计，工艺路径已冻结；请克隆新版本修改')
