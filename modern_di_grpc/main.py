"""modern-di integration for gRPC (grpcio)."""

import contextvars
import dataclasses
import functools
import inspect
import typing

import grpc
from grpc import ServicerContext
from modern_di import Container, Scope, providers


grpc_context_provider = providers.ContextProvider(ServicerContext, scope=Scope.REQUEST)

_request_container: contextvars.ContextVar[Container] = contextvars.ContextVar("modern_di_request_container")


def _build_child(container: Container, context: ServicerContext) -> Container:
    child = container.build_child_container(scope=Scope.REQUEST)
    child.set_context(ServicerContext, context)
    return child


def fetch_di_container() -> Container:
    """Return the current RPC's child container. Raises ``LookupError`` outside an intercepted RPC."""
    return _request_container.get()


def _ensure_context_provider(container: Container) -> None:
    # Register grpc_context_provider once (idempotent) so ServicerContext injects out of the box.
    if container.providers_registry.find_provider(ServicerContext) is None:
        container.add_providers(grpc_context_provider)


T = typing.TypeVar("T")
T_co = typing.TypeVar("T_co", covariant=True)


@dataclasses.dataclass(slots=True, frozen=True)
class _FromDI(typing.Generic[T_co]):
    dependency: "providers.AbstractProvider[T_co] | type[T_co]"


def FromDI(dependency: "providers.AbstractProvider[T] | type[T]") -> T:  # noqa: N802
    """Mark a servicer-method parameter for DI injection via ``Annotated[T, FromDI]``."""
    return typing.cast(T, _FromDI(dependency))


def _parse_inject_params(func: typing.Callable[..., typing.Any]) -> dict[str, _FromDI[typing.Any]]:
    hints = typing.get_type_hints(func, include_extras=True)
    di_params: dict[str, _FromDI[typing.Any]] = {}
    for name, hint in hints.items():
        if name == "return":
            continue
        if typing.get_origin(hint) is typing.Annotated:
            for meta in typing.get_args(hint)[1:]:
                if isinstance(meta, _FromDI):
                    di_params[name] = meta
                    break
    return di_params


def _resolve(di_params: dict[str, _FromDI[typing.Any]]) -> dict[str, typing.Any]:
    container = _request_container.get()
    return {name: container.resolve_dependency(marker.dependency) for name, marker in di_params.items()}


def inject(func: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Any]:
    """Resolve ``FromDI`` params of a gRPC servicer method from the current RPC's child container.

    Produces a sync, async, or async-generator wrapper matching *func*. gRPC always calls a
    behavior as ``(request, context)`` positionally, so resolved params are appended as keywords
    (no bind-by-name needed). A method with no ``FromDI`` parameter is returned unchanged.
    """
    di_params = _parse_inject_params(func)
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
