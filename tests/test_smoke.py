import modern_di_grpc
from tests.protos import greeter_pb2, greeter_pb2_grpc


def test_public_api_importable() -> None:
    assert isinstance(modern_di_grpc.__all__, list)


def test_proto_stubs_importable() -> None:
    assert greeter_pb2.HelloRequest is not None  # ty: ignore[unresolved-attribute]
    assert greeter_pb2_grpc.GreeterServicer is not None
