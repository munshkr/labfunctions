# pylint: disable=unused-argument
import pathlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List, Optional

from nb_workflows.core.entities import (NBTask, ScheduleData, WorkflowData,
                                        WorkflowsList)
from nb_workflows.core.managers import workflows
from nb_workflows.core.scheduler import SchedulerExecutor
from nb_workflows.utils import (get_query_param, parse_page_limit, run_async,
                                secure_filename)
from sanic import Blueprint, Sanic
from sanic.response import json
from sanic_ext import openapi
from sanic_jwt import protected

workflows_bp = Blueprint("workflows", url_prefix="workflows")


def _get_scheduler(qname="default") -> SchedulerExecutor:

    current_app = Sanic.get_app("nb_workflows")
    r = current_app.ctx.rq_redis
    return SchedulerExecutor(r)


# @workflows_bp.post("/<projectid>/notebooks/_run")
# @openapi.body({"application/json": NBTask})
# @openapi.parameter("projectid", str, "path")
# @openapi.response(202, {"executionid": str}, "Task executed")
# @openapi.response(400, {"msg": str}, "Wrong params")
# @protected()
# def launch_task(request, projectid):
#     """
#     Prepare and execute a Notebook Workflow Job based on a filename
#     This endpoint allows to execution any notebook without restriction.
#     The file should exist remotetly but it doesn't need to be
#     previously scheduled
#     """
#     try:
#         nb_task = NBTask(**request.json)
#     except TypeError:
#         return json(dict(msg="wrong params"), 400)
#
#     Q = _get_q_executor()
#
#     job = Q.enqueue_notebook(nb_task)
#
#     return json(dict(executionid=job.id), status=202)


@workflows_bp.get("/<projectid>/notebooks/_files")
@openapi.parameter("projectid", str, "path")
@protected()
def list_nb_workflows(request, projectid):
    """
    List file workflows
    """
    # pylint: disable=unused-argument

    # nb_files = list_workflows()
    nb_files = []

    return json(nb_files)


@workflows_bp.post("/<projectid>/notebooks/_upload")
@openapi.parameter("projectid", str, "path")
@protected()
def upload_notebook(request, projectid):
    """
    Upload a notebook file to the server
    """
    # pylint: disable=unused-argument

    nb_files = []

    return json(nb_files)


@workflows_bp.get("/<projectid>")
@openapi.parameter("projectid", str, "path")
@openapi.response(200, WorkflowsList, "Notebook Workflow already exist")
@protected()
async def workflows_list(request, projectid):
    """List workflows registered in the database"""
    # pylint: disable=unused-argument

    session = request.ctx.session

    result = await workflows.get_all(session, projectid)
    data = [asdict(r) for r in result]

    return json(dict(rows=data), 200)


@workflows_bp.delete("/<projectid>/<jobid>")
@openapi.parameter("projectid", str, "path")
@openapi.parameter("jobid", str, "path")
@protected()
async def workflow_delete(request, projectid, jobid):
    """Delete from db and queue a workflow"""
    # pylint: disable=unused-argument
    session = request.ctx.session
    scheduler = _get_scheduler()
    async with session.begin():
        await scheduler.delete_workflow(session, projectid, jobid)
        await session.commit()

    return json(dict(msg="done"), 200)


@workflows_bp.post("/<projectid>")
@openapi.body({"application/json": NBTask})
@openapi.parameter("projectid", str, "path")
@openapi.response(200, {"msg": str}, "Notebook Workflow already exist")
@openapi.response(201, {"jobid": str}, "Notebook Workflow registered")
@openapi.response(400, {"msg": str}, description="wrong params")
@openapi.response(404, {"msg": str}, description="project not found")
@protected()
async def workflow_create(request, projectid):
    """
    Register a notebook workflow and schedule it
    """
    breakpoint()
    try:
        nb_task = NBTask(**request.json)
        if nb_task.schedule:
            # return json(dict(msg="schedule information is needed"), 400)
            nb_task.schedule = ScheduleData(**request.json["schedule"])
    except TypeError:
        return json(dict(msg="wrong params"), 400)

    session = request.ctx.session

    async with session.begin():
        try:
            jobid = await workflows.register(session, projectid, nb_task)
        except KeyError as e:
            print(e)
            return json(dict(msg="workflow already exist"), status=200)
        except AttributeError as e:
            print(e)
            return json(dict(msg="project not found"), status=404)

        return json(dict(jobid=jobid), status=201)


@workflows_bp.put("/<projectid>")
@openapi.body({"application/json": NBTask})
@openapi.parameter("projectid", str, "path")
@openapi.response(200, {"jobid": str}, "Notebook Workflow accepted")
@openapi.response(400, {"msg": str}, description="wrong params")
@openapi.response(503, {"msg": str}, description="Error persiting the job")
@protected()
async def workflow_update(request, projectid):
    """
    Register a notebook workflow and schedule it
    """
    """
    Register a notebook workflow and schedule it
    """
    try:
        nb_task = NBTask(**request.json)
        if not nb_task.schedule:
            return json(dict(msg="schedule information is needed"), 400)

        nb_task.schedule = ScheduleData(**request.json["schedule"])
    except TypeError:
        return json(dict(msg="wrong params"), 400)

    session = request.ctx.session

    async with session.begin():
        try:
            jobid = await workflows.register(session, projectid, nb_task,
                                             update=True)
        except KeyError as e:
            print(e)
            return json(dict(msg="workflow already exist"), status=200)
        except AttributeError:
            return json(dict(msg="project not found"), status=404)

        return json(dict(jobid=jobid), status=201)


@workflows_bp.get("/<projectid>/<jobid>")
@openapi.parameter("projectid", str, "path")
@openapi.parameter("jobid", str, "path")
@openapi.response(200, WorkflowData)
@openapi.response(404, {"msg": str}, description="Job not found")
@protected()
async def workflow_get(request, projectid, jobid):
    """Get a workflow by projectid"""
    # pylint: disable=unused-argument
    session = request.ctx.session
    async with session.begin():
        obj_dict = await workflows.get_by_jobid_prj(session, projectid, jobid)

    if obj_dict:
        return json(asdict(obj_dict), 200)
    return json(dict(msg="Not found"), 404)


@workflows_bp.get("/<projectid>/schedule/<jobid>")
@openapi.parameter("projectid", str, "path")
@openapi.parameter("jobid", str, "path")
@openapi.response(200)
@openapi.response(404, {"msg": str}, description="Job not found")
@protected()
async def schedule_one_job(request, projectid, jobid):
    """Delete a job from RQ and DB"""
    # pylint: disable=unused-argument
    scheduler = _get_scheduler()
    session = request.ctx.session
    async with session.begin():
        obj_dict = await scheduler.get_jobid_db(session, jobid)

    if obj_dict:
        return json(obj_dict, 200)
    return json(dict(msg="Not found"), 404)


@workflows_bp.post("/<projectid>/schedule/<jobid>/_run")
@openapi.parameter("projectid", str, "path")
@openapi.parameter("jobid", str, "path")
@openapi.response(202, dict(executionid=str), "Execution id of the task")
@protected()
def schedule_run(request, projectid, jobid):
    """
    Manually execute a registered schedule task
    """
    Q = _get_q_executor()

    job = Q.enqueue(scheduler_dispatcher, jobid)

    return json(dict(executionid=job.id), status=202)
