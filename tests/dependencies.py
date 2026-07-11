import dataclasses

from grpc import ServicerContext
from modern_di import Group, Scope, providers


app_teardowns: list[str] = []
request_teardowns: list[str] = []


@dataclasses.dataclass(kw_only=True, slots=True)
class AppResource:
    label: str


@dataclasses.dataclass(kw_only=True, slots=True)
class RequestResource:
    app_resource: AppResource


@dataclasses.dataclass(kw_only=True, slots=True)
class ContextReader:
    peer: str


def _make_context_reader(context: ServicerContext | None = None) -> ContextReader:
    # `context` is wired from grpc_context_provider (ContextProvider(ServicerContext, REQUEST));
    # the `| None = None` default lets it construct at validate time when no context is set.
    return ContextReader(peer=context.peer() if context is not None else "no-context")


async def _close_app(_: AppResource) -> None:
    app_teardowns.append("app-closed")


def _close_request(_: RequestResource) -> None:
    request_teardowns.append("request-closed")


class Dependencies(Group):
    app_factory = providers.Factory(
        creator=AppResource,
        kwargs={"label": "root"},
        cache=providers.CacheSettings(finalizer=_close_app),
    )
    request_factory = providers.Factory(
        scope=Scope.REQUEST,
        creator=RequestResource,
        bound_type=None,
        cache=providers.CacheSettings(finalizer=_close_request),
    )
    context_reader = providers.Factory(
        scope=Scope.REQUEST,
        creator=_make_context_reader,
        bound_type=None,
    )
