"""步骤状态：围住真实操作，在开始、成功、异常时各发出相应事件。"""
from contextlib import contextmanager
from uuid import uuid4


@contextmanager
def activity(emit, stage, message, arguments=None):
    activity_id = uuid4().hex

    def update(state):
        emit(stage, message, {"activity_id": activity_id, "state": state, "arguments": arguments})

    update("running")
    try:
        yield
    except Exception:
        update("failed")
        raise
    else:
        update("completed")
