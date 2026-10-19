import React, {useEffect, useState} from 'react';
import {Alert, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message} from 'antd';
import {api} from './api.js';

const optional = ['flow_id', 'step_id', 'card_version_id', 'equipment_id', 'chamber', 'substrate_type', 'inspection_type'];
const selectProps = {allowClear:true, showSearch:true, optionFilterProp:'label', style:{minWidth:180}};

export default function ContextManagement({kind}) {
  const recipe = kind === 'recipe';
  const path = recipe ? '/recipe-contexts' : '/inspection-plan-contexts';
  const targetKey = recipe ? 'recipe_id' : 'inspection_plan_id';
  const targetPath = recipe ? '/recipes' : '/inspection-plans';
  const [data,setData] = useState({rules:[],flows:[],versions:[],equipment:[],targets:[]});
  const [loading,setLoading] = useState(false), [saving,setSaving] = useState(false);
  const [editing,setEditing] = useState(null), [opened,setOpened] = useState(false);
  const [filters,setFilters] = useState({}), [result,setResult] = useState(null), [resolving,setResolving] = useState(false);
  const [form] = Form.useForm(), [testForm] = Form.useForm();
  const flowId = Form.useWatch('flow_id',form), equipmentId = Form.useWatch('equipment_id',form);
  const testFlow = Form.useWatch('flow_id',testForm), testEquipment = Form.useWatch('equipment_id',testForm);
  const load = async () => {
    setLoading(true);
    try {
      const [rules,flows,versions,equipment,targets] = await Promise.all([path,'/flows','/card-versions','/equipment',targetPath].map(p=>api.get(p)));
      setData({rules,flows,versions,equipment,targets});
    } catch(e) {message.error(e.message)} finally {setLoading(false)}
  };
  useEffect(()=>{load()},[path]);
  const steps = data.flows.flatMap(f=>f.groups.flatMap(g=>g.steps.map(s=>({...s,flow_id:f.id,label:`${f.name} #${f.id} / ${g.name} / ${s.sequence}: ${s.name} #${s.id}`}))));
  const options = rows=>rows.map(x=>({value:x.id,label:`${x.name || x.version} #${x.id}`}));
  const stepOptions = flow=>steps.filter(s=>!flow||s.flow_id===flow).map(s=>({value:s.id,label:s.label}));
  const versionOptions = data.versions.map(v=>({value:v.id,label:`Card #${v.card_id} / ${v.version} (${v.status}) #${v.id}`}));
  const chambers = id=>(data.equipment.find(e=>e.id===id)?.chambers||[]).map(c=>({value:c,label:c}));
  const label = (rows,id)=>id==null?'不限':rows.find(x=>x.id===id)?.name||`#${id}`;
  const open = rule=>{setEditing(rule);form.resetFields();form.setFieldsValue(rule||{priority:0,is_enabled:true});setOpened(true)};
  const save = async values=>{
    setSaving(true);
    try {
      const payload={...values};
      for(const key of optional) if((recipe ? key!=='inspection_type' : !['equipment_id','chamber','substrate_type'].includes(key))) payload[key]=values[key]??null;
      if(editing) await api.put(`${path}/${editing.id}`,{...payload,revision:editing.revision});else await api.post(path,payload);
      setOpened(false);setResult(null);message.success('规则已保存');await load();
    } catch(e){message.error(e.message)} finally{setSaving(false)}
  };
  const mutate = async fn=>{try{await fn();setResult(null);await load()}catch(e){message.error(e.message);await load()}};
  const run = async values=>{
    setResolving(true);setResult(null);
    try {setResult(await api.post(`${path}/resolve`,values))}
    catch(e){setResult({resolution_status:'error',message:e.message})}finally{setResolving(false)}
  };
  const rows=data.rules.filter(r=>Object.entries(filters).every(([k,v])=>v==null||r[k]===v));
  const columns=[
    {title:'配置名称',dataIndex:'name'},
    {title:'Flow',dataIndex:'flow_id',render:id=>label(data.flows,id)},
    {title:'Step',dataIndex:'step_id',render:id=>id==null?'不限':steps.find(s=>s.id===id)?.label||`#${id}`},
    {title:'卡版本',dataIndex:'card_version_id',render:id=>id==null?'不限':versionOptions.find(v=>v.value===id)?.label||`#${id}`},
    ...(recipe ? [{title:'Equipment',dataIndex:'equipment_id',render:id=>label(data.equipment,id)},{title:'Chamber',dataIndex:'chamber',render:v=>v||'不限'},{title:'Substrate',dataIndex:'substrate_type',render:v=>v||'不限'}] : [{title:'检测条件',dataIndex:'inspection_type',render:v=>v||'不限'}]),
    {title:recipe?'Recipe':'Inspection Plan',dataIndex:targetKey,render:id=>label(data.targets,id)},
    {title:'Priority',dataIndex:'priority',sorter:(a,b)=>a.priority-b.priority},
    {title:'启用',dataIndex:'is_enabled',render:(v,r)=><Switch checked={v} onChange={enabled=>mutate(()=>api.patch(`${path}/${r.id}/enabled`,{is_enabled:enabled,revision:r.revision}))}/>},
    {title:'说明',dataIndex:'description'},
    {title:'操作',fixed:'right',render:(_,r)=><Space><Button onClick={()=>open(r)}>编辑</Button><Popconfirm title="删除规则？" onConfirm={()=>mutate(()=>api.del(`${path}/${r.id}?revision=${r.revision}`))}><Button danger>删除</Button></Popconfirm></Space>}
  ];
  const conditionFields=(testing=false)=>{
    const f=testing?testForm:form, flow=testing?testFlow:flowId, eq=testing?testEquipment:equipmentId;
    return <>
      <Form.Item name="flow_id" label={testing?'直接父 Flow（可由 Step 推导）':'Flow（空表示不限）'}><Select {...selectProps} options={options(data.flows)} onChange={()=>{f.setFieldsValue({step_id:null,...(testing?{card_version_id:null}:{})});if(testing)setResult(null)}}/></Form.Item>
      <Form.Item name="step_id" label="Step" rules={testing?[{required:true}]:[]}><Select {...selectProps} options={stepOptions(flow)} onChange={id=>{if(testing){const s=steps.find(x=>x.id===id);f.setFieldsValue({flow_id:s?.flow_id,card_version_id:s?.card_version_id??null});setResult(null)}}}/></Form.Item>
      <Form.Item name="card_version_id" label={testing?'Operation Card Version（默认读取 Step 绑定）':'Operation Card Version'}><Select {...selectProps} options={versionOptions}/></Form.Item>
      {recipe?<>
        <Form.Item name="equipment_id" label="Equipment" rules={testing?[{required:true}]:[]}><Select {...selectProps} options={options(data.equipment)} onChange={()=>{f.setFieldsValue({chamber:null});if(testing)setResult(null)}}/></Form.Item>
        <Form.Item name="chamber" label="Chamber"><Select {...selectProps} options={chambers(eq)} disabled={!eq}/></Form.Item>
        {!testing&&<Form.Item name="substrate_type" label="Substrate Type（匹配绑定版本的基材）"><Select {...selectProps} options={[...new Set(data.versions.map(v=>v.substrate_type).filter(Boolean))].map(v=>({value:v,label:v}))}/></Form.Item>}
      </>:<Form.Item name="inspection_type" label="检测业务条件" rules={testing?[{required:true,whitespace:true}]:[]}><Input placeholder="例如：刻蚀后检测；空表示不限（仅规则）"/></Form.Item>}
    </>;
  };
  return <Space direction="vertical" style={{width:'100%'}} size="large">
    <Alert type="info" showIcon message="空条件表示不限。先比较条件数量，再比较 Priority（数值越大越优先）；同级不同目标返回冲突，不隐式回退。Step 按 ID 区分，Flow 为 Step 的直接父流程。"/>
    <Space wrap><Button type="primary" onClick={()=>open(null)}>新增规则</Button><Button onClick={load}>刷新</Button>
      {[['flow_id','Flow',options(data.flows)],['step_id','Step',stepOptions(filters.flow_id)],...(recipe?[['equipment_id','Equipment',options(data.equipment)]]:[]),[targetKey,recipe?'Recipe':'Inspection Plan',options(data.targets)]].map(([key,title,opts])=><Select key={key} {...selectProps} placeholder={`筛选 ${title}`} value={filters[key]} options={opts} onChange={value=>setFilters(prev=>({...prev,[key]:value,...(key==='flow_id'?{step_id:null}:{})}))}/>)}
    </Space>
    <Table rowKey="id" loading={loading} dataSource={rows} columns={columns} scroll={{x:1600}} pagination={{pageSize:10}}/>
    {!recipe&&<InspectionItems plans={data.targets} versions={data.versions} reload={load}/>}
    <Card title="Context Resolution 测试">
      <Form name={`${kind}-context-test`} form={testForm} layout="vertical" onFinish={run} onValuesChange={()=>setResult(null)}>
        {conditionFields(true)}<Button type="primary" htmlType="submit" loading={resolving}>Resolve</Button>
      </Form>
      {result&&<Alert style={{marginTop:16}} type={result.resolution_status==='resolved'?'success':result.resolution_status==='unresolved'?'warning':'error'} message={<><Tag>{result.resolution_status}</Tag>{result.message}</>} description={<><p>目标：{result.target_name||'—'}（{result.target_id??'—'}）</p><p>规则：{result.matched_context_name||'—'}（{result.matched_context_id??'—'}）</p><pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(result.match_details||{},null,2)}</pre>{result.conflicting_context_ids?.length>0&&<p>冲突规则：{result.conflicting_context_ids.join(', ')}</p>}</>}/>}
    </Card>
    <Modal width={720} title={editing?'编辑上下文规则':'新增上下文规则'} open={opened} onCancel={()=>setOpened(false)} onOk={()=>form.submit()} confirmLoading={saving} destroyOnHidden>
      <Form name={`${kind}-context-rule`} form={form} layout="vertical" onFinish={save}>
        <Form.Item name="name" label="配置名称" rules={[{required:true,whitespace:true}]}><Input maxLength={120}/></Form.Item>
        {conditionFields()}
        <Form.Item name={targetKey} label={recipe?'Recipe':'Inspection Plan'} rules={[{required:true}]}><Select {...selectProps} options={options(data.targets)}/></Form.Item>
        <Form.Item name="priority" label="Priority" rules={[{required:true}]}><InputNumber precision={0}/></Form.Item>
        <Form.Item name="is_enabled" label="启用" valuePropName="checked"><Switch/></Form.Item>
        <Form.Item name="description" label="说明"><Input.TextArea/></Form.Item>
      </Form>
    </Modal>
  </Space>;
}


function InspectionItems({plans,versions,reload}){
  const [planId,setPlanId]=useState(null),[items,setItems]=useState([]),[opened,setOpened]=useState(false),[editing,setEditing]=useState(null),[newPlan,setNewPlan]=useState(false),[busy,setBusy]=useState(false);
  const [form]=Form.useForm(),[planForm]=Form.useForm();
  const plan=plans.find(p=>p.id===planId);
  const frozen=!!plan?.card_version_id&&versions.find(v=>v.id===plan.card_version_id)?.status!=='Draft';
  const load=async()=>{if(!planId){setItems([]);return}try{setItems(await api.get(`/inspection-plans/${planId}/items`))}catch(e){message.error(e.message)}};
  useEffect(()=>{load()},[planId]);
  const open=item=>{setEditing(item);form.resetFields();form.setFieldsValue(item||{unit:'nm',frequency:'Every Lot'});setOpened(true)};
  const save=async values=>{setBusy(true);try{if(editing)await api.put(`/inspection-plans/${planId}/items/${editing.id}`,values);else await api.post(`/inspection-plans/${planId}/items`,values);setOpened(false);await load();await reload()}catch(e){message.error(e.message)}finally{setBusy(false)}};
  return <Card title="Inspection Plan 检测项目">
    <Space wrap><Select {...selectProps} placeholder="选择检测计划" value={planId} options={plans.map(p=>({value:p.id,label:`${p.name} #${p.id}`}))} onChange={id=>{setPlanId(id);setItems([])}}/><Button onClick={()=>{planForm.resetFields();setNewPlan(true)}}>新增独立检测计划</Button><Button disabled={!plan||frozen} onClick={()=>open(null)}>添加检测项目</Button></Space>
    {plan&&<Alert style={{marginTop:12}} type="info" message={frozen?'此计划关联已发布/废弃版本，检测项目只读。':'可维护多个检测项目；旧计划的内联检测字段继续保留。'} description={!items.length?`旧内联定义：${plan.inspection_type||'—'}；目标 ${plan.target??'—'} ${plan.unit||''}；LSL ${plan.lsl??'—'} / USL ${plan.usl??'—'}；抽样 ${plan.sampling_rule||'—'}；频率 ${plan.frequency||'—'}`:undefined}/>}
    <Table rowKey="id" dataSource={items} pagination={{pageSize:5}} columns={['name','inspection_type','sampling_rule','target','lsl','usl','unit','frequency'].map(k=>({title:k,dataIndex:k})).concat([{title:'操作',render:(_,item)=><Space><Button disabled={frozen} onClick={()=>open(item)}>编辑</Button><Popconfirm title="删除检测项目？" onConfirm={async()=>{try{await api.del(`/inspection-plans/${planId}/items/${item.id}`);await load();await reload()}catch(e){message.error(e.message)}}}><Button danger disabled={frozen}>删除</Button></Popconfirm></Space>}])}/>
    <Modal open={opened} title="检测项目" onCancel={()=>setOpened(false)} onOk={()=>form.submit()} confirmLoading={busy} destroyOnHidden><Form name="inspection-item" form={form} layout="vertical" onFinish={save}>
      {['name','inspection_type','sampling_rule','unit','frequency'].map(k=><Form.Item key={k} name={k} label={k} rules={k==='name'?[{required:true,whitespace:true}]:[]}><Input/></Form.Item>)}
      {['target','lsl','usl'].map(k=><Form.Item key={k} name={k} label={k}><InputNumber/></Form.Item>)}
    </Form></Modal>
    <Modal open={newPlan} title="新增独立检测计划" onCancel={()=>setNewPlan(false)} onOk={()=>planForm.submit()} confirmLoading={busy} destroyOnHidden><Form name="inspection-plan" form={planForm} layout="vertical" onFinish={async values=>{setBusy(true);try{const p=await api.post('/inspection-plans',values);await reload();setPlanId(p.id);setNewPlan(false)}catch(e){message.error(e.message)}finally{setBusy(false)}}}>
      <Form.Item name="name" label="计划名称" rules={[{required:true,whitespace:true}]}><Input/></Form.Item><Form.Item name="version" label="版本" initialValue="1.0"><Input/></Form.Item>
    </Form></Modal>
  </Card>;
}
