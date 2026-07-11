import contextlib
import contextvars
import typing
import unittest.mock

import pytest
from grpc import ServicerContext
from modern_di import Container, Scope

from modern_di_grpc import FromDI, fetch_di_container, grpc_context_provider, inject
from modern_di_grpc.main import _build_child, _request_container
from tests.dependencies import AppResource, Dependencies, RequestResource, app_teardowns, request_teardowns


@contextlib.contextmanager
def _rpc_child() -> typing.Iterator[Container]:
    root = Container(groups=[Dependencies], validate=True)
    child = root.build_child_container(scope=Scope.REQUEST)
    token = _request_container.set(child)
    try:
        yield child
    finally:
        child.close_sync()
        _request_container.reset(token)


def test_fetch_di_container_returns_child() -> None:
    with _rpc_child() as child:
        assert fetch_di_container() is child


def test_fetch_di_container_raises_outside_rpc() -> None:
    def _call() -> None:
        with pytest.raises(LookupError):
            fetch_di_container()

    contextvars.copy_context().run(_call)  # guaranteed-unset ContextVar


def test_inject_sync_resolves() -> None:
    @inject
    def method(
        _self: object,
        _request: str,
        _context: object,
        app_res: typing.Annotated[AppResource, FromDI(AppResource)],
        req_res: typing.Annotated[RequestResource, FromDI(Dependencies.request_factory)],
    ) -> tuple[bool, bool]:
        return isinstance(app_res, AppResource), isinstance(req_res, RequestResource)

    with _rpc_child():
        assert method(object(), "req", object()) == (True, True)


def test_inject_sync_passthrough_without_fromdi() -> None:
    def method(_self: object, request: str, _context: object) -> str:
        return request

    wrapped = inject(method)
    assert wrapped is method
    assert wrapped(object(), "req", object()) == "req"


def test_inject_sync_generator_resolves() -> None:
    @inject
    def method(
        _self: object,
        _request: str,
        _context: object,
        req_res: typing.Annotated[RequestResource, FromDI(Dependencies.request_factory)],
    ) -> typing.Iterator[bool]:
        yield isinstance(req_res, RequestResource)

    with _rpc_child():
        assert list(method(object(), "req", object())) == [True]


async def test_inject_async_resolves() -> None:
    @inject
    async def method(
        _self: object,
        _request: str,
        _context: object,
        req_res: typing.Annotated[RequestResource, FromDI(Dependencies.request_factory)],
    ) -> bool:
        return isinstance(req_res, RequestResource)

    with _rpc_child():
        assert await method(object(), "req", object()) is True


async def test_inject_async_generator_resolves() -> None:
    @inject
    async def method(
        _self: object,
        _request: str,
        _context: object,
        req_res: typing.Annotated[RequestResource, FromDI(Dependencies.request_factory)],
    ) -> typing.AsyncIterator[bool]:
        yield isinstance(req_res, RequestResource)

    with _rpc_child():
        assert [x async for x in method(object(), "req", object())] == [True]


def test_build_child_seeds_servicer_context() -> None:
    root = Container(groups=[Dependencies], validate=True)
    root.add_providers(grpc_context_provider)
    context = typing.cast(ServicerContext, unittest.mock.MagicMock(spec=ServicerContext))
    child = _build_child(root, context)
    try:
        assert child.scope is Scope.REQUEST
        assert child.resolve(ServicerContext) is context
    finally:
        child.close_sync()
        root.close_sync()


def test_context_reader_resolves_without_live_context() -> None:
    with _rpc_child() as child:
        reader = child.resolve_provider(Dependencies.context_reader)
        assert reader.peer == "no-context"


async def test_close_runs_app_and_request_finalizers() -> None:
    app_before, request_before = len(app_teardowns), len(request_teardowns)
    root = Container(groups=[Dependencies], validate=True)
    root.resolve(AppResource)
    child = root.build_child_container(scope=Scope.REQUEST)
    child.resolve_provider(Dependencies.request_factory)
    child.close_sync()
    await root.close_async()
    assert request_teardowns[request_before:] == ["request-closed"]
    assert app_teardowns[app_before:] == ["app-closed"]
