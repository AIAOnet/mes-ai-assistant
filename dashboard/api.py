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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .controller import SimulationController
from .auth import COOKIE_NAME, authenticate, configured_users, create_session, read_session
from .logging_config import configure_logging, correlation_id

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
        admin_only = path in {"/api/config", "/api/security", "/api/database", "/api/diagnostics", "/api/system/restart"}
        if access_response is None and admin_only and user.role != "admin":
            access_response = JSONResponse({"detail": "Administrator role required"}, status_code=403)
    if access_response is not None:
        response = access_response
    else:
        try:
            response = await call_next(request)
        except Exception:
            LOGGER.exception("http_request_failed", extra={"fields": {"method": request.method, "path": path, "user": user.username if user else None, "role": user.role if user else None}})
            correlation_id.reset(context_token)
            raise
    response.headers["X-Request-ID"] = request_id
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
    LOGGER.info("http_request", extra={"fields": {"method": request.method, "path": path, "status": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "user": user.username if user else None, "role": user.role if user else None, "client": request.client.host if request.client else None}})
    correlation_id.reset(context_token)
    return response


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(DIRECTORY / "index.html")


@app.get("/healthz", include_in_schema=False)
async def health() -> JSONResponse:
    result = controller.health()
    return JSONResponse(result, status_code=200 if result["transport_connected"] else 503)


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
    response.set_cookie(COOKIE_NAME, create_session(user, timeout), max_age=timeout * 60, httponly=True, samesite="strict", secure=False)
    return response


@app.post("/api/auth/logout")
async def logout() -> JSONResponse:
    response = JSONResponse({"logged_out": True})
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="strict")
    return response


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
