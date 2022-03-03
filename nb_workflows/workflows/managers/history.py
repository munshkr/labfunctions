from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Union

from nb_workflows.workflows.entities import (ExecutionResult, HistoryResult,
                                             NBTask)
from nb_workflows.workflows.models import HistoryModel
from sqlalchemy import select


@dataclass
class HistoryLastResponse:
    rows: List[HistoryResult]


async def get_last(
        session, jobid: str, limit=1
) -> Union[HistoryLastResponse, None]:
    stmt = (
        select(HistoryModel)
        .where(HistoryModel.jobid == jobid)
        .order_by(HistoryModel.created_at.desc())
        .limit(limit)
    )
    r = await session.execute(stmt)
    results = r.scalars()
    if not results:
        return None

    rsp = []
    for r in results:
        rsp.append(
            HistoryResult(
                jobid=jobid,
                executionid=r.executionid,
                status=r.status,
                result=r.result,
                created_at=r.created_at.isoformat(),
            )
        )
    return HistoryLastResponse(rows=rsp)


async def create(session,
                 execution_result: ExecutionResult,
                 nb_task: NBTask) -> HistoryModel:
    result_data = asdict(execution_result)

    status = 0
    if execution_result.error:
        status = -1

    row = HistoryModel(
        jobid=nb_task.jobid,
        executionid=execution_result.executionid,
        elapsed_secs=execution_result.elapsed_secs,
        nb_name=execution_result.name,
        result=result_data,
        status=status,
    )
    session.add(row)
    return row
