import grpc

from examples.app import build_server
from tests.protos import greeter_pb2, greeter_pb2_grpc


HelloRequest = greeter_pb2.HelloRequest  # ty: ignore[unresolved-attribute]


def test_example_resolves_and_greets() -> None:
    server, port, container = build_server()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = greeter_pb2_grpc.GreeterStub(channel)
            reply = stub.SayHello(HelloRequest(name="world"))
        assert reply.message == "Hello, world!"
    finally:
        server.stop(0)
        container.close_sync()
