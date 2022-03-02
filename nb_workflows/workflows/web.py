# pylint: disable=unused-argument
import asyncio
import pathlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List, Optional

import aiofiles
from nb_workflows.conf import settings
from nb_workflows.utils import (get_query_param, list_workflows, run_async,
                                secure_filename)
from nb_workflows.workflows.core import nb_job_executor
from nb_workflows.workflows.entities import (ExecutionResult, HistoryRequest,
                                             NBTask)
from nb_workflows.workflows.registers import register_history_db
from nb_workflows.workflows.scheduler import (QueueExecutor, SchedulerExecutor,
                                              scheduler_dispatcher)
from redis import Redis
from sanic import Blueprint, Sanic, exceptions
from sanic.response import json
from sanic_ext import openapi
from sanic_jwt import protected

workflows_bp = Blueprint("workflows", url_prefix="workflows")


def _get_scheduler() -> SchedulerExecutor:
    current_app = Sanic.get_app("nb_workflows")
    return current_app.ctx.scheduler


def _get_q_executor() -> QueueExecutor:
    current_app = Sanic.get_app("nb_workflows")
    return current_app.ctx.Q


@dataclass
class JobResponse:
    jobid: str
    workflow: NBTask


@dataclass
class JobDetail:
    jobid: str
    func_name: str
    # workflow: NBTask
    created_at: str


@workflows_bp.listener("before_server_start")
def startserver(current_app, loop):
    _cfg = settings.rq2dict()
    redis = Redis(**_cfg)
    current_app.ctx.rq_redis = redis
    current_app.ctx.scheduler = SchedulerExecutor(redis)
    current_app.ctx.Q = QueueExecutor(redis)
    # current_app.ctx.queue = queue_init(_cfg)


@workflows_bp.post("/notebooks/_run")
@openapi.body({"application/json": NBTask})
@openapi.response(202, {"executionid": str}, "Task executed")
@openapi.response(400, {"msg": str}, "Wrong params")
@protected()
def launch_task(request):
    """
    Prepare and execute a Notebook Workflow Job based on a filename
    This endpoint allows to execution any notebook without restriction.
    The file should exist remotetly but it doesn't need to be
    previously scheduled
    """
    try:
        nb_task = NBTask(**request.json)
    except TypeError:
        return json(dict(msg="wrong params"), 400)

    Q = _get_q_executor()

    job = Q.enqueue_notebook(nb_task)

    return json(dict(executionid=job.id), status=202)


@workflows_bp.get("/notebooks/_files")
@protected()
def list_nb_workflows(request):
    """
    List file workflows
    """
    # pylint: disable=unused-argument

    nb_files = list_workflows()

    return json(nb_files)


@workflows_bp.post("/notebooks/_upload")
@protected()
def upload_notebook(request):
    """
    Upload a notebook file to the server
    """
    # pylint: disable=unused-argument

    nb_files = list_workflows()

    return json(nb_files)


@workflows_bp.post("/_upload")
async def upload_project(request):
    """
    Upload a workflow project
    """
    # pylint: disable=unused-argument

    root = pathlib.Path(settings.BASE_PATH)
    (root / settings.UPLOADS).mkdir(parents=True, exist_ok=True)
    file_body = request.files["file"][0].body
    name = secure_filename(request.files["file"][0].name)

    fp = str(root / settings.UPLOADS / name)
    async with aiofiles.open(fp, "wb") as f:
        await f.write(file_body)

    return json(dict(msg="ok"), 201)


@workflows_bp.get("/rqjobs/<jobid>")
@openapi.parameter("jobid", str, "path")
@protected()
def get_job_result(request, jobid):
    """Get job result from the queue"""
    Q = _get_q_executor()
    job = Q.fetch_job(jobid)
    result = job.result
    if result:
        result = asdict(result)

    return json(
        dict(
            jobid=job.id,
            status=job.get_status(),
            result=result,
            position=job.get_position(),
        )
    )


@workflows_bp.get("/rqjobs/failed")
@protected()
def get_failed_jobs(request):
    """Get jobs failed in RQ"""
    Q = _get_q_executor()

    jobs = Q.get_jobs_ids("failed")

    return json(dict(rows=jobs, total=len(jobs)))


@workflows_bp.delete("/rqjobs/failed")
@openapi.parameter("remove", bool, "query")
@protected()
def delete_failed_jobs(request):
    """Remove failed jobs from the queue"""

    to_remove = get_query_param(request, "remove", False)
    Q = _get_q_executor()

    jobs = Q.remove_jobs("failed", to_remove)

    return json(dict(rows=jobs, total=len(jobs)))


@workflows_bp.get("/rqjobs/running")
@protected()
def get_running_jobs(request):
    """Get jobs Running"""
    Q = _get_q_executor()

    jobs = Q.get_jobs_ids("started")

    return json(dict(rows=jobs, total=len(jobs)))


@workflows_bp.get("/schedule")
@protected()
async def list_schedule(request):
    """List jobs registered in the database"""
    # pylint: disable=unused-argument

    session = request.ctx.session
    scheduler = _get_scheduler()

    async with session.begin():
        result = await scheduler.get_schedule_db(session)

    return json(result)


@workflows_bp.delete("/schedule/<jobid>")
@openapi.parameter("jobid", str, "path")
@protected()
async def schedule_delete(request, jobid):
    """Get a ScheduleJob"""
    # pylint: disable=unused-argument
    scheduler = _get_scheduler()
    session = request.ctx.session
    async with session.begin():
        await scheduler.delete_job(session, jobid)
        await session.commit()

    return json(dict(msg="done"), 200)


@workflows_bp.get("/schedule/rqjobs")
@openapi.response(200, List[JobDetail], "Task Scheduled")
@protected()
def list_scheduled_redis(request):
    """
    List the jobs scheduled in the scheduler
    """
    # pylint: disable=unused-argument

    scheduler = _get_scheduler()
    jobs = scheduler.list_jobs()

    return json(jobs, 200)


@workflows_bp.post("/schedule")
@openapi.body({"application/json": NBTask})
@openapi.response(200, {"msg": str}, "Notebook Workflow already exist")
@openapi.response(201, {"jobid": str}, "Notebook Workflow registered")
@openapi.response(400, {"msg": str}, description="wrong params")
@protected()
async def create_notebook_schedule(request):
    """
    Register a notebook workflow and schedule it
    """
    try:
        nb_task = NBTask(**request.json)
        if not nb_task.schedule:
            return json(dict(msg="schedule information is needed"), 400)
    except TypeError:
        return json(dict(msg="wrong params"), 400)

    session = request.ctx.session
    scheduler = _get_scheduler()

    async with session.begin():
        try:
            rsp = await scheduler.schedule(session, request.json)
        except KeyError:
            return json(dict(msg="notebook workflow already exists"), status=200)

    return json(dict(jobid=rsp), status=201)


@workflows_bp.put("/schedule")
@openapi.body({"application/json": NBTask})
@openapi.response(202, {"jobid": str}, "Notebook Workflow accepted")
@openapi.response(400, {"msg": str}, description="wrong params")
@openapi.response(503, {"msg": str}, description="Error persiting the job")
@protected()
async def update_notebook_schedule(request):
    """
    Register a notebook workflow and schedule it
    """
    try:
        nb_task = NBTask(**request.json)
        if not nb_task.schedule:
            return json(dict(msg="schedule information is needed"), 400)
    except TypeError:
        return json(dict(msg="wrong params"), 400)

    session = request.ctx.session
    scheduler = _get_scheduler()

    async with session.begin():
        try:
            rsp = await scheduler.schedule(session, request.json, update=True)
        except KeyError:
            return json(
                dict(msg="An integrity error persisting the job"), status=503
            )

    return json(dict(jobid=rsp), status=202)


@workflows_bp.get("/schedule/<jobid>")
@openapi.parameter("jobid", str, "path")
@openapi.response(200)
@openapi.response(404, {"msg": str}, description="Job not found")
@protected()
async def schedule_one_job(request, jobid):
    """Delete a job from RQ and DB"""
    # pylint: disable=unused-argument
    scheduler = _get_scheduler()
    session = request.ctx.session
    async with session.begin():
        obj_dict = await scheduler.get_jobid_db(session, jobid)

    if obj_dict:
        return json(obj_dict, 200)
    return json(dict(msg="Not found"), 404)


@workflows_bp.post("/schedule/<jobid>/_run")
@openapi.parameter("jobid", str, "path")
@openapi.response(202, dict(executionid=str), "Execution id of the task")
@protected()
def schedule_run(request, jobid):
    """
    Manually execute a registered schedule task
    """
    Q = _get_q_executor()

    job = Q.enqueue(scheduler_dispatcher, jobid)

    return json(dict(executionid=job.id), status=202)


@workflows_bp.delete("/schedule/rqjobs/_cancel/<jobid>")
@openapi.parameter("jobid", str, "path")
@protected()
async def schedule_cancel(request, jobid):
    """delete a scheduler job from redis"""
    # pylint: disable=unused-argument

    scheduler = _get_scheduler()
    await run_async(scheduler.cancel, jobid)
    return json(dict(msg="done"), 200)


@workflows_bp.delete("/schedule/rqjobs/_cancel_all")
@protected()
async def schedule_cancel_all(request):
    """Cancel all the jobs in the queue"""
    # pylint: disable=unused-argument

    scheduler = _get_scheduler()

    await run_async(scheduler.cancel_all)

    return json(dict(msg="done"), 200)


@workflows_bp.get("/history/<jobid>")
@openapi.parameter("jobid", str, "path")
@openapi.response(200, "Found")
@openapi.response(404, dict(msg=str), "Not Found")
@protected()
async def history_last_job(request, jobid):
    """Get the status of the last job executed"""
    # pylint: disable=unused-argument
    scheduler = _get_scheduler()
    session = request.ctx.session
    async with session.begin():
        h = await scheduler.get_last_history(session, jobid)
        if h:
            return json(asdict(h), 200)

        return json(dict(msg="not found"), 404)


@workflows_bp.post("/history/")
@openapi.body({"application/json": HistoryRequest})
@openapi.response(201, "Created")
@protected()
async def history_create(request):
    """Register a jobexecution"""
    # pylint: disable=unused-argument

    dict_ = request.json
    task = NBTask(**dict_["task"])
    result = ExecutionResult(**dict_["result"])
    session = request.ctx.session
    async with session.begin():
        await register_history_db(session, result, task)
        await session.commit()

    return json(dict(msg="created"), 201)
