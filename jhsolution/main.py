from typing import Any, Awaitable, Callable, Optional, Union
import enum, time

from opentelemetry.sdk.resources import SERVICE_NAME as OTEL_SERVICE_NAME
from opentelemetry.sdk.resources import Resource as OtelResource

from opentelemetry import trace as otel_trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from opentelemetry import metrics as otel_metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

from opentelemetry.sdk import _logs as otel_logs
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

import logging, structlog
from logging import config, handlers
from structlog.types import EventDict

import sqlalchemy as sa
from sqlalchemy import orm

from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from asgi_correlation_id import correlation_id, CorrelationIdMiddleware
from uvicorn.protocols.utils import get_path_with_query_string

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exception_handlers import http_exception_handler

from jhsolution import env, model
from jhsolution.router import api, admin, site, misc, car365_api_test

################################################################################
# Config open telemetry exporter
################################################################################

resource = OtelResource(
	attributes={OTEL_SERVICE_NAME: "JHsolution"}, schema_url=env.OPEN_TELEMETRY_URL
)

trace_provider = TracerProvider(resource=resource)
trace_exporter = OTLPSpanExporter(endpoint=env.OPEN_TELEMETRY_URL, insecure=True)
processor = BatchSpanProcessor(trace_exporter)
trace_provider.add_span_processor(processor)
otel_trace.set_tracer_provider(trace_provider)

metric_exporter = OTLPMetricExporter(endpoint=env.OPEN_TELEMETRY_URL, insecure=True)
metric_reader = PeriodicExportingMetricReader(metric_exporter)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
otel_metrics.set_meter_provider(meter_provider)

otel_logger_provider = LoggerProvider(resource=resource)
log_exporter = OTLPLogExporter(endpoint=env.OPEN_TELEMETRY_URL, insecure=True)
log_processor = BatchLogRecordProcessor(log_exporter)
otel_logger_provider.add_log_record_processor(log_processor)
# Set logging handler at below

################################################################################
# Config loggers
################################################################################

# Event processors

def orm_processor(
	logger: logging.Logger, name: str, event_dict: EventDict
) -> EventDict:
	for key, item in event_dict.items():
		if isinstance(item, model.Base):
			event_dict[key] = item.to_dict()
		if isinstance(item, enum.Enum):
			event_dict[key] = item.name
	return event_dict

def render_request_id(
	logger: logging.Logger, name: str, event_dict: EventDict
) -> EventDict:
	if request_id := event_dict.pop('request_id', None):
		event_dict['event'] = f"[{request_id[:8]}] {event_dict['event']}"
	return event_dict

def add_opentelemetry_spans(
	logger: logging.Logger, name: str, event_dict: EventDict
) -> EventDict:
	span = otel_trace.get_current_span()
	if not span.is_recording():
		event_dict["span"] = None
		return event_dict

	ctx = span.get_span_context()
	parent = getattr(span, "parent", None)

	event_dict["span"] = {
		"span_id": hex(ctx.span_id),
		"trace_id": hex(ctx.trace_id),
		"parent_span_id": hex(parent.span_id) if parent else None,
	}

	return event_dict

def drop_headers(
	logger: logging.Logger, name: str, event_dict: EventDict
) -> EventDict:
	event_dict.pop("http_request_headers", None)
	return event_dict

timestamper = structlog.processors.TimeStamper(fmt='iso')

pre_chain: list[structlog.types.Processor] = [
	structlog.contextvars.merge_contextvars,
	structlog.processors.StackInfoRenderer(),
	structlog.stdlib.add_logger_name,
	structlog.stdlib.add_log_level,
	structlog.stdlib.ExtraAdder(),
	structlog.stdlib.PositionalArgumentsFormatter(),
	timestamper,
	orm_processor,
]

# Structlog Configuration

structlog.configure(
	processors = pre_chain + [
		structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
	],
	logger_factory=structlog.stdlib.LoggerFactory(),
	wrapper_class=structlog.stdlib.BoundLogger,
	cache_logger_on_first_use=True
)

# Formatters

common_processor = structlog.stdlib.ProcessorFormatter.remove_processors_meta
console_formatter = structlog.stdlib.ProcessorFormatter(
	foreign_pre_chain=pre_chain,
	processors=[
		common_processor,
		drop_headers,
		render_request_id,
		structlog.dev.ConsoleRenderer()
	]
)
json_formatter = structlog.stdlib.ProcessorFormatter(
	foreign_pre_chain=pre_chain,
	processors=[
		common_processor,
		structlog.processors.format_exc_info,
		structlog.processors.JSONRenderer()
	]
)

# Handlers

console_handler = logging.StreamHandler()
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.DEBUG)

json_handler = logging.handlers.TimedRotatingFileHandler("logs/log", "D", 90)
json_handler.setFormatter(json_formatter)
json_handler.setLevel(logging.DEBUG)

otel_handler = otel_logs.LoggingHandler(logger_provider=otel_logger_provider)
otel_handler.setFormatter(json_formatter)
otel_handler.setLevel(logging.DEBUG)

# Loggers

root_logger = logging.getLogger()
root_logger.handlers.clear()
root_logger.addHandler(json_handler)
root_logger.setLevel(logging.DEBUG)
root_logger.propagate = True

main_logger = structlog.get_logger("JHsolution")
main_logger.addHandler(otel_handler)
main_logger.addHandler(console_handler)

for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
	logger = logging.getLogger(logger_name)
	logger.handlers.clear()
	logger.addHandler(json_handler)
	logger.setLevel(logging.DEBUG)
	logger.propagate = True

################################################################################
# Config app
################################################################################

app = FastAPI()

# Middlewares

@app.middleware("http")
async def logging_middleware(
	request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
	# Initialize logger context variables

	structlog.contextvars.clear_contextvars()
	request_id = correlation_id.get()
	headers_dict = {k.decode(): v.decode() for k, v in request.headers._list}

	structlog.contextvars.bind_contextvars(
		request_id=request_id,
		http_method=request.method,
		http_url=request.url.path,
		http_request_headers=headers_dict,
	)

	if client := request.client:
		structlog.contextvars.bind_contextvars(
			host=client.host, port=client.port
		)

	main_logger.debug("request has received")

	# Try to process request

	response: Optional[Response]
	try:
		with orm.Session(model.engine) as database_session:
			request.scope["database_session"] = database_session
			start_time = time.perf_counter_ns()
			response = await call_next(request)
	except Exception as e:
		response, exception = None, e

	# Return the response

	finally:
		duration = time.perf_counter_ns() - start_time
		if response is not None:
			code = response.status_code
			headers_dict = {k.decode(): v.decode() for k, v in response.headers._list}
			main_logger.debug(
				"request has succeed",
				http_response_header=headers_dict,
				status_code=code,
				duration=duration
			)
			return response
		else:
			main_logger.info("request has failed", duration=duration)
			if not isinstance(exception, HTTPException):
				main_logger.error("Unexpected exception", exc_info=exception)
				exception = HTTPException(500)
			return await custom_http_exception_handler(request, exception)

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(SessionMiddleware, secret_key=env.SESSION_SECRET_KEY)

# Static Paths and Routers

app.mount("/js", StaticFiles(directory="static/js"), name="static_js")
app.mount("/css", StaticFiles(directory="static/css"), name="static_css")
app.mount("/assets", StaticFiles(directory="static/assets"), name="static_assets")

app.include_router(admin, prefix='/ADMIN')
app.include_router(api, prefix='/api/v1')
app.include_router(site)
app.include_router(misc)

# Exception Handlers

templates = Jinja2Templates(directory="templates")

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(
	request: Request, exception: HTTPException
) -> Response:
	for prefix in ['/api', '/js', '/css', '/assets']:
		if request.url.path[:len(prefix)] == prefix:
			return await http_exception_handler(request, exception)

	context = {'status_code': exception.status_code, 'detail': exception.detail}
	return templates.TemplateResponse(
		request, "error.jinja", context, status_code=exception.status_code
	)
