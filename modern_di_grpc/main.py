"""modern-di integration for gRPC (grpcio)."""

import contextvars
import dataclasses
import functools
import inspect
import typing

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
