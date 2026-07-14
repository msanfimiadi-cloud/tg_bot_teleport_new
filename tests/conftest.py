import asyncio
import inspect
from collections.abc import AsyncGenerator
from typing import Any

import pytest


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    testfunction = pyfuncitem.obj
    if inspect.iscoroutinefunction(testfunction):
        kwargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        _run(testfunction(**kwargs))
        return True
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_fixture_setup(fixturedef: pytest.FixtureDef[Any], request: pytest.FixtureRequest) -> Any:
    func = fixturedef.func
    if inspect.isasyncgenfunction(func):
        kwargs = {name: request.getfixturevalue(name) for name in fixturedef.argnames}
        agen: AsyncGenerator[Any, None] = func(**kwargs)
        result = _run(agen.__anext__())

        def finalizer() -> None:
            try:
                _run(agen.__anext__())
            except StopAsyncIteration:
                pass

        request.addfinalizer(finalizer)
        fixturedef.cached_result = (result, fixturedef.cache_key(request), None)
        return result
    if inspect.iscoroutinefunction(func):
        kwargs = {name: request.getfixturevalue(name) for name in fixturedef.argnames}
        result = _run(func(**kwargs))
        fixturedef.cached_result = (result, fixturedef.cache_key(request), None)
        return result
    return None
