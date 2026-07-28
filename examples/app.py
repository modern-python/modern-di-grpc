# Minimal modern-di + grpc example.
# Run for real:  python -m examples.app  (serves on an ephemeral localhost port until Ctrl+C)
import typing
from concurrent import futures

import grpc
from modern_di import Container, Group, Scope, providers

from modern_di_grpc import DIInterceptor, FromDI, inject
from tests.protos import greeter_pb2, greeter_pb2_grpc


class Settings:
    def __init__(self) -> None:
        self.greeting = "Hello"


class Greeter:
    def __init__(self, settings: Settings) -> None:  # auto-injected by type
        self._settings = settings

    def greet(self, name: str) -> str:
        return f"{self._settings.greeting}, {name}!"


class AppGroup(Group):
    settings = providers.Factory(Settings, scope=Scope.APP, cache=True)
    greeter = providers.Factory(Greeter, scope=Scope.REQUEST)


class GreeterService(greeter_pb2_grpc.GreeterServicer):
    @inject
    def SayHello(  # noqa: N802
        self,
        request: greeter_pb2.HelloRequest,  # ty: ignore[unresolved-attribute]
        _context: grpc.ServicerContext,
        greeter: typing.Annotated[Greeter, FromDI(Greeter)],
    ) -> greeter_pb2.HelloReply:  # ty: ignore[unresolved-attribute]
        return greeter_pb2.HelloReply(message=greeter.greet(request.name))  # ty: ignore[unresolved-attribute]


def build_server(port: str = "127.0.0.1:0") -> tuple[grpc.Server, int, Container]:
    """Wire the container, register the interceptor, and start listening; return the bound port."""
    container = Container(groups=[AppGroup])
    container.validate()  # optional fail-fast; gRPC gives the adapter no root-lifecycle hook,
    # so the close at the end of this function is the caller-owned half
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10), interceptors=[DIInterceptor(container)])
    greeter_pb2_grpc.add_GreeterServicer_to_server(GreeterService(), server)
    bound_port = server.add_insecure_port(port)
    server.start()
    return server, bound_port, container


if __name__ == "__main__":  # pragma: no cover
    _server, _port, _container = build_server("[::]:50051")
    print(f"Serving on port {_port}; Ctrl+C to stop")  # noqa: T201
    try:
        _server.wait_for_termination()
    finally:
        _container.close_sync()
