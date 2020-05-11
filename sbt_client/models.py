import typing as t
from enum import Enum
from pydantic import BaseModel


class RpcRequest(t.NamedTuple):
    jsonrpc: str
    id: int
    method: str
    params: t.Dict[str, t.Any]


class LogMessageParams(BaseModel):
    type: int
    message: str


class DiagnosticPosition(BaseModel):
    line: int
    character: int


class DiagnosticRange(BaseModel):
    start: DiagnosticPosition
    end: DiagnosticPosition


class Diagnostic(BaseModel):
    range: DiagnosticRange
    severity: int
    message: str


class DiagnosticParams(BaseModel):
    uri: str
    diagnostics: t.List[Diagnostic]


class LogMessageEvent(BaseModel):
    params: LogMessageParams


class DiagnosticEvent(BaseModel):
    params: DiagnosticParams


RpcEvent = t.Union[LogMessageEvent, DiagnosticEvent]


class ResultStatus(Enum):
    DONE = "Done"


class ResultBody(BaseModel):
    status: ResultStatus


class ErrorBody(BaseModel):
    code: int
    message: str


class RpcResult(BaseModel):
    id: int
    result: ResultBody


class RpcError(BaseModel):
    id: int
    error: ErrorBody


RpcResponse = t.Union[RpcResult, RpcError, RpcEvent]
