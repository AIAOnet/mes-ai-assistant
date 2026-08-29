"""FastAPI entry point for the MES learning dashboard."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, model_validator
from typing import Literal
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from assistant.models import ProviderError
from assistant.orchestrator import AssistantMode, AssistantOrchestrator, Intent, PageContext
from assistant.service import AssistantNotConfigured, AssistantService
from assistant.tools import MESReadTools, ToolNotFoundError, ToolValidationError
from .controller import SimulationController
from .auth import COOKIE_NAME, authenticate, configured_users, create_session, read_session, secure_cookie_enabled
from .logging_config import configure_logging, correlation_id
from .monitoring import monitoring

DIRECTORY = Path(__file__).parent


def load_local_environment() -> None:
    """Load simple KEY=VALUE entries from the ignored local .env file."""
    environment_path = DIRECTORY.parent / ".env"
    if not environment_path.exists():
        return
    for raw_line in environment_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_local_environment()
configure_logging()
LOGGER = logging.getLogger("dashboard.api")
controller = SimulationController()
assistant_service = AssistantService()
mes_tools = MESReadTools(controller)
assistant_orchestrator = AssistantOrchestrator(mes_tools)


class ThresholdSettings(BaseModel):
    warning: float = Field(ge=0)
    critical: float = Field(gt=0)

    @model_validator(mode="after")
    def warning_must_be_below_critical(self):
        if self.warning >= self.critical:
            raise ValueError("warning must be lower than critical")
        return self


class Configuration(BaseModel):
    pressure: ThresholdSettings
    temperature: ThresholdSettings
    simulation_update_interval: float = Field(gt=0, le=60)
    production_interval_ticks: int = Field(ge=1, le=3600)
    opc_endpoint: str = Field(min_length=12, max_length=300)
    communication_mode: Literal["OPC_UA", "MQTT"]
    mqtt_broker_host: str = Field(default="127.0.0.1", min_length=1, max_length=200)
    mqtt_broker_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_topic_prefix: str = Field(default="factory/machine-01", min_length=1, max_length=200)

    @model_validator(mode="after")
    def valid_opc_endpoint(self):
        if not self.opc_endpoint.startswith("opc.tcp://"):
            raise ValueError("OPC endpoint must begin with opc.tcp://")
        return self


class AcknowledgeRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=100)


class ProductionOrderRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    product_name: str = Field(min_length=1, max_length=100)
    target_quantity: int = Field(ge=1, le=1_000_000)


class CommunicationModeRequest(BaseModel):
    mode: Literal["OPC_UA", "MQTT"]


class DashboardSecurity(BaseModel):
    authentication_enabled: bool
    session_timeout_minutes: int = Field(ge=5, le=1440)
    audit_enabled: bool


class OPCUASecurity(BaseModel):
    security_mode: Literal["None", "Sign", "SignAndEncrypt"]
    security_policy: Literal["None", "Basic256Sha256", "Aes128_Sha256_RsaOaep"]
    certificate_path: str = Field(max_length=500)
    private_key_path: str = Field(max_length=500)
    server_certificate_path: str = Field(default="", max_length=500)
    server_private_key_path: str = Field(default="", max_length=500)
    trusted_certificates_path: str = Field(max_length=500)

    @model_validator(mode="after")
    def certificates_required_when_secured(self):
        required = (self.certificate_path, self.private_key_path, self.server_certificate_path, self.server_private_key_path)
        if self.security_mode != "None" and any(not path.strip() for path in required):
            raise ValueError("OPC UA client/server certificate and private key paths are required for a secured mode")
        return self


class MQTTSecurity(BaseModel):
    tls_enabled: bool
    username: str = Field(max_length=100)
    ca_certificate_path: str = Field(max_length=500)
    client_certificate_path: str = Field(max_length=500)
    client_key_path: str = Field(max_length=500)

    @model_validator(mode="after")
    def ca_required_for_tls(self):
        if self.tls_enabled and not self.ca_certificate_path.strip():
            raise ValueError("MQTT CA certificate path is required when TLS is enabled")
        if self.tls_enabled and not self.username.strip():
            raise ValueError("MQTT username is required when TLS is enabled")
        if bool(self.client_certificate_path.strip()) != bool(self.client_key_path.strip()):
            raise ValueError("MQTT client certificate and private key must be configured together")
        return self


class SecurityConfiguration(BaseModel):
    dashboard: DashboardSecurity
    opc_ua: OPCUASecurity
    mqtt: MQTTSecurity


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class AssistantPageContext(BaseModel):
    page: Literal[
        "machine_details", "production", "communication", "data_flow", "maintenance",
        "security", "configuration", "diagnostics", "database", "alarm_details",
    ]
    machine_id: str | None = Field(default=None, pattern=r"^MACHINE-\d{2}$")
    alarm_id: str | None = Field(default=None, min_length=3, max_length=66)
    production_order_id: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"
    )


class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    context: AssistantPageContext | None = None


def assistant_conversation_key(request: Request, conversation_id: str) -> str:
    user = request.state.user
    identity = user.username if user else "local"
    return f"{identity}:{conversation_id}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await controller.start()
    try:
        yield
    finally:
        await controller.shutdown()


app = FastAPI(title="MES Factory Simulation", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=DIRECTORY), name="static")


def authentication_enabled() -> bool:
    return bool(controller.settings["security"]["dashboard"].get("authentication_enabled"))


@app.middleware("http")
async def enforce_dashboard_access(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:100]
    context_token = correlation_id.set(request_id)
    started = time.perf_counter()
    path = request.url.path
    user = read_session(request.cookies.get(COOKIE_NAME))
    login_username = None
    if path == "/api/auth/login" and request.method == "POST":
        try:
            login_username = (await request.json()).get("username", "")
        except Exception:
            pass
    request.state.user = user
    exempt = path == "/" or path.startswith("/static/") or path.startswith("/api/auth/")
    access_response = None
    if authentication_enabled() and path.startswith("/api/") and not exempt:
        if user is None:
            access_response = JSONResponse({"detail": "Authentication required"}, status_code=401)
        admin_only = path in {"/api/config", "/api/security", "/api/database", "/api/diagnostics", "/api/monitoring", "/api/system/restart"}
        if access_response is None and admin_only and user.role != "admin":
            access_response = JSONResponse({"detail": "Administrator role required"}, status_code=403)
    if access_response is not None:
        response = access_response
    else:
        try:
            response = await call_next(request)
        except Exception:
            monitoring.record_request(request.method, path, 500, time.perf_counter() - started)
            LOGGER.exception("http_request_failed", extra={"fields": {"method": request.method, "path": path, "user": user.username if user else None, "role": user.role if user else None}})
            correlation_id.reset(context_token)
            raise
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self' ws: wss:; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'"
    if path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        audit_user = user
        if path == "/api/auth/login" and response.status_code == 200 and login_username:
            record = configured_users().get(login_username)
            if record:
                from .auth import User
                audit_user = User(login_username, record[1])
        if audit_user is not None:
            try:
                controller.audit_operator_action(audit_user.username, audit_user.role, request.method, path, response.status_code, request.client.host if request.client else None)
            except Exception:
                pass
    duration = time.perf_counter() - started
    monitoring.record_request(request.method, path, response.status_code, duration)
    LOGGER.info("http_request", extra={"fields": {"method": request.method, "path": path, "status": response.status_code, "duration_ms": round(duration * 1000, 2), "user": user.username if user else None, "role": user.role if user else None, "client": request.client.host if request.client else None}})
    correlation_id.reset(context_token)
    return response


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(
        DIRECTORY / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/healthz", include_in_schema=False)
async def health() -> JSONResponse:
    result = controller.health()
    return JSONResponse(result, status_code=200 if result["transport_connected"] else 503)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(monitoring.prometheus(controller.diagnostics()["services"]), media_type="text/plain; version=0.0.4")


@app.get("/api/auth/me")
async def current_user(request: Request) -> dict:
    user = read_session(request.cookies.get(COOKIE_NAME))
    return {
        "authentication_enabled": authentication_enabled(),
        "authenticated": user is not None or not authentication_enabled(),
        "username": user.username if user else ("Local user" if not authentication_enabled() else None),
        "role": user.role if user else ("admin" if not authentication_enabled() else None),
    }


@app.post("/api/auth/login")
async def login(credentials: LoginRequest):
    if not authentication_enabled():
        raise HTTPException(status_code=409, detail="Authentication is disabled")
    user = authenticate(credentials.username.strip(), credentials.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    timeout = controller.settings["security"]["dashboard"]["session_timeout_minutes"]
    response = JSONResponse({"username": user.username, "role": user.role})
    response.set_cookie(COOKIE_NAME, create_session(user, timeout), max_age=timeout * 60, httponly=True, samesite="strict", secure=secure_cookie_enabled())
    return response


@app.post("/api/auth/logout")
async def logout() -> JSONResponse:
    response = JSONResponse({"logged_out": True})
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="strict")
    return response


@app.get("/api/assistant/status")
async def assistant_status() -> dict:
    return assistant_service.status()


@app.post("/api/assistant/chat")
async def assistant_chat(chat_request: AssistantChatRequest, request: Request) -> dict:
    message = chat_request.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message is required")
    try:
        conversation_key = assistant_conversation_key(request, chat_request.conversation_id)
        page_context = PageContext(**chat_request.context.model_dump()) if chat_request.context else None
        plan = assistant_orchestrator.plan(message, page_context, conversation_key)
        if plan.intent == Intent.UNSUPPORTED_OPERATIONAL:
            answer = (
                "That operational question requires historical or investigation tools that are "
                "not available until Phase 5 analytics. I will not guess from raw historical data."
            )
            assistant_service.remember_exchange(conversation_key, message, answer)
            model = None
            tool_result = None
        elif plan.mode == AssistantMode.DATA:
            tool_result = assistant_orchestrator.execute(plan)
            answer, model = await assistant_service.grounded_chat(
                conversation_key, message, plan.intent.value, tool_result.as_context()
            )
        else:
            tool_result = None
            answer, model = await assistant_service.chat(conversation_key, message)
    except AssistantNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ToolValidationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ToolNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "answer": answer,
        "model": model,
        "conversation_id": chat_request.conversation_id,
        "mode": plan.mode.value,
        "intent": plan.intent.value,
        "tool": plan.tool,
        "tool_arguments": plan.arguments,
        "resolved_context": plan.context,
        "sources": tool_result.sources if tool_result else [],
    }


@app.delete("/api/assistant/conversations/{conversation_id}")
async def clear_assistant_conversation(conversation_id: str, request: Request) -> dict:
    if not conversation_id.replace("-", "").replace("_", "").isalnum() or len(conversation_id) > 100:
        raise HTTPException(status_code=422, detail="Invalid conversation ID")
    conversation_key = assistant_conversation_key(request, conversation_id)
    assistant_service.clear(conversation_key)
    assistant_orchestrator.clear_context(conversation_key)
    return {"cleared": True}


@app.get("/api/mes/machines/{machine_id}/status")
async def mes_machine_status(machine_id: str) -> dict:
    try:
        return mes_tools.get_machine_status(machine_id).as_context()
    except ToolValidationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get("/api/mes/machines/{machine_id}/alarms")
async def mes_machine_alarms(machine_id: str, active_only: bool = False, period: str | None = None) -> dict:
    try:
        return mes_tools.get_machine_alarms(machine_id, active_only, period).as_context()
    except ToolValidationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get("/api/mes/machines/{machine_id}/production")
async def mes_production_status(machine_id: str) -> dict:
    try:
        return mes_tools.get_production_status(machine_id).as_context()
    except ToolValidationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get("/api/mes/machines/{machine_id}/oee")
async def mes_oee(machine_id: str) -> dict:
    try:
        return mes_tools.get_oee(machine_id).as_context()
    except ToolValidationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get("/api/mes/machines/{machine_id}/history")
async def mes_machine_history(machine_id: str, metric: str, period: str, limit: int = 100) -> dict:
    try:
        return mes_tools.get_machine_history(machine_id, metric, period, limit).as_context()
    except ToolValidationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get("/api/mes/machines/{machine_id}/events")
async def mes_event_history(machine_id: str, period: str, limit: int = 100) -> dict:
    try:
        return mes_tools.search_events(machine_id, period, limit).as_context()
    except ToolValidationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get("/api/mes/machines/{machine_id}/maintenance")
async def mes_maintenance_history(machine_id: str, period: str, limit: int = 100) -> dict:
    try:
        return mes_tools.get_maintenance_history(machine_id, period, limit).as_context()
    except ToolValidationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get("/api/mes/machines/{machine_id}/production-history")
async def mes_production_history(machine_id: str, period: str, limit: int = 100) -> dict:
    try:
        return mes_tools.get_production_history(machine_id, period, limit).as_context()
    except ToolValidationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get("/api/mes/alarms/{alarm_id}")
async def mes_alarm_details(alarm_id: str) -> dict:
    alarm = next((item for item in controller.read_machine_alarms("MACHINE-01") if item["id"] == alarm_id), None)
    if alarm is None:
        raise HTTPException(status_code=404, detail="Alarm not found")
    return {"data": alarm, "sources": [{"type": "alarm", "id": alarm_id,
                                        "uri": f"/api/mes/alarms/{alarm_id}"}]}


@app.get("/api/mes/production-orders/{order_id}")
async def mes_production_order(order_id: str) -> dict:
    orders = controller.read_production_status("MACHINE-01")["orders"]
    order = next((item for item in orders if item["id"] == order_id), None)
    if order is None:
        raise HTTPException(status_code=404, detail="Production order not found")
    return {"data": order, "sources": [{"type": "production_order", "id": order_id,
                                        "uri": f"/api/mes/production-orders/{order_id}"}]}


@app.post("/api/system/restart")
async def restart_dashboard() -> dict:
    if not os.getenv("MES_CONTAINERIZED"):
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([sys.executable, "-m", "dashboard.restart"], cwd=DIRECTORY.parent, creationflags=flags, close_fds=True)

    async def stop_current_process() -> None:
        await asyncio.sleep(0.75)
        os._exit(0)

    asyncio.create_task(stop_current_process())
    return {"restarting": True}


@app.get("/api/state")
async def state() -> dict:
    return controller.snapshot()


@app.get("/api/config")
async def get_configuration() -> dict:
    return controller.configuration()


@app.get("/api/database")
async def database_view() -> dict:
    return controller.database_snapshot()


@app.get("/api/diagnostics")
async def diagnostics() -> dict:
    return controller.diagnostics()


@app.get("/api/monitoring")
async def monitoring_snapshot() -> dict:
    return monitoring.snapshot(controller.diagnostics()["services"])


@app.get("/api/security")
async def get_security_configuration() -> dict:
    return controller.security_configuration()


@app.put("/api/security")
async def update_security_configuration(configuration: SecurityConfiguration) -> dict:
    if configuration.dashboard.authentication_enabled:
        if not os.getenv("MES_DASHBOARD_SECRET") or len(os.getenv("MES_DASHBOARD_SECRET", "")) < 32:
            raise HTTPException(status_code=422, detail="MES_DASHBOARD_SECRET must contain at least 32 characters")
        if not configured_users():
            raise HTTPException(status_code=422, detail="Configure at least one dashboard user in environment variables")
    return controller.apply_security_configuration(configuration.model_dump())


@app.put("/api/config")
async def update_configuration(configuration: Configuration) -> dict:
    return controller.apply_configuration(configuration.model_dump())


@app.post("/api/simulation/start")
async def start_simulation() -> dict:
    await controller.start_simulation()
    return controller.snapshot()


@app.post("/api/simulation/pause")
async def pause_simulation() -> dict:
    await controller.pause_simulation()
    return controller.snapshot()


@app.post("/api/machine/start")
async def start_machine() -> dict:
    await controller.start_machine()
    return controller.snapshot()


@app.post("/api/machine/stop")
async def stop_machine() -> dict:
    await controller.stop_machine()
    return controller.snapshot()


@app.post("/api/machine/reset")
async def reset_machine() -> dict:
    await controller.reset_machine()
    return controller.snapshot()


@app.post("/api/faults/pressure")
async def raise_pressure() -> dict:
    controller.raise_pressure()
    return controller.snapshot()


@app.post("/api/faults/temperature")
async def raise_temperature() -> dict:
    controller.raise_temperature()
    return controller.snapshot()


@app.post("/api/alarms/{alarm_id}/acknowledge")
async def acknowledge_alarm(alarm_id: str, request: AcknowledgeRequest) -> dict:
    operator = request.operator.strip()
    if not operator:
        raise HTTPException(status_code=422, detail="Operator name is required")
    alarm = controller.acknowledge_alarm(alarm_id, operator)
    if alarm is None:
        raise HTTPException(status_code=404, detail="Alarm not found")
    return controller.snapshot()


@app.post("/api/tasks/{task_id}/start")
async def start_task(task_id: int) -> dict:
    task = controller.start_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return controller.snapshot()


@app.post("/api/tasks/{task_id}/complete")
async def complete_task(task_id: int) -> dict:
    task = controller.complete_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return controller.snapshot()


@app.post("/api/production-orders")
async def create_production_order(request: ProductionOrderRequest) -> dict:
    try:
        controller.create_production_order(request.order_id, request.product_name, request.target_quantity)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return controller.snapshot()


@app.post("/api/communication/mode")
async def switch_communication(request: CommunicationModeRequest) -> dict:
    try:
        await controller.switch_communication(request.mode)
    except OSError as error:
        raise HTTPException(status_code=503, detail=f"Transport connection failed: {error}") from error
    return controller.snapshot()


@app.post("/api/production-orders/{order_id}/start")
async def start_production_order(order_id: str) -> dict:
    try:
        order = controller.start_production_order(order_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if order is None:
        raise HTTPException(status_code=404, detail="Production order not found")
    return controller.snapshot()


@app.post("/api/production-orders/{order_id}/reject")
async def reject_production_part(order_id: str) -> dict:
    try:
        order = controller.reject_production_part(order_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if order is None:
        raise HTTPException(status_code=404, detail="Production order not found")
    return controller.snapshot()


@app.post("/api/production-orders/{order_id}/complete")
async def complete_production_order(order_id: str) -> dict:
    try:
        order = controller.complete_production_order(order_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if order is None:
        raise HTTPException(status_code=404, detail="Production order not found")
    return controller.snapshot()


@app.websocket("/ws/live")
async def live(websocket: WebSocket) -> None:
    if authentication_enabled() and read_session(websocket.cookies.get(COOKIE_NAME)) is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(controller.snapshot())
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError):
        pass


def main() -> None:
    import uvicorn
    uvicorn.run("dashboard.api:app", host=os.getenv("MES_DASHBOARD_HOST", "127.0.0.1"), port=int(os.getenv("MES_DASHBOARD_PORT", "8000")))


if __name__ == "__main__":
    main()
