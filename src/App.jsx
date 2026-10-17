import React,{useEffect,useMemo,useState} from 'react';
import {Layout,Menu,Typography,Card,Table,Button,Space,Tag,Select,Input,InputNumber,Modal,Form,message,Descriptions,Drawer,Tabs,Popconfirm,Tree,Row,Col,Statistic,Divider,Empty,Alert, Collapse} from 'antd';
import {ApartmentOutlined,AppstoreOutlined,DatabaseOutlined,ReloadOutlined,PlusOutlined,CopyOutlined,CheckCircleOutlined,DeleteOutlined} from '@ant-design/icons';
const {Sider,Content,Header}=Layout;
const req=async(path,options={})=>{let r;try{r=await fetch('/api'+path,{headers:{'Content-Type':'application/json'},...options,body:options.body?JSON.stringify(options.body):undefined});}catch(e){throw new Error('无法连接后端，请启动 FastAPI（8000 端口）');}let data=await r.json().catch(()=>null);if(!r.ok)throw new Error(typeof data?.detail==='string'?data.detail:'HTTP '+r.status);return data};
const api={get:p=>req(p),post:(p,d)=>req(p,{method:'POST',body:d}),put:(p,d)=>req(p,{method:'PUT',body:d}),del:p=>req(p,{method:'DELETE'})};
function useRemote(paths){const [data,setData]=useState({}),[loading,setLoading]=useState(false);const load=async()=>{setLoading(true);try{const result=await Promise.all(paths.map(p=>api.get(p)));setData(Object.fromEntries(paths.map((p,i)=>[p,result[i]])));}catch(e){message.error(e.message)}finally{setLoading(false)}};useEffect(()=>{load()},[]);return {data,loading,load}}
const Status=({value})=><Tag color={value==='Released'?'green':value==='Draft'?'orange':'default'}>{value}</Tag>;
const handle=async(fn,load)=>{try{await fn();message.success('操作成功');await load()}catch(e){message.error(e.message)}};
function Cards({refreshKey}){
 const {data,loading,load}=useRemote(['/operation-cards','/equipment']);const cards=data['/operation-cards']||[],equipment=data['/equipment']||[];
 const [current,setCurrent]=useState(null),[modal,setModal]=useState(''),[form]=Form.useForm(),[editRecipe,setEditRecipe]=useState(null),[json,setJson]=useState('{}');
 useEffect(()=>{if(refreshKey)load()},[refreshKey]);const rows=cards.flatMap(c=>c.versions.map(v=>({...v,code:c.code,name:c.name,card_id:c.id,card_name:c.name})));const selected=rows.find(r=>r.id===current?.id)||current;
 const open=(mode,initial={})=>{setModal(mode);form.resetFields();form.setFieldsValue(initial)};
 const submit=async v=>{let p;
   if(modal==='newCard')p=api.post('/operation-cards',v);
   if(modal==='newVersion')p=api.post(`/operation-cards/${selected.card_id}/versions`,v);
   if(modal==='clone')p=api.post(`/card-versions/${selected.id}/clone`,{version:v.version});
   if(modal==='editVersion')p=api.put(`/card-versions/${selected.id}`,v);
   if(modal==='newRecipe')p=api.post('/recipes',{card_version_id:selected.id,name:v.name,version:v.version||'1.0',equipment_id:v.equipment_id||null,chamber:v.chamber||'',parameters:JSON.parse(json)});
   if(modal==='newInspection')p=api.post('/inspection-plans',{...v,card_version_id:selected.id,equipment_id:v.equipment_id||null});
   if(modal==='editRecipe')p=api.put(`/recipes/${editRecipe.id}`,{...editRecipe,parameters:JSON.parse(json)});
   if(modal==='newCard' && !v.code)p=Promise.reject(new Error('Card Code 必填'));
   await handle(()=>p,load);setModal('')
 };
 const cols=[{title:'Card Code',dataIndex:'code',render:v=><span className="cardcode">{v}</span>},{title:'Operation Card',dataIndex:'name'},{title:'Version',dataIndex:'version'},{title:'Status',dataIndex:'status',render:v=><Status value={v}/>},{title:'Recipe',render:(_,r)=>r.recipes.map(x=>x.name).join(', ')||'—'},{title:'Inspection',render:(_,r)=>r.inspections.map(x=>x.name).join(', ')||'—'},{title:'Actions',render:(_,r)=><Button size="small" onClick={()=>setCurrent(r)}>详情</Button>}];
 return <><Space style={{marginBottom:18}}><Button icon={<PlusOutlined/>} type="primary" onClick={()=>open('newCard')}>创建工序卡</Button><Button icon={<ReloadOutlined/>} onClick={load}>刷新</Button></Space>
 <Table loading={loading} dataSource={rows} rowKey="id" columns={cols} pagination={{pageSize:10}}/>
 <Card title="工序卡库（独立主数据）" size="small"><Typography.Text type="secondary">卡版本是不可变的制造参数快照；产品工序只引用已发布版本的 ID。创建新版本不会修改旧产品流程。</Typography.Text></Card>
 <Drawer width={620} title={`${selected?.code||''} — ${selected?.version||''}`} open={!!selected&&!modal} onClose={()=>setCurrent(null)} extra={<Space><Button onClick={()=>open('clone')}>复制新版本</Button><Button onClick={()=>open('newVersion')}>空白版本</Button></Space>}>
  {selected&&<><Descriptions column={2} bordered size="small" items={[{key:'v',label:'Version',children:selected.version},{key:'s',label:'Status',children:<Status value={selected.status}/>},{key:'m',label:'Material',children:selected.material_type||'—'},{key:'sub',label:'Substrate',children:selected.substrate_type||'—'},
{ key: 'owner', label: '工序责任人', children: selected.responsible_person || '—' },
{ key: 'equipment', label: '设备', children: equipment.find(e => e.id === selected.equipment_id)?.name || '—' },
{ key: 'tooling', label: '工装要求', span: 2, children: selected.tooling_requirement || '—' },
{ key: 'drawing', label: '图纸', children: [selected.drawing_number, selected.drawing_version ? `Rev.${selected.drawing_version}` : ''].filter(Boolean).join(' / ') || '—' },
{ key: 'drawingUrl', label: '图纸地址', span: 2, children: selected.drawing_url || '—' },
{ key: 'sop', label: 'SOP', children: [selected.sop_number, selected.sop_version ? `Rev.${selected.sop_version}` : ''].filter(Boolean).join(' / ') || '—' },
{ key: 'sopUrl', label: 'SOP 地址', span: 2, children: selected.sop_url || '—' },
{key:'film',label:'Film',span:2,children:selected.film_requirement||'—'}]}/>
  <Space style={{marginTop:16,marginBottom:12}}><Button disabled={selected.status!=='Draft'} onClick={()=>open('editVersion',selected)}>编辑参数要求</Button><Button disabled={selected.status!=='Draft'} type="primary" icon={<CheckCircleOutlined/>} onClick={()=>handle(()=>api.post(`/card-versions/${selected.id}/release`),load)}>发布版本</Button></Space>
  <Divider>Recipes</Divider>{selected.recipes.map(r=><Card key={r.id} size="small" style={{marginBottom:8}} title={r.name+' / '+r.version} extra={<Button size="small" disabled={selected.status!=='Draft'} onClick={()=>{setEditRecipe(r);setJson(JSON.stringify(r.parameters,null,2));open('editRecipe')}}>编辑</Button>}><pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(r.parameters,null,2)}</pre><div className="small">Equipment ID: {r.equipment_id??'—'} · Chamber: {r.chamber||'—'}</div></Card>)}
  <Button disabled={selected.status!=='Draft'} onClick={()=>{setJson('{}');open('newRecipe')}}>添加 Recipe</Button>
  <Divider>Inspection Plans</Divider>{selected.inspections.map(i=><Card key={i.id} size="small" style={{marginBottom:8}} title={i.name}><div>{i.inspection_type} · Target {i.target} {i.unit} · LSL {i.lsl} / USL {i.usl}</div><div className="small">{i.sampling_rule} · {i.frequency}</div></Card>)}
  <Button disabled={selected.status!=='Draft'} onClick={()=>open('newInspection')}>添加 Inspection Plan</Button></>}
 </Drawer>
 <Modal title={{newCard:'创建独立工序卡',newVersion:'创建空白版本',clone:'复制为新 Draft 版本',editVersion:'编辑 Draft 参数',newRecipe:'新增 Recipe',editRecipe:'编辑 Recipe',newInspection:'新增检测计划'}[modal]} open={!!modal} onCancel={()=>setModal('')} onOk={()=>form.submit()} destroyOnHidden>
 <Form form={form} layout="vertical" onFinish={submit}>
 {modal==='newCard'&&<><Form.Item name="code" label="Card Code" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="name" label="Name" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="description" label="Description"><Input.TextArea/></Form.Item></>}
 {['newVersion','clone'].includes(modal)&&<Form.Item label="New Version" name="version" rules={[{required:true}]}><Input placeholder="2.0"/></Form.Item>}
 {['newVersion','editVersion'].includes(modal)&&<><Form.Item label="Description" name="description"><Input/></Form.Item><Form.Item name="material_type" label="Material Type"><Input/></Form.Item><Form.Item name="substrate_type" label="Substrate Type"><Input/></Form.Item><Form.Item name="film_requirement" label="Film Requirement"><Input/></Form.Item>
<Form.Item name="responsible_person" label="工序责任人">
  <Input placeholder="姓名或工号"/>
</Form.Item>

<Form.Item name="equipment_id" label="设备">
  <Select
    allowClear
    showSearch
    optionFilterProp="label"
    options={equipment.map(e => ({
      value: e.id,
      label: e.name
    }))}
    placeholder="选择设备"
  />
</Form.Item>

<Form.Item name="tooling_requirement" label="工装要求">
  <Input.TextArea rows={2}/>
</Form.Item>

<Divider>图纸信息</Divider>

<Form.Item name="drawing_number" label="图纸编号">
  <Input/>
</Form.Item>

<Form.Item name="drawing_version" label="图纸版本">
  <Input/>
</Form.Item>

<Form.Item name="drawing_url" label="图纸地址">
  <Input placeholder="内部文档系统链接或文件地址"/>
</Form.Item>

<Divider>SOP 信息</Divider>

<Form.Item name="sop_number" label="SOP 编号">
  <Input/>
</Form.Item>

<Form.Item name="sop_version" label="SOP 版本">
  <Input/>
</Form.Item>

<Form.Item name="sop_url" label="SOP 地址">
  <Input placeholder="内部文档系统链接或文件地址"/>
</Form.Item>
</>}
 {['newRecipe','editRecipe'].includes(modal)&&<>{modal==='newRecipe'&&<><Form.Item name="name" label="Recipe Name" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="version" initialValue="1.0" label="Recipe Version"><Input/></Form.Item><Form.Item name="equipment_id" label="Equipment"><Select allowClear options={equipment.map(e=>({value:e.id,label:e.name}))}/></Form.Item><Form.Item name="chamber" label="Chamber"><Input/></Form.Item></>}<div>Parameters (JSON)</div><Input.TextArea rows={7} value={json} onChange={e=>setJson(e.target.value)}/></>}
 {modal==='newInspection'&&<><Form.Item name="name" label="Plan Name" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="inspection_type" label="Inspection Type"><Input/></Form.Item><Form.Item name="equipment_id" label="Equipment"><Select allowClear options={equipment.map(e=>({label:e.name,value:e.id}))}/></Form.Item><Form.Item name="target" label="Target"><InputNumber style={{width:'100%'}}/></Form.Item><Form.Item name="lsl" label="LSL"><InputNumber style={{width:'100%'}}/></Form.Item><Form.Item name="usl" label="USL"><InputNumber style={{width:'100%'}}/></Form.Item><Form.Item name="unit" label="Unit" initialValue="nm"><Input/></Form.Item><Form.Item name="sampling_rule" label="Sampling Rule"><Input/></Form.Item><Form.Item name="frequency" label="Frequency"><Input/></Form.Item></>}
 </Form></Modal></>;
}
function ProductManagement({selectFlow}){
 const {data,loading,load}=useRemote(['/products']);const products=data['/products']||[],[modal,setModal]=useState(''),[current,setCurrent]=useState(null),[form]=Form.useForm();const open=(type,item=null)=>{setModal(type);setCurrent(item);form.resetFields()};
 const submit=async values=>{const f=modal==='product'?()=>api.post('/products',values):modal==='revision'?()=>api.post('/revisions',{...values,product_id:current.id}):modal==='clone'?()=>api.post(`/revisions/${current.id}/clone`,values):()=>api.post('/flows',{...values,revision_id:current.id});await handle(f,load);setModal('')};
 const tree=products.map(p=>({title:<Space><strong>{p.name}</strong><Tag>{p.family}</Tag><Button size="small" onClick={e=>{e.stopPropagation();open('revision',p)}}>+ Revision</Button></Space>,key:`p-${p.id}`,children:p.revisions.map(r=>({title:<Space>Revision {r.version}<Status value={r.status}/><Button size="small" onClick={e=>{e.stopPropagation();open('flow',r)}}>+ Flow</Button><Button size="small" icon={<CopyOutlined/>} onClick={e=>{e.stopPropagation();open('clone',r)}}>Clone</Button><Button size="small" disabled={r.status!=='Draft'} onClick={e=>{e.stopPropagation();handle(()=>api.post(`/revisions/${r.id}/release`),load)}}>Release</Button></Space>,key:`r-${r.id}`,children:r.flows.map(f=>({title:<a onClick={()=>selectFlow(f.id)}>{f.name} → Open Designer</a>,key:`f-${f.id}`}))}))}));
 return <><Space style={{marginBottom:20}}><Button type="primary" icon={<PlusOutlined/>} onClick={()=>open('product')}>创建 Product</Button><Button icon={<ReloadOutlined/>} onClick={load}>刷新</Button></Space><Card loading={loading} title="Product / Revision / Flow" extra={<span className="sub">点击流程打开设计器</span>}>{tree.length?<Tree defaultExpandAll showLine treeData={tree} selectable={false}/>:<Empty/>}</Card>
 <Alert style={{marginTop:16}} type="info" showIcon message="产品版本一旦 Released，流程及 Step 绑定不能再修改；使用 Clone 生成新 Revision。"/>
 <Modal open={!!modal} title={{product:'新增 Product',revision:'新增 Revision',clone:'克隆 Revision + Flow',flow:'新增 Flow'}[modal]} onCancel={()=>setModal('')} onOk={()=>form.submit()} destroyOnHidden><Form form={form} layout="vertical" onFinish={submit}>{modal==='product'?<><Form.Item name="name" label="Product Name" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="family" label="Family" initialValue="Reticle"><Input/></Form.Item><Form.Item name="description" label="Description"><Input/></Form.Item></>:modal==='flow'?<Form.Item name="name" label="Flow Name" rules={[{required:true}]}><Input/></Form.Item>:<Form.Item name="version" label="Revision Version" rules={[{required:true}]}><Input placeholder="2.0"/></Form.Item>}</Form></Modal></>;
}
function Designer({initialFlow}){
 const {data,load}=useRemote(['/flows','/operation-cards']);
 const flows=data['/flows']||[];
 const cards=data['/operation-cards']||[];

 const [flowId,setFlowId]=useState(null);
 const [modal,setModal]=useState('');
 const [current,setCurrent]=useState(null);
 const [form]=Form.useForm();

 useEffect(()=>{
   if(initialFlow)setFlowId(initialFlow);
 },[initialFlow]);

 useEffect(()=>{
   if(!flowId&&flows.length)setFlowId(flows[0].id);
 },[flows.length]);

 const flow=flows.find(f=>f.id===flowId);

 const refOptions=cards.flatMap(c=>
   c.versions
    .filter(v=>v.status==='Released')
    .map(v=>({
      value:v.id,
      label:`${c.code} / V${v.version} (${c.name})`
    }))
 );

 /*
  * 打开编辑窗口
  *
  * group   : 新增 / 编辑 Operation Group
  * addstep  : 新增 Operation Step
  * step     : 编辑 Operation Step
  */
 const show=(type,item=null)=>{
   setModal(type);
   setCurrent(item);
   form.resetFields();

   if(type==='group' && item){
     form.setFieldsValue({
       name:item.name,
       sequence:item.sequence
     });
   }

   if(type==='addstep'){
     form.setFieldsValue({
       name:'',
       sequence:item?.steps?.length
         ? Math.max(...item.steps.map(s=>s.sequence))+10
         : 10
     });
   }

   if(type==='step' && item){
     form.setFieldsValue({
       name:item.name,
       sequence:item.sequence,
       card_version_id:item.card_version_id
     });
   }
 };

 /*
  * 保存
  */
 const submit=async values=>{
   let work;

   if(modal==='group'){
     // 新增 Group
     work=()=>api.post('/groups',{
       ...values,
       flow_id:flow.id
     });
   }

   else if(modal==='editGroup'){
     // 修改 Group
     work=()=>api.put(`/groups/${current.id}`,{
       flow_id:current.flow_id || flow.id,
       name:values.name,
       sequence:values.sequence
     });
   }

   else if(modal==='addstep'){
     // 新增 Step
     work=()=>api.post('/steps',{
       ...values,
       group_id:current.id
     });
   }

   else if(modal==='step'){
     // 修改 Step
     work=()=>api.put(`/steps/${current.id}`,values);
   }

   await handle(work,load);
   setModal('');
   setCurrent(null);
 };

 /*
  * 按 Sequence 排序。
  *
  * 这样修改 Group Sequence 后，
  * 页面会自动按照新的 Sequence 展示。
  */
 const sortedGroups=[...(flow?.groups||[])].sort(
   (a,b)=>a.sequence-b.sequence
 );

 return <>
   <Space style={{marginBottom:18}}>
     <Select
       style={{width:360}}
       placeholder="Select Process Flow"
       value={flowId}
       onChange={setFlowId}
       options={flows.map(f=>({
         label:f.name+' · Flow #'+f.id,
         value:f.id
       }))}
     />

     <Button
       icon={<ReloadOutlined/>}
       onClick={load}
     >
       刷新
     </Button>

     <Button
       type="primary"
       disabled={!flow}
       onClick={()=>show('group')}
     >
       添加 Operation Group
     </Button>
   </Space>

   {!flow ? (
     <Empty description="请先在 Product Management 创建 Flow"/>
   ) : (
     <>
       <div className="flow-term">START</div>
       <div className="connector"/>

<Collapse
  defaultActiveKey={sortedGroups.map(g => String(g.id))}
  items={sortedGroups.map(g => {

    const sortedSteps = [...(g.steps || [])].sort(
      (a, b) => a.sequence - b.sequence
    );

    return {
      key: String(g.id),

      label: (
        <Space>
          <strong>
            GROUP {g.sequence}: {g.name}
          </strong>
          <Tag>
            {sortedSteps.length} Steps
          </Tag>
        </Space>
      ),

      extra: (
        <Space onClick={e => e.stopPropagation()}>

          <Button
            size="small"
            onClick={() => show('editGroup', g)}
          >
            编辑
          </Button>

          <Button
            size="small"
            onClick={() => show('addstep', g)}
          >
            + Step
          </Button>

        </Space>
      ),

      children: (
        <div>

          {sortedSteps.length === 0 ? (
            <Empty
              description="该 Group 暂无 Step"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          ) : (
            sortedSteps.map(s => (
              <div
                key={s.id}
                className="flow-node"
                style={{ marginBottom: 10 }}
              >

                <Space
                  style={{
                    justifyContent: 'space-between',
                    width: '100%'
                  }}
                >

                  <div>

                    <strong>
                      STEP {s.sequence}: {s.name}
                    </strong>

                    <div className="small">

                      Operation Card Reference:

                      <span className="cardcode">

                        {s.card_code || 'Unbound'}

                        {' '}

                        {s.card_version
                          ? 'V' + s.card_version
                          : ''
                        }

                      </span>

                    </div>

                  </div>

                  <Button
                    size="small"
                    onClick={() => show('step', s)}
                  >
                    绑定 / 修改
                  </Button>

                </Space>

              </div>
            ))
          )}

        </div>
      )
    };
  })}
/>

       <div className="flow-term">END</div>
     </>
   )}

   {/* Group / Step Modal */}
   <Modal
     open={!!modal}
     title={{
       group:'新增 Operation Group',
       editGroup:'编辑 Operation Group',
       addstep:'新增 Operation Step',
       step:'修改 Step / 引用工序卡'
     }[modal]}
     onCancel={()=>{
       setModal('');
       setCurrent(null);
     }}
     onOk={()=>form.submit()}
     destroyOnHidden
   >

     <Form
       form={form}
       layout="vertical"
       onFinish={submit}
     >

       <Form.Item
         name="name"
         label="Name"
         rules={[
           {
             required:true,
             message:'请输入名称'
           }
         ]}
       >
         <Input/>
       </Form.Item>

       <Form.Item
         name="sequence"
         label="Sequence"
         rules={[
           {
             required:true,
             message:'请输入 Sequence'
           }
         ]}
       >
         <InputNumber
           min={1}
           style={{width:'100%'}}
         />
       </Form.Item>

       {/* Step 才显示 Operation Card */}
       {modal!=='group' && modal!=='editGroup' && (
         <Form.Item
           name="card_version_id"
           label="Released Operation Card Version"
         >
           <Select
             allowClear
             showSearch
             optionFilterProp="label"
             options={refOptions}
             placeholder="选择工序卡版本"
           />
         </Form.Item>
       )}

     </Form>

   </Modal>
 </>;
}

function Dashboard({navigate}){const {data}=useRemote(['/products','/operation-cards','/flows']);const p=data['/products']||[],c=data['/operation-cards']||[],f=data['/flows']||[];return <><Row gutter={16}>{[[p.length,'Products'],[p.reduce((n,x)=>n+x.revisions.length,0),'Revisions'],[c.length,'Operation Cards'],[f.length,'Process Flows']].map(([n,label])=><Col xs={12} md={6} key={label}><Card><Statistic title={label} value={n}/></Card></Col>)}</Row><Card title="Operation Card — 独立主数据设计" style={{marginTop:20}}><p>Product → Product Revision → Process Flow → Operation Group → Operation Step → <strong>Operation Card Version</strong></p><p>工序卡由独立 Card Library 管理；同一版本可以被多个产品的 Step 引用。Released 版本不允许覆盖，修改时 Clone Draft，再发布新版本。</p><Space><Button onClick={()=>navigate('cards')}>打开 Operation Card Library</Button><Button type="primary" onClick={()=>navigate('flow')}>打开 Flow Designer</Button></Space></Card><Card style={{marginTop:16}} title="预置 Reticle 制造流程"><p>Cleaning → ZEP520A Coating → EBPG5200 Exposure → Development → Etching → CD SEM</p><p>EBL: 100 kV / 2 nA / 120 µC/cm²；CD: 100 nm ±5 nm。</p></Card></>}
export default function App(){const [page,setPage]=useState('dashboard'),[flowId,setFlowId]=useState(null),[rev,setRev]=useState(0);const labels={dashboard:'MES Sandbox',products:'Product Management',cards:'Operation Card Library',flow:'Process Flow Designer'};
 return <Layout style={{minHeight:'100vh'}}><Sider breakpoint="lg" collapsedWidth="0" width={245} theme="dark"><div className="logo"><DatabaseOutlined style={{marginRight:9}}/> MES Sandbox</div><Menu theme="dark" mode="inline" selectedKeys={[page]} onClick={e=>setPage(e.key)} items={[{key:'dashboard',icon:<AppstoreOutlined/>,label:'Overview'},{key:'products',icon:<DatabaseOutlined/>,label:'Product Management'},{key:'cards',icon:<AppstoreOutlined/>,label:'Operation Card Library'},{key:'flow',icon:<ApartmentOutlined/>,label:'Process Flow Designer'}]}/></Sider><Layout><Header style={{background:'#fff',display:'flex',justifyContent:'space-between',alignItems:'center',padding:'0 26px',borderBottom:'1px solid #e7edf4'}}><h2 className="head-title">{labels[page]}</h2><Tag color="blue">Master Data Validation</Tag></Header><Content style={{margin:'24px',maxWidth:1450}}><div className="pane">{page==='dashboard'?<Dashboard navigate={setPage}/>:page==='products'?<ProductManagement selectFlow={id=>{setFlowId(id);setPage('flow')}}/>:page==='cards'?<Cards refreshKey={rev}/>:<Designer initialFlow={flowId}/>}</div></Content></Layout></Layout>;
}
