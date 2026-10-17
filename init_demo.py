from app.core import *

def seed():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(Product).filter_by(name='CGH Mask').first():
            print('Demo already exists; skipped.');return
        eq={}
        for name,model,kind in [('WetBench-01','Wet Bench','Cleaning'),('Coater-01','Spin Coater','Coating'),('EBPG5200','Raith EBPG5200','EBL'),('Developer-01','Wet Developer','Development'),('Etcher-01','ICP RIE','Etching'),('CD-SEM-01','CD SEM','Metrology')]:
            e=Equipment(name=name,model=model,kind=kind,chambers=['Main']);db.add(e);db.flush();eq[name]=e.id
        specs=[
            ('CLEANING','Cleaning','Quartz substrate cleaning','WetBench-01',{'time':{'value':300,'unit':'s'}},None),
            ('COATING','ZEP520A Coating','Resist coating','Coater-01',{'spin_speed':{'value':5000,'unit':'rpm'},'bake_temperature':{'value':180,'unit':'C'},'bake_time':{'value':120,'unit':'s'}},None),
            ('EBL_100KV','EBPG5200 100kV Exposure','Electron beam lithography','EBPG5200',{'voltage':{'value':100,'unit':'kV'},'beam_current':{'value':2,'unit':'nA'},'dose':{'value':120,'unit':'uC/cm2'}},None),
            ('DEVELOP','Development','Resist development','Developer-01',{'development_time':{'value':60,'unit':'s'}},None),
            ('ETCH','Etching','Chrome pattern transfer','Etcher-01',{'power':{'value':200,'unit':'W'},'time':{'value':90,'unit':'s'}},None),
            ('CD_INSPECT','CD Inspection','CD SEM measurement',None,{},dict(name='CD 100nm',inspection_type='CD SEM',equipment_id=eq['CD-SEM-01'],sampling_rule='1 wafer per lot',target=100,usl=105,lsl=95,unit='nm',frequency='Every Lot')),
        ]
        versions=[]
        for code,name,desc,machine,params,inspection in specs:
            card=OperationCard(code=code,name=name,description=desc);db.add(card);db.flush()
            v=OperationCardVersion(card_id=card.id,version='1.0',status='Draft',material_type='Reticle',substrate_type='6-inch Quartz',film_requirement='Cr 100 nm / ZEP520A resist' if code!='CLEANING' else 'Bare quartz')
            db.add(v);db.flush()
            if machine:db.add(Recipe(card_version_id=v.id,name=name+' Recipe',version='1.0',equipment_id=eq[machine],chamber='Main',parameters=params))
            if inspection:db.add(InspectionPlan(card_version_id=v.id,**inspection))
            db.flush();v.status='Released';versions.append(v.id)
        product=Product(name='CGH Mask',family='Reticle');db.add(product);db.flush()
        rev=ProductRevision(product_id=product.id,version='1.0',status='Draft');db.add(rev);db.flush()
        flow=ProcessFlow(revision_id=rev.id,name='CGH Fabrication Flow');db.add(flow);db.flush()
        groups=[('Preparation',[0,1]),('Lithography',[2,3]),('Pattern Transfer',[4]),('Metrology',[5])]
        for gi,(gname,indices) in enumerate(groups):
            group=OperationGroup(flow_id=flow.id,name=gname,sequence=(gi+1)*10);db.add(group);db.flush()
            for idx in indices:
                name=specs[idx][1];db.add(OperationStep(group_id=group.id,name=name,sequence=(idx+1)*10,card_version_id=versions[idx]))
        db.commit()
        print('Initialized CGH Mask, 6 Released cards, recipe & inspection, flow, 6 steps')
if __name__=='__main__':seed()
