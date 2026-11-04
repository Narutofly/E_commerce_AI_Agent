import hashlib
import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, field_validator
from .store import Store, now, rows, password_ok, audit
from .service import owned, create_ticket, review_ticket, decode_ticket
from .agent import respond


class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


class Application(BaseModel):
    order_id: str = Field(min_length=1,max_length=100)
    kind: Literal['return','exchange']
    reason: str = Field(min_length=2,max_length=2000)
    request_id: str = Field(min_length=8,max_length=100)

    @field_validator('reason')
    @classmethod
    def meaningful(cls,v):
        if len(v.strip())<2:
            raise ValueError('请填写具体原因')
        return v.strip()


class Review(BaseModel):
    status: Literal['approved','rejected','completed']
    opinion: str = Field(min_length=2,max_length=2000)

    @field_validator('opinion')
    @classmethod
    def meaningful(cls,v):
        if len(v.strip())<2:
            raise ValueError('请填写处理意见')
        return v.strip()


class PolicyEdit(BaseModel):
    version: int = Field(ge=1)
    body: str = Field(min_length=5,max_length=10000)

    @field_validator('body')
    @classmethod
    def meaningful(cls,v):
        if len(v.strip()) < 5:
            raise ValueError('政策正文不能为空')
        return v.strip()


class Conversation(BaseModel):
    order_id: str | None = Field(default=None,max_length=100)


class Message(Conversation):
    message: str = Field(min_length=1,max_length=2000)
    mode: Literal['local','llm'] = 'local'

    @field_validator('message')
    @classmethod
    def meaningful(cls,v):
        if not v.strip():
            raise ValueError('问题不能为空')
        return v.strip()


def create_app(path=None):
    store = Store(path or os.getenv('AFTER_SALES_DB',str(Path(__file__).parent/'data'/'after_sales.sqlite3')))

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(title='数码售后 · 单商家演示',lifespan=lifespan)
    app.state.store = store
    security = HTTPBearer(auto_error=False)

    def current(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if credentials is None:
            raise HTTPException(401,'请先登录')
        token = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        with store.db() as db:
            row = db.execute('SELECT u.id,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1 AND u.username IN (\'user\',\'admin\')',(token,now())).fetchone()
            if not row:
                raise HTTPException(401,'会话已失效，请重新登录')
            return dict(row)

    def customer(user=Depends(current)):
        if user['role']!='customer':
            raise HTTPException(403,'仅消费者可操作')
        return user

    def merchant(user=Depends(current)):
        if user['role']!='merchant':
            raise HTTPException(403,'仅商家管理员可操作')
        return user

    prefix='/api/sales'

    @app.get(prefix+'/health')
    def health():
        return {'status':'ok','simulated':True,'rules':{'return':7,'exchange':30},'default_mode':'local'}

    @app.post(prefix+'/auth/login')
    def login(req:Login):
        with store.db(True) as db:
            row = db.execute("SELECT * FROM users WHERE username=? AND active=1 AND username IN ('user','admin')",(req.username,)).fetchone()
            if not row or not password_ok(req.password,row['password']):
                raise HTTPException(401,'用户名或密码错误')
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat()))
            audit(db,row['id'],'auth.login',row['id'],{})
            return {'token':token,'user':{'id':row['id'],'username':row['username'],'role':row['role']}}

    @app.get(prefix+'/auth/me')
    def me(user=Depends(current)):
        return user

    @app.post(prefix+'/auth/logout')
    def logout(user=Depends(current),credentials=Depends(security)):
        with store.db(True) as db:
            db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(credentials.credentials.encode()).hexdigest(),))
        return {'ok':True}

    @app.get(prefix+'/orders')
    def orders(user=Depends(customer)):
        with store.db() as db:
            return rows(db.execute('SELECT * FROM orders WHERE user_id=? ORDER BY id',(user['id'],)))

    @app.get(prefix+'/orders/{oid}')
    def order(oid:str,user=Depends(customer)):
        with store.db() as db:
            return owned(db,'orders',oid,user['id'])

    @app.get(prefix+'/tickets')
    def tickets(user=Depends(current)):
        with store.db() as db:
            result = db.execute('SELECT * FROM tickets ORDER BY created_at DESC') if user['role']=='merchant' else db.execute('SELECT * FROM tickets WHERE user_id=? ORDER BY created_at DESC',(user['id'],))
            return [decode_ticket(t) for t in result.fetchall()]

    @app.get(prefix+'/tickets/{tid}')
    def ticket(tid:str,user=Depends(current)):
        with store.db() as db:
            if user['role']=='customer':
                return decode_ticket(owned(db,'tickets',tid,user['id']))
            row = db.execute('SELECT * FROM tickets WHERE id=?',(tid,)).fetchone()
            if not row:
                raise HTTPException(404,'工单不存在')
            return decode_ticket(row)

    @app.post(prefix+'/tickets')
    def submit(req:Application,user=Depends(customer)):
        return create_ticket(store,user,req)

    @app.post(prefix+'/tickets/{tid}/review')
    def review(tid:str,req:Review,user=Depends(merchant)):
        return review_ticket(store,user,tid,req)

    @app.get(prefix+'/policies')
    def policies(user=Depends(current)):
        with store.db() as db:
            return store.policies(db)

    @app.put(prefix+'/policies/{pid}')
    def edit(pid:str,req:PolicyEdit,user=Depends(merchant)):
        with store.db(True) as db:
            row=db.execute('SELECT * FROM policies WHERE id=?',(pid,)).fetchone()
            if not row:
                raise HTTPException(404,'政策不存在')
            if row['version']!=req.version:
                raise HTTPException(409,'政策已被修改，请刷新并重新编辑')
            version=req.version+1
            db.execute('UPDATE policies SET body=?,version=? WHERE id=?',(req.body,version,pid))
            db.execute('INSERT INTO policy_versions VALUES(?,?,?,?,?)',(pid,version,row['title'],req.body,now()))
            if store.fts:
                db.execute('DELETE FROM policy_fts WHERE id=?',(pid,))
                db.execute('INSERT INTO policy_fts VALUES(?,?,?)',(pid,row['title'],req.body))
            audit(db,user['id'],'policy.update',pid,{'from':req.version,'to':version})
            return dict(db.execute('SELECT * FROM policies WHERE id=?',(pid,)).fetchone())

    @app.get(prefix+'/policies/{pid}/versions')
    def versions(pid:str,user=Depends(merchant)):
        with store.db() as db:
            return rows(db.execute('SELECT * FROM policy_versions WHERE policy_id=? ORDER BY version DESC',(pid,)))

    @app.get(prefix+'/audit')
    def audits(user=Depends(merchant)):
        with store.db() as db:
            return rows(db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 500'))

    @app.get(prefix+'/conversations')
    def conversations(user=Depends(customer)):
        with store.db() as db:
            return rows(db.execute('SELECT * FROM conversations WHERE user_id=? ORDER BY created_at DESC',(user['id'],)))

    @app.post(prefix+'/conversations')
    def new_conversation(req:Conversation,user=Depends(customer)):
        with store.db(True) as db:
            if req.order_id:
                owned(db,'orders',req.order_id,user['id'])
            cid=uuid.uuid4().hex
            db.execute('INSERT INTO conversations VALUES(?,?,?,?)',(cid,user['id'],req.order_id,now()))
            return {'id':cid,'order_id':req.order_id}

    @app.get(prefix+'/conversations/{cid}')
    def conversation(cid:str,user=Depends(customer)):
        with store.db() as db:
            conv=owned(db,'conversations',cid,user['id'])
            conv['messages']=rows(db.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY id',(cid,)))
            return conv

    @app.post(prefix+'/conversations/{cid}/messages')
    async def message(cid:str,req:Message,user=Depends(customer)):
        return await respond(store,user,cid,req)

    return app


app=create_app()
