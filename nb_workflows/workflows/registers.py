from dataclasses import asdict

from nb_workflows.conf import settings, settings_client
from nb_workflows.db.sync import SQL
from nb_workflows.notifications import (EMOJI_ERROR, EMOJI_OK, DiscordClient,
                                        SlackCient)
from nb_workflows.workflows.entities import ExecutionResult, NBTask
from nb_workflows.workflows.managers import history
from nb_workflows.workflows.models import HistoryModel


def send_discord_fail(msg):
    txt = f"{EMOJI_ERROR} - {msg}"

    dc = DiscordClient()

    dc.send(settings.DISCORD_FAIL, txt)


def send_discord_ok(msg):
    txt = f"{EMOJI_OK} - {msg}"

    dc = DiscordClient()

    dc.send(settings.DISCORD_OK, txt)


def send_slack_ok(msg):
    txt = f"{EMOJI_OK} - {msg}"
    sc = SlackCient(tkn=settings.SLACK_BOT_TOKEN)
    sc.send(settings.SLACK_CHANNEL_OK, txt)


def send_slack_fail(msg):
    txt = f"{EMOJI_OK} - {msg}"
    sc = SlackCient(tkn=settings.SLACK_BOT_TOKEN)
    sc.send(settings.SLACK_CHANNEL_FAIL, txt)


def send_ok(medium, msg):
    if medium == "slack":
        send_slack_ok(msg)
    elif medium == "discord":
        send_discord_ok(msg)
    else:
        print("Wrong medium for notifications")


def send_fail(medium, msg):
    if medium == "slack":
        send_slack_fail(msg)
    elif medium == "discord":
        send_discord_fail(msg)
    else:
        print("Wrong medium for notifications")


def job_history_register(execution_result: ExecutionResult, nb_task: NBTask):
    """run inside of the nb_job_executor"""
    db = SQL(settings.SQL)

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
    session = db.sessionmaker()()
    session.add(row)
    session.commit()
    session.close()

    if status == 0 and nb_task.notifications_ok:
        for medium in nb_task.notifications_ok:
            send_ok(medium, (f"{nb_task.jobid} Executed OK in "
                             f"{execution_result.elapsed_secs} secs. "
                             f"NB: {execution_result.name} "
                             f"Alias: {nb_task.alias}."))

    if status != 0 and nb_task.notifications_fail:
        for medium in nb_task.notifications_fail:
            send_fail(medium, (f"{nb_task.jobid} FAILED in "
                               f"{execution_result.elapsed_secs} secs. "
                               f"NB: {execution_result.name} "
                               f"Alias: {nb_task.alias}."))


async def register_history_db(session,
                              execution_result: ExecutionResult,
                              nb_task: NBTask):
    """TODO: notifications calls are sync, they should be async
    """
    hm = await history.create(session, execution_result, nb_task)

    if hm.status == 0 and nb_task.notifications_ok:
        for medium in nb_task.notifications_ok:
            send_ok(medium, (f"{nb_task.jobid} Executed OK in "
                             f"{execution_result.elapsed_secs} secs. "
                             f"NB: {execution_result.name} "
                             f"Alias: {nb_task.alias}."))

    if hm.status != 0 and nb_task.notifications_fail:
        for medium in nb_task.notifications_fail:
            send_fail(medium, (f"{nb_task.jobid} FAILED in "
                               f"{execution_result.elapsed_secs} secs. "
                               f"NB: {execution_result.name} "
                               f"Alias: {nb_task.alias}."))
