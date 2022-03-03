from contextvars import ContextVar

import aioredis
from redis import Redis
from sanic import Sanic
from sanic.response import json
from sanic_ext import Extend
from sanic_jwt import Initialize

from nb_workflows.auth import users
from nb_workflows.conf import settings
from nb_workflows.db.nosync import AsyncSQL

app = Sanic("nb_workflows")
Initialize(
    app,
    authenticate=users.authenticate_web,
    secret=settings.SECRET_KEY,
    refresh_token_enabled=True,
    retrieve_refresh_token=users.retrieve_refresh_token,
    store_refresh_token=users.store_refresh_token,
    retrieve_user=users.retrieve_user,
)


# app.blueprint(workflows_bp)

app.config.CORS_ORIGINS = "*"
Extend(app)
app.ext.openapi.add_security_scheme(
    "token",
    "http",
    scheme="bearer",
    bearer_format="JWT",
)
app.ext.openapi.secured()
app.ext.openapi.secured("token")

db = AsyncSQL(settings.ASQL)
_base_model_session_ctx = ContextVar("session")


def _parse_page_limit(request, def_pg="1", def_lt="100"):
    strpage = request.args.get("page", [def_pg])
    strlimit = request.args.get("limit", [def_lt])
    page = int(strpage[0])
    limit = int(strlimit[0])

    return page, limit


@app.listener("before_server_start")
async def startserver(current_app, loop):
    """Initialization of the redis and sqldb clients"""
    current_app.ctx.web_redis = aioredis.from_url(
        settings.WEB_REDIS, decode_responses=True
    )

    _cfg = settings.rq2dict()
    redis = Redis(**_cfg)
    current_app.ctx.rq_redis = redis

    current_app.ctx.db = db
    await current_app.ctx.db.init()


@app.listener("after_server_stop")
async def shutdown(current_app, loop):
    await current_app.ctx.db.engine.dispose()
    # await current_app.ctx.redis.close()


@app.middleware("request")
async def inject_session(request):
    current_app = Sanic.get_app("nb_workflows")
    request.ctx.session = app.ctx.db.sessionmaker()
    request.ctx.session_ctx_token = _base_model_session_ctx.set(
        request.ctx.session
    )
    request.ctx.web_redis = current_app.ctx.web_redis

    request.ctx.dbconn = db.engine


@app.middleware("response")
async def close_session(request, response):
    if hasattr(request.ctx, "session_ctx_token"):
        _base_model_session_ctx.reset(request.ctx.session_ctx_token)
        await request.ctx.session.close()


@app.get("/status")
async def status_handler(request):
    return json(dict(msg="We are ok"))
