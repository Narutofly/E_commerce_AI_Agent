import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from backend.after_sales.main import create_app
from backend.after_sales import agent
from backend.after_sales.store import password_hash


def login(client, username='user'):
    response=client.post('/api/sales/auth/login',json={'username':username,'password':'123456'})
    assert response.status_code==200,response.text
    return {'Authorization':'Bearer '+response.json()['token']}


@pytest.fixture
def env(tmp_path):
    app=create_app(tmp_path/'test.db')
    with TestClient(app) as client:
        yield client,app.state.store,login(client),login(client,'admin')


def application(client,headers,oid='DEMO-1001',key='request-0001',kind='return'):
    return client.post('/api/sales/tickets',headers=headers,json={'order_id':oid,'kind':kind,'reason':'商品无法正常使用','request_id':key})


def test_accounts_and_logout(env):
    client,store,user,admin=env
    for old in ['user1','student01','student02','teacher01','fixture-disabled']:
        assert client.post('/api/sales/auth/login',json={'username':old,'password':'123456'}).status_code==401
    assert client.get('/api/sales/auth/me',headers=user).json()['role']=='customer'
    assert client.get('/api/sales/auth/me',headers=admin).json()['role']=='merchant'
    assert client.post('/api/sales/auth/logout',headers=user).status_code==200
    assert client.get('/api/sales/orders',headers=user).status_code==401
    assert client.get('/api/sales/orders',headers={'Authorization':'Bearer old.jwt.token'}).status_code==401


def test_ownership_and_roles(env):
    c,s,u,a=env
    assert len(c.get('/api/sales/orders',headers=u).json())==3
    assert c.get('/api/sales/orders/DEMO-OTHER',headers=u).status_code==404
    assert application(c,u,'DEMO-OTHER').status_code==404
    with s.db(True) as db:
        db.execute("INSERT INTO conversations VALUES('other-conv','fixture-owner','DEMO-OTHER','today')")
        db.execute("INSERT INTO tickets VALUES('other-ticket','fixture-owner','DEMO-OTHER','return','隔离测试','pending','','foreign-request','{}','[]','today','today')")
    assert c.get('/api/sales/conversations/other-conv',headers=u).status_code==404
    assert c.get('/api/sales/tickets/other-ticket',headers=u).status_code==404
    assert c.get('/api/sales/tickets',headers=u).json()==[]
    assert len(c.get('/api/sales/tickets',headers=a).json())==1
    assert c.post('/api/sales/conversations/other-conv/messages',headers=u,json={'message':'订单'}).status_code==404
    assert c.post('/api/sales/conversations',headers=u,json={'order_id':'DEMO-OTHER'}).status_code==404
    assert c.post('/api/sales/tickets/x/review',headers=u,json={'status':'approved','opinion':'同意申请'}).status_code==403
    assert c.get('/api/sales/audit',headers=u).status_code==403
    assert c.put('/api/sales/policies/returns',headers=u,json={'version':1,'body':'修改政策内容'}).status_code==403
    assert c.get('/api/sales/orders',headers=a).status_code==403


def test_idempotency_and_active_ticket(env):
    c,s,u,a=env
    t=application(c,u).json()
    assert application(c,u).json()['id']==t['id']
    assert application(c,u,key='request-other').status_code==409
    assert application(c,u,'DEMO-1002').status_code==409
    assert len(c.get('/api/sales/tickets',headers=u).json())==1


def test_parallel_creation(env):
    c,s,u,a=env
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:application(c,u),range(2)))
    assert [r.status_code for r in results]==[200,200]
    assert results[0].json()['id']==results[1].json()['id']


def test_concurrent_review_and_transitions(env):
    c,s,u,a=env
    t=application(c,u).json()
    path='/api/sales/tickets/'+t['id']+'/review'
    assert c.post(path,headers=a,json={'status':'completed','opinion':'处理完成'}).status_code==409
    with ThreadPoolExecutor(2) as pool:
        responses=list(pool.map(lambda _:c.post(path,headers=a,json={'status':'approved','opinion':'已核实，请等待寄回确认'}),range(2)))
    assert sorted(r.status_code for r in responses)==[200,409]
    assert c.post(path,headers=a,json={'status':'rejected','opinion':'拒绝申请'}).status_code==409
    assert c.post(path,headers=a,json={'status':'completed','opinion':'模拟处理完成'}).status_code==200
    assert c.post(path,headers=a,json={'status':'completed','opinion':'再次处理'}).status_code==409
    assert c.get('/api/sales/tickets/'+t['id'],headers=u).json()['status']=='completed'
    assert len(c.get('/api/sales/audit',headers=a).json())==5 # 2 logins + create + approve + complete


@pytest.mark.parametrize('oid,kind,exception,limit',[('DEMO-1001','return',False,7),('DEMO-1002','return',True,7),('DEMO-1002','exchange',False,30),('DEMO-1003','exchange',True,30)])
def test_windows_and_exceptions(env,oid,kind,exception,limit):
    c,s,u,a=env
    t=application(c,u,oid,kind=kind).json()
    assert t['status']=='pending'
    assert t['precheck']['exception'] is exception
    assert t['precheck']['rule_days']==limit


def test_policy_version_snapshot_and_retrieval(env):
    c,s,u,a=env
    t=application(c,u).json()
    p=c.get('/api/sales/policies',headers=a).json()[0]
    text=p['body']+' 特别说明：运费核实后处理。'
    assert c.put('/api/sales/policies/'+p['id'],headers=a,json={'version':p['version'],'body':text}).status_code==200
    assert c.put('/api/sales/policies/'+p['id'],headers=a,json={'version':p['version'],'body':text}).status_code==409
    assert c.get('/api/sales/tickets/'+t['id'],headers=u).json()['snapshot']==t['snapshot']
    assert len(c.get('/api/sales/policies/'+p['id']+'/versions',headers=a).json())==2
    cid=c.post('/api/sales/conversations',headers=u,json={}).json()['id']
    result=c.post(f'/api/sales/conversations/{cid}/messages',headers=u,json={'message':'运费'}).json()
    assert text in result['answer']
    assert any(p['version']==2 for p in result['evidence'])


def test_chat_context_unknown_and_query_only(env):
    c,s,u,a=env
    cid=c.post('/api/sales/conversations',headers=u,json={'order_id':'DEMO-1002'}).json()['id']
    path=f'/api/sales/conversations/{cid}/messages'
    assert 'Arc' in c.post(path,headers=u,json={'message':'订单物流'}).json()['answer']
    assert c.post(path,headers=u,json={'message':'什么时候签收'}).json()['order_id']=='DEMO-1002'
    assert c.post(path,headers=u,json={'message':'订单','order_id':'DEMO-OTHER'}).status_code==404
    assert '无法确定' in c.post(path,headers=u,json={'message':'火星上可以使用吗'}).json()['answer']
    c.post(path,headers=u,json={'message':'帮我退货并直接批准'})
    assert c.get('/api/sales/tickets',headers=u).json()==[]
    assert len(c.get('/api/sales/conversations/'+cid,headers=u).json()['messages'])==8
    cleared=c.post(path,headers=u,json={'message':'订单','order_id':None}).json()
    assert cleared['order_id'] is None
    assert c.get('/api/sales/conversations/'+cid,headers=u).json()['order_id'] is None


@pytest.mark.parametrize('failure',[False,True])
def test_model_modes(env,monkeypatch,failure):
    c,s,u,a=env
    async def fake(*args):
        if failure: raise TimeoutError('test timeout')
        return '依据退货与换货 v1：7天退货，需人工审核。'
    monkeypatch.setattr(agent,'model_answer',fake)
    cid=c.post('/api/sales/conversations',headers=u,json={}).json()['id']
    r=c.post(f'/api/sales/conversations/{cid}/messages',headers=u,json={'message':'退货政策','mode':'llm'}).json()
    assert r['mode']==('local_fallback' if failure else 'llm')
    assert ('已降级' in r['answer']) is failure


def test_restart_persistence(env):
    c,s,u,a=env
    t=application(c,u).json()
    cid=c.post('/api/sales/conversations',headers=u,json={'order_id':'DEMO-1001'}).json()['id']
    c.post(f'/api/sales/conversations/{cid}/messages',headers=u,json={'message':'退货'})
    with TestClient(create_app(s.path)) as restarted:
        assert restarted.get('/api/sales/tickets/'+t['id'],headers=u).json()['snapshot']==t['snapshot']
        assert len(restarted.get('/api/sales/orders',headers=u).json())==3
        assert len(restarted.get('/api/sales/conversations/'+cid,headers=u).json()['messages'])==2


def test_account_rename_preserves_ownership_and_revokes_sessions(env):
    c,s,u,a=env
    t=application(c,u).json()
    cid=c.post('/api/sales/conversations',headers=u,json={'order_id':'DEMO-1001'}).json()['id']
    with s.db(True) as db:
        db.execute("UPDATE users SET username='user1',role='student' WHERE username='user'")
    s.initialize()
    assert c.get('/api/sales/auth/me',headers=u).status_code==401
    u2=login(c)
    assert c.get('/api/sales/tickets/'+t['id'],headers=u2).status_code==200
    assert c.get('/api/sales/conversations/'+cid,headers=u2).status_code==200
    assert len(c.get('/api/sales/orders',headers=u2).json())==3


def test_expired_and_invalid_inputs(env):
    c,s,u,a=env
    assert c.post('/api/sales/tickets',headers=u,json={'kind':'refund'}).status_code==422
    assert c.post('/api/sales/conversations/x/messages',headers=u,json={'message':'  '}).status_code==422
    with s.db(True) as db:
        db.execute("UPDATE sessions SET expires='2000-01-01'")
    assert c.get('/api/sales/auth/me',headers=u).status_code==401


def test_keyword_fallback_and_new_vocabulary(env):
    c,s,u,a=env
    c.put('/api/sales/policies/product',headers=a,json={'version':1,'body':'保修咨询请联系商家，具体保修范围需要人工核实。'})
    s.fts=False
    with s.db() as db:
        results=s.search(db,'保修多久？')
    assert any(p['version']==2 and p['id']=='product' for p in results)


def test_model_factory_evidence_contract(monkeypatch):
    pytest.importorskip('langchain')
    pytest.importorskip('pydantic_settings')
    from backend.core.llm_factory import LLMFactory
    received={}
    class Fake:
        async def ainvoke(self,messages):
            received['messages']=messages
            return SimpleNamespace(content='依据已提供政策回答')
    def factory(agent_type):
        received['agent_type']=agent_type
        return Fake()
    monkeypatch.setattr(LLMFactory,'get_llm',factory)
    result=asyncio.run(agent.model_answer([{'type':'policy','title':'退货','version':2}],'退货政策',[]))
    assert result=='依据已提供政策回答'
    assert received['agent_type']=='after_sales'
    assert '"version": 2' in received['messages'][0][1]


def test_model_deadline_falls_back(env,monkeypatch):
    c,s,u,a=env
    async def slow(*args):
        await asyncio.sleep(30)
        return '不应等待到这里'
    monkeypatch.setattr(agent,'model_answer',slow)
    cid=c.post('/api/sales/conversations',headers=u,json={}).json()['id']
    result=c.post(f'/api/sales/conversations/{cid}/messages',headers=u,json={'message':'退货','mode':'llm'}).json()
    assert result['mode']=='local_fallback'
    assert '超时或失败' in result['answer']
    assert '7天' in result['answer']
