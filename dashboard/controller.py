"""Coordinate existing layers for the web-based learning environment."""

from __future__ import annotations

import asyncio
import os
import platform
import sys
import time
from contextlib import suppress
from datetime import datetime, timezone

from machine import MachineSimulator, PLCSimulator
from mes.config import load_settings, save_settings
from mes.main import build_processor, build_rules
from mes.opc_client import MESOPCClient
from mes.mqtt_client import MESMQTTTransport
from mes.production import ProductionOrder, ProductionStatus
from opc.server import OPCUAServer
from .logging_config import recent_errors

DEFAULT_SECURITY = {
    "dashboard": {"authentication_enabled": False, "session_timeout_minutes": 30, "audit_enabled": True},
    "opc_ua": {"security_mode": "None", "security_policy": "None", "certificate_path": "", "private_key_path": "", "server_certificate_path": "", "server_private_key_path": "", "trusted_certificates_path": ""},
    "mqtt": {"tls_enabled": False, "username": "", "ca_certificate_path": "", "client_certificate_path": "", "client_key_path": ""},
}


class SimulationController:
    def __init__(self, endpoint: str | None = None, persist: bool = True, update_interval: float | None = None) -> None:
        self.settings = load_settings()
        self.settings.setdefault("security", {section: values.copy() for section, values in DEFAULT_SECURITY.items()})
        endpoint_overridden = endpoint is not None
        endpoint = endpoint or self.settings["opc_endpoint"]
        self.machine = MachineSimulator(
            production_interval_ticks=self.settings["production_interval_ticks"]
        )
        self.plc = PLCSimulator(self.machine)
        self.opc_server = OPCUAServer(self.plc, endpoint, self.settings["security"]["opc_ua"])
        self.processor = build_processor(persist=persist)
        self.mes_client = MESOPCClient(endpoint, self.processor, self.settings["security"]["opc_ua"])
        mqtt_host = os.getenv("MES_MQTT_HOST", self.settings.get("mqtt_broker_host", "127.0.0.1"))
        mqtt_port = int(os.getenv("MES_MQTT_PORT", str(self.settings.get("mqtt_broker_port", 1883))))
        self.mqtt_transport = MESMQTTTransport(self.plc, self.processor, mqtt_host, mqtt_port, self.settings.get("mqtt_topic_prefix", "factory/machine-01"), self.settings["security"]["mqtt"])
        self.communication_mode = "OPC_UA" if endpoint_overridden else self.settings["communication_mode"]
        self.update_interval = update_interval or self.settings["simulation_update_interval"]
        self.simulation_running = False
        self.opc_connected = False
        self._task: asyncio.Task | None = None
        self.production_orders: list[ProductionOrder] = []
        self.active_order: ProductionOrder | None = None
        self._last_machine_count = self.machine.production_count
        self._started_at = time.monotonic()

    async def start(self) -> None:
        await self.opc_server.start()
        if self.communication_mode == "MQTT":
            self.mqtt_transport.start()
        else:
            await self.mes_client.start()
            self.opc_connected = True
        self.simulation_running = True
        self._task = asyncio.create_task(self._simulation_loop())

    async def shutdown(self) -> None:
        self.simulation_running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        if self.opc_connected:
            await self.mes_client.stop()
            self.opc_connected = False
        self.mqtt_transport.stop()
        await self.opc_server.stop()

    async def _simulation_loop(self) -> None:
        while True:
            if self.simulation_running:
                self.machine.tick()
                await self.opc_server.publish_scan()
                if self.communication_mode == "MQTT":
                    self.mqtt_transport.publish_scan()
                self._update_production_order()
            await asyncio.sleep(self.update_interval)

    def _update_production_order(self) -> None:
        produced = max(0, self.machine.production_count - self._last_machine_count)
        self._last_machine_count = self.machine.production_count
        order = self.active_order
        if order is None or order.status != ProductionStatus.RUNNING:
            return
        order.elapsed_seconds += self.update_interval
        if self.machine.state.value == "RUNNING":
            order.operating_seconds += self.update_interval
        if produced:
            order.record_good(produced)
            if self.processor.persistence is not None:
                self.processor.persistence.persist_production_record(order)
        if order.total_quantity >= order.target_quantity:
            self.complete_production_order(order.order_id)

    async def start_simulation(self) -> None:
        self.simulation_running = True

    async def pause_simulation(self) -> None:
        self.simulation_running = False

    async def start_machine(self) -> None:
        self.machine.start()
        await self.opc_server.publish_scan()

    async def stop_machine(self) -> None:
        self.machine.stop()
        await self.opc_server.publish_scan()

    async def reset_machine(self) -> None:
        self.machine.reset()
        await self.opc_server.publish_scan()

    def raise_pressure(self) -> None:
        self.machine.raise_pressure()

    def raise_temperature(self) -> None:
        self.machine.raise_temperature()

    def configuration(self) -> dict:
        return self.settings.copy()

    def apply_configuration(self, settings: dict) -> dict:
        restart_required = (
            settings["opc_endpoint"] != self.settings["opc_endpoint"]
            or settings["communication_mode"]
            != self.settings["communication_mode"]
            or settings["mqtt_broker_host"] != self.settings.get("mqtt_broker_host")
            or settings["mqtt_broker_port"] != self.settings.get("mqtt_broker_port")
            or settings["mqtt_topic_prefix"] != self.settings.get("mqtt_topic_prefix")
        )
        security = self.settings.get("security", DEFAULT_SECURITY)
        self.settings = {**settings, "security": security}
        self.update_interval = settings["simulation_update_interval"]
        self.machine.production_interval_ticks = settings[
            "production_interval_ticks"
        ]
        self.processor.rule_engine.update_rules(build_rules(settings))
        save_settings(self.settings)
        return {"settings": self.configuration(), "restart_required": restart_required}

    def security_configuration(self) -> dict:
        import os
        security = self.settings["security"]
        return {
            **security,
            "secrets": {
                "dashboard_secret_configured": bool(os.getenv("MES_DASHBOARD_SECRET")),
                "mqtt_password_configured": bool(os.getenv("MES_MQTT_PASSWORD")),
            },
        }

    def apply_security_configuration(self, security: dict) -> dict:
        self.settings["security"] = security
        save_settings(self.settings)
        return {"security": self.security_configuration(), "restart_required": True}

    async def switch_communication(self, mode: str) -> None:
        if mode == self.communication_mode:
            return
        if mode == "MQTT":
            if self.opc_connected:
                await self.mes_client.stop()
                self.opc_connected = False
            self.mqtt_transport.start()
        else:
            self.mqtt_transport.stop()
            await self.mes_client.start()
            self.opc_connected = True
        self.communication_mode = mode
        self.settings["communication_mode"] = mode
        save_settings(self.settings)

    def acknowledge_alarm(self, alarm_id: str, operator: str):
        alarm = self.processor.alarm_manager.acknowledge(
            alarm_id, operator, datetime.now(timezone.utc)
        )
        if alarm is not None and self.processor.persistence is not None:
            self.processor.persistence.acknowledge_alarm(alarm)
        return alarm

    def start_task(self, task_id: int):
        task = self.processor.task_manager.start(task_id)
        if task is not None and self.processor.persistence is not None:
            self.processor.persistence.update_task(task)
        return task

    def complete_task(self, task_id: int):
        task = self.processor.task_manager.complete(task_id)
        if task is not None and self.processor.persistence is not None:
            self.processor.persistence.update_task(task)
        return task

    def create_production_order(self, order_id: str, product_name: str, target_quantity: int):
        if any(order.order_id == order_id for order in self.production_orders):
            raise ValueError("Production order ID already exists")
        order = ProductionOrder(order_id, product_name, target_quantity)
        self.production_orders.append(order)
        if self.processor.persistence is not None:
            self.processor.persistence.persist_production_order(order, self.machine.machine_id)
        return order

    def start_production_order(self, order_id: str):
        if self.active_order is not None and self.active_order.status == ProductionStatus.RUNNING:
            raise ValueError("Another production order is already running")
        order = next((item for item in self.production_orders if item.order_id == order_id), None)
        if order is None:
            return None
        order.start()
        self.active_order = order
        self._last_machine_count = self.machine.production_count
        if self.processor.persistence is not None:
            self.processor.persistence.update_production_order(order)
        return order

    def reject_production_part(self, order_id: str):
        order = next((item for item in self.production_orders if item.order_id == order_id), None)
        if order is None:
            return None
        order.reject_one()
        if self.processor.persistence is not None:
            self.processor.persistence.persist_production_record(order)
        return order

    def complete_production_order(self, order_id: str):
        order = next((item for item in self.production_orders if item.order_id == order_id), None)
        if order is None:
            return None
        order.complete()
        if self.active_order is order:
            self.active_order = None
        if self.processor.persistence is not None:
            self.processor.persistence.update_production_order(order)
        return order

    def database_snapshot(self) -> dict:
        if self.processor.persistence is None:
            return {"readings": [], "events": [], "alarms": [], "tasks": [], "audit": [], "actions": [], "orders": [], "production": []}
        return self.processor.persistence.database_snapshot()

    def health(self) -> dict:
        transport_connected = self.mqtt_transport.connected if self.communication_mode == "MQTT" else self.opc_connected
        return {"status": "healthy" if transport_connected else "starting", "transport": self.communication_mode, "transport_connected": transport_connected, "database_configured": self.processor.persistence is not None}

    def diagnostics(self) -> dict:
        database_connected = False
        database_error = None
        if self.processor.persistence is not None:
            try:
                database_connected = self.processor.persistence.health_check()
            except Exception as error:
                database_error = type(error).__name__
        return {
            "overall": "HEALTHY" if self.health()["transport_connected"] and database_connected else "DEGRADED",
            "services": {
                "dashboard": {"connected": True, "detail": "API process responding"},
                "database": {"connected": database_connected, "detail": database_error or "SELECT 1 succeeded"},
                "transport": {"connected": self.health()["transport_connected"], "detail": self.communication_mode},
                "opc_ua": {"connected": self.opc_connected, "detail": self.settings["security"]["opc_ua"]["security_mode"]},
                "mqtt": {"connected": self.mqtt_transport.connected, "detail": f"{self.mqtt_transport.host}:{self.mqtt_transport.port}"},
            },
            "runtime": {
                "containerized": bool(os.getenv("MES_CONTAINERIZED")),
                "python": platform.python_version(),
                "platform": platform.system(),
                "process_id": os.getpid(),
                "uptime_seconds": round(time.monotonic() - self._started_at, 1),
                "executable": sys.executable,
            },
            "recent_errors": recent_errors(),
        }

    def audit_operator_action(self, username: str, role: str, method: str, path: str, status: int, client_address: str | None) -> None:
        dashboard_security = self.settings["security"]["dashboard"]
        if not dashboard_security.get("audit_enabled") or self.processor.persistence is None:
            return
        self.processor.persistence.persist_operator_action(username, role, method, path, status, client_address)

    def snapshot(self) -> dict:
        tags = self.processor.latest_tags
        alarms = [{"id": a.alarm_id, "type": a.alarm_type, "severity": a.severity, "message": a.message, "status": a.status.value, "acknowledged": a.acknowledged, "acknowledged_by": a.acknowledged_by, "acknowledged_time": a.acknowledged_time.isoformat() if a.acknowledged_time else None, "triggered_time": a.triggered_time.isoformat(), "resolved_time": a.resolved_time.isoformat() if a.resolved_time else None} for a in self.processor.alarm_manager.alarms[-20:]]
        events = [{"type": e.event_type.value, "condition": e.condition, "value": e.value, "time": e.occurred_at.isoformat()} for e in self.processor.events[-20:]]
        tasks = [{"id": t.task_id, "alarm_id": t.related_alarm_id, "description": t.description, "priority": t.priority, "status": t.status.value, "created_time": t.created_time.isoformat(), "completed_time": t.completed_time.isoformat() if t.completed_time else None} for t in self.processor.task_manager.tasks[-20:]]
        ideal_cycle_seconds = self.update_interval * self.machine.production_interval_ticks
        orders = [{"id": o.order_id, "product_name": o.product_name, "target_quantity": o.target_quantity, "status": o.status.value, "total_quantity": o.total_quantity, "good_quantity": o.good_quantity, "rejected_quantity": o.rejected_quantity, "started_time": o.started_time.isoformat() if o.started_time else None, "completed_time": o.completed_time.isoformat() if o.completed_time else None, "oee": o.oee(ideal_cycle_seconds)} for o in reversed(self.production_orders[-20:])]
        return {
            "simulation": "RUNNING" if self.simulation_running else "PAUSED",
            "machine_id": self.machine.machine_id,
            "machine_status": tags.get("Machine01.Status", self.machine.state.value),
            "pressure": tags.get("Machine01.Pressure", self.machine.pressure),
            "temperature": tags.get("Machine01.Temperature", self.machine.temperature),
            "rpm": tags.get("Machine01.RPM", self.machine.rpm),
            "production_count": tags.get("Machine01.ProductionCount", self.machine.production_count),
            "opc_connected": self.opc_connected,
            "opc_endpoint": self.opc_server.endpoint,
            "opc_security_mode": self.settings["security"]["opc_ua"]["security_mode"],
            "opc_security_policy": self.settings["security"]["opc_ua"]["security_policy"],
            "opc_secure_channel": self.opc_connected and self.settings["security"]["opc_ua"]["security_mode"] != "None",
            "communication_mode": self.communication_mode,
            "communication_connected": self.mqtt_transport.connected if self.communication_mode == "MQTT" else self.opc_connected,
            "mqtt_broker": f"{self.mqtt_transport.host}:{self.mqtt_transport.port}",
            "mqtt_topic_prefix": self.mqtt_transport.prefix,
            "mqtt_messages": list(self.mqtt_transport.messages),
            "traces": list(self.processor.traces),
            "important_traces": list(self.processor.important_traces),
            "subscribed_tags": len(tags),
            "alarms": alarms,
            "events": events,
            "tasks": tasks,
            "production_orders": orders,
        }
