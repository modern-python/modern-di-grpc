"""modern-di integration for gRPC (grpcio)."""

import contextvars
import functools
import inspect
import typing

import grpc
import grpc.aio
from grpc import ServicerContext
from modern_di import Container, Scope, integrations, providers


grpc_context_provider = providers.ContextProvider(ServicerContext, scope=Scope.REQUEST)

_request_container: contextvars.ContextVar[Container] = contextvars.ContextVar("modern_di_request_container")


def _build_child(container: Container, context: ServicerContext) -> Container:
    match = integrations.bind(grpc_context_provider, context)
    return container.build_child_container(scope=match.scope, context=match.context)


def fetch_di_container() -> Container:
    """Return the current RPC's child container. Raises ``LookupError`` outside an intercepted RPC."""
    return _request_container.get()


def _ensure_context_provider(container: Container) -> None:
    # Register grpc_context_provider once (idempotent) so ServicerContext injects out of the box.
    if container.providers_registry.find_provider(ServicerContext) is None:
        container.add_providers(grpc_context_provider)


FromDI = integrations.from_di


def _resolve(di_params: dict[str, integrations.Marker[typing.Any]]) -> dict[str, typing.Any]:
    container = _request_container.get()
    return integrations.resolve_markers(container, di_params)


def inject(func: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Any]:
    """Resolve ``FromDI`` params of a gRPC servicer method from the current RPC's child container.

    Produces a sync, async, or async-generator wrapper matching *func*. gRPC always calls a
    behavior as ``(request, context)`` positionally, so resolved params are appended as keywords
    (no bind-by-name needed). A method with no ``FromDI`` parameter is returned unchanged.
    """
    di_params = integrations.parse_markers(func)
    if not di_params:
        return func

    if inspect.isasyncgenfunction(func):

        @functools.wraps(func)
        async def async_gen_wrapper(
            *args: typing.Any,  # noqa: ANN401
            **kwargs: typing.Any,  # noqa: ANN401
        ) -> typing.AsyncIterator[typing.Any]:
            async for item in func(*args, **kwargs, **_resolve(di_params)):
                yield item

        return async_gen_wrapper

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:  # noqa: ANN401
            return await func(*args, **kwargs, **_resolve(di_params))

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:  # noqa: ANN401
        return func(*args, **kwargs, **_resolve(di_params))

    return sync_wrapper


def _rewrap(
    handler: grpc.RpcMethodHandler,
    unary_builder: typing.Callable[[typing.Callable[..., typing.Any]], typing.Callable[..., typing.Any]],
    stream_builder: typing.Callable[[typing.Callable[..., typing.Any]], typing.Callable[..., typing.Any]],
) -> grpc.RpcMethodHandler:
    # grpc.RpcMethodHandler is an abc.ABC documenting these attributes only in its docstring (no annotated
    # fields), so ty cannot resolve them on the concrete instances the runtime actually hands back.
    deserializer = handler.request_deserializer  # ty: ignore[unresolved-attribute]
    serializer = handler.response_serializer  # ty: ignore[unresolved-attribute]
    if unary_unary := handler.unary_unary:  # ty: ignore[unresolved-attribute]
        return grpc.unary_unary_rpc_method_handler(unary_builder(unary_unary), deserializer, serializer)
    if unary_stream := handler.unary_stream:  # ty: ignore[unresolved-attribute]
        return grpc.unary_stream_rpc_method_handler(stream_builder(unary_stream), deserializer, serializer)
    if stream_unary := handler.stream_unary:  # ty: ignore[unresolved-attribute]
        return grpc.stream_unary_rpc_method_handler(unary_builder(stream_unary), deserializer, serializer)
    if stream_stream := handler.stream_stream:  # ty: ignore[unresolved-attribute]
        return grpc.stream_stream_rpc_method_handler(stream_builder(stream_stream), deserializer, serializer)
    return handler  # pragma: no cover  (every RpcMethodHandler sets exactly one behavior)


def _wrap_unary_sync(
    behavior: typing.Callable[..., typing.Any], container: Container
) -> typing.Callable[..., typing.Any]:
    def wrapper(request_or_iterator: typing.Any, context: ServicerContext) -> typing.Any:  # noqa: ANN401
        child = _build_child(container, context)
        token = _request_container.set(child)
        try:
            return behavior(request_or_iterator, context)
        finally:
            try:
                child.close_sync()
            finally:
                _request_container.reset(token)

    return wrapper


def _wrap_stream_sync(
    behavior: typing.Callable[..., typing.Any], container: Container
) -> typing.Callable[..., typing.Any]:
    def wrapper(request_or_iterator: typing.Any, context: ServicerContext) -> typing.Iterator[typing.Any]:  # noqa: ANN401
        child = _build_child(container, context)
        token = _request_container.set(child)
        try:
            yield from behavior(request_or_iterator, context)
        finally:
            try:
                child.close_sync()
            finally:
                _request_container.reset(token)

    return wrapper


class DIInterceptor(grpc.ServerInterceptor):
    """Server interceptor that opens a ``Scope.REQUEST`` child container per RPC (sync server)."""

    def __init__(self, container: Container) -> None:
        self._container = container
        _ensure_context_provider(container)

    def intercept_service(
        self,
        continuation: typing.Callable[[grpc.HandlerCallDetails], grpc.RpcMethodHandler],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler:
        handler = continuation(handler_call_details)
        if handler is None:
            return handler
        return _rewrap(
            handler,
            lambda behavior: _wrap_unary_sync(behavior, self._container),
            lambda behavior: _wrap_stream_sync(behavior, self._container),
        )


def _wrap_unary_aio(
    behavior: typing.Callable[..., typing.Any], container: Container
) -> typing.Callable[..., typing.Any]:
    async def wrapper(request_or_iterator: typing.Any, context: ServicerContext) -> typing.Any:  # noqa: ANN401
        child = _build_child(container, context)
        token = _request_container.set(child)
        try:
            return await behavior(request_or_iterator, context)
        finally:
            try:
                await child.close_async()
            finally:
                _request_container.reset(token)

    return wrapper


def _wrap_stream_aio(
    behavior: typing.Callable[..., typing.Any], container: Container
) -> typing.Callable[..., typing.Any]:
    async def wrapper(request_or_iterator: typing.Any, context: ServicerContext) -> typing.AsyncIterator[typing.Any]:  # noqa: ANN401
        child = _build_child(container, context)
        token = _request_container.set(child)
        try:
            async for item in behavior(request_or_iterator, context):
                yield item
        finally:
            try:
                await child.close_async()
            finally:
                _request_container.reset(token)

    return wrapper


class DIAioInterceptor(grpc.aio.ServerInterceptor):
    """Server interceptor that opens a ``Scope.REQUEST`` child container per RPC (async server)."""

    def __init__(self, container: Container) -> None:
        self._container = container
        _ensure_context_provider(container)

    async def intercept_service(
        self,
        continuation: typing.Callable[[grpc.HandlerCallDetails], typing.Awaitable[grpc.RpcMethodHandler]],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler:
        handler = await continuation(handler_call_details)
        if handler is None:
            return handler
        return _rewrap(
            handler,
            lambda behavior: _wrap_unary_aio(behavior, self._container),
            lambda behavior: _wrap_stream_aio(behavior, self._container),
        )
