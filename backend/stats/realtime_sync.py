from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict, Optional

from django.db import connections

from settings.models import AgentDisplayMapping, GeneralSettings
from .ami_manager import AMIEvent, AMIManager

logger = logging.getLogger(__name__)

_worker_started = False
_worker_lock = threading.Lock()
_CALLERID_RE = re.compile(r'^\s*"?([^"<]*)"?\s*<\s*([^>]+)\s*>\s*$')
_ENDPOINT_TOKEN_RE = re.compile(r"([A-Za-z0-9_.-]+)")


def _bool_from_ami(value: Any) -> int:
    return 1 if str(value).strip().lower() in {"1", "yes", "true", "on"} else 0


def _normalize_agent(value: str) -> str:
    return str(value or "").strip()


def _extract_endpoint_token(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "/" in raw:
        raw = raw.split("/", 1)[1]
    match = _ENDPOINT_TOKEN_RE.search(raw)
    return match.group(1).strip() if match else ""


def _parse_callerid(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    match = _CALLERID_RE.match(raw)
    if not match:
        return "", ""
    name = match.group(1).strip().strip('"')
    endpoint = _extract_endpoint_token(match.group(2))
    if not name or not endpoint:
        return "", ""
    return name, endpoint


def _extract_callerid_from_endpoint_payload(payload: Dict[str, Any]) -> str:
    for key in ("Callerid", "CallerID", "CallerId", "callerid"):
        value = payload.get(key)
        if value:
            return str(value).strip()

    for key, value in payload.items():
        if "callerid" in str(key).lower() and value:
            return str(value).strip()
    return ""


def _extract_callerid_from_command(payload: Dict[str, Any]) -> str:
    for row in payload.get("output", []):
        for _, value in row.items():
            line = str(value or "").strip()
            if not line or "callerid" not in line.lower():
                continue
            if ":" in line:
                return line.split(":", 1)[1].strip()
    return ""


def _ensure_agent_mapping(system_name: str, display_name: str) -> None:
    system_name = str(system_name or "").strip()
    display_name = str(display_name or "").strip()
    if not system_name or not display_name:
        return

    # UI/manual mapping always has priority: never overwrite existing value.
    AgentDisplayMapping.objects.get_or_create(
        agent_system_name=system_name,
        defaults={"agent_display_name": display_name},
    )


def _sync_agent_mappings_from_pjsip(manager: AMIManager) -> None:
    endpoints = set()

    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT DISTINCT agent FROM agents_new WHERE agent IS NOT NULL AND agent <> ''")
            for (agent,) in cursor.fetchall():
                endpoint = _extract_endpoint_token(agent)
                if endpoint:
                    endpoints.add(endpoint)
    except Exception as exc:
        logger.warning("Failed to collect endpoints from agents_new: %s", exc)

    try:
        endpoint_rows = manager.pjsip_show_endpoints().get("endpoints", [])
        for row in endpoint_rows:
            for key in ("ObjectName", "Endpoint"):
                endpoint = _extract_endpoint_token(row.get(key, ""))
                if endpoint:
                    endpoints.add(endpoint)
    except Exception as exc:
        logger.warning("PJSIPShowEndpoints sync failed: %s", exc)

    for endpoint in sorted(endpoints):
        try:
            payload = manager.pjsip_show_endpoint(endpoint)
            callerid = ""
            for row in payload.get("endpoint", []):
                callerid = _extract_callerid_from_endpoint_payload(row)
                if callerid:
                    break
            if not callerid:
                callerid = _extract_callerid_from_command(manager.command(f"pjsip show endpoint {endpoint}"))

            display_name, ext = _parse_callerid(callerid)
            if not (display_name and ext):
                continue

            _ensure_agent_mapping(ext, display_name)
            _ensure_agent_mapping(f"PJSIP/{ext}", display_name)
            if endpoint != ext:
                _ensure_agent_mapping(endpoint, display_name)
                _ensure_agent_mapping(f"PJSIP/{endpoint}", display_name)
        except Exception as exc:
            logger.warning("PJSIP endpoint mapping sync failed for %s: %s", endpoint, exc)


def _upsert_queue(queue_name: str, descr: str = "") -> None:
    if not queue_name:
        return
    with connections["default"].cursor() as cursor:
        try:
            cursor.execute(
                """
                INSERT INTO queues_new (queuename, descr)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE descr = VALUES(descr)
                """,
                [queue_name, descr or queue_name],
            )
        except Exception:
            cursor.execute(
                """
                INSERT INTO queues_new (queuename)
                VALUES (%s)
                ON DUPLICATE KEY UPDATE queuename = VALUES(queuename)
                """,
                [queue_name],
            )


def _upsert_agent(agent: str, name: str = "") -> None:
    if not agent:
        return
    with connections["default"].cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO agents_new (agent, name)
            VALUES (%s, NULLIF(%s, ''))
            ON DUPLICATE KEY UPDATE name = IF(VALUES(name) IS NULL, name, VALUES(name))
            """,
            [agent, name],
        )


def _upsert_member(queue_name: str, interface: str, penalty: int = 0, paused: int = 0, member_name: str = "") -> None:
    if not queue_name or not interface:
        return
    _upsert_queue(queue_name, queue_name)
    _upsert_agent(interface, member_name)
    with connections["default"].cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO queue_members (queue_name, interface, penalty, paused, member_name)
            VALUES (%s, %s, %s, %s, NULLIF(%s, ''))
            ON DUPLICATE KEY UPDATE
              penalty = VALUES(penalty),
              paused = VALUES(paused),
              member_name = IF(VALUES(member_name) IS NULL, member_name, VALUES(member_name))
            """,
            [queue_name, interface, int(penalty), int(paused), member_name],
        )


def _delete_member(queue_name: str, interface: str) -> None:
    if not queue_name or not interface:
        return
    with connections["default"].cursor() as cursor:
        cursor.execute("DELETE FROM queue_members WHERE queue_name = %s AND interface = %s", [queue_name, interface])


def ensure_runtime_tables() -> None:
    with connections["default"].cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS queue_members (
              id BIGINT NOT NULL AUTO_INCREMENT,
              queue_name VARCHAR(128) NOT NULL,
              interface VARCHAR(255) NOT NULL,
              penalty INT NOT NULL DEFAULT 0,
              paused TINYINT(1) NOT NULL DEFAULT 0,
              member_name VARCHAR(255) NULL,
              PRIMARY KEY (id),
              UNIQUE KEY uq_queue_member (queue_name, interface),
              KEY idx_queue_name (queue_name),
              KEY idx_interface (interface)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cursor.execute("SHOW COLUMNS FROM queue_members LIKE 'member_name'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE queue_members ADD COLUMN member_name VARCHAR(255) NULL")
        cursor.execute("SHOW COLUMNS FROM queue_members LIKE 'penalty'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE queue_members ADD COLUMN penalty INT NOT NULL DEFAULT 0")
        cursor.execute("SHOW COLUMNS FROM queue_members LIKE 'paused'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE queue_members ADD COLUMN paused TINYINT(1) NOT NULL DEFAULT 0")
        cursor.execute("SHOW INDEX FROM queue_members WHERE Key_name = 'uq_queue_member'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE queue_members ADD UNIQUE KEY uq_queue_member (queue_name, interface)")


def _full_sync_from_ami(manager: AMIManager) -> None:
    try:
        payload = manager.queue_status()
    except Exception as exc:
        logger.warning("QueueStatus sync failed: %s", exc)
        return

    for queue in payload.get("queues", []):
        queue_name = str(queue.get("Queue", "")).strip()
        if not queue_name:
            continue
        _upsert_queue(queue_name, queue_name)
        for member in queue.get("members", []):
            interface = _normalize_agent(str(member.get("Location") or member.get("Interface") or ""))
            member_name = str(member.get("MemberName") or member.get("Name") or "")
            _upsert_member(
                queue_name=queue_name,
                interface=interface,
                penalty=int(member.get("Penalty") or 0),
                paused=_bool_from_ami(member.get("Paused", 0)),
                member_name=member_name,
            )


def _handle_ami_event(event: AMIEvent) -> None:
    event_type = str(event.get("Event", "")).strip()
    queue_name = str(event.get("Queue", "")).strip()
    interface = _normalize_agent(str(event.get("Interface") or event.get("Location") or ""))
    member_name = str(event.get("MemberName") or event.get("Name") or "")

    if event_type in {"QueueParams", "QueueSummary"}:
        _upsert_queue(queue_name, queue_name)
        return

    if event_type in {"QueueMember", "QueueMemberAdded", "QueueMemberStatus", "QueueMemberPause"}:
        _upsert_member(
            queue_name=queue_name,
            interface=interface,
            penalty=int(event.get("Penalty") or 0),
            paused=_bool_from_ami(event.get("Paused", 0)),
            member_name=member_name,
        )
        return

    if event_type == "QueueMemberRemoved":
        _delete_member(queue_name, interface)


class _RealtimeSyncWorker(threading.Thread):
    daemon = True

    def run(self) -> None:
        while True:
            try:
                ensure_runtime_tables()
                settings = GeneralSettings.objects.first()
                if not settings or not settings.ami_host:
                    time.sleep(5)
                    continue

                manager = AMIManager(
                    host=settings.ami_host,
                    port=settings.ami_port,
                    username=settings.ami_user,
                    secret=settings.ami_password,
                )
                if not manager.connect():
                    time.sleep(5)
                    continue

                manager.on_event(_handle_ami_event)
                _full_sync_from_ami(manager)
                _sync_agent_mappings_from_pjsip(manager)

                while manager.authenticated and manager.running:
                    time.sleep(1)
                manager.disconnect()
            except Exception as exc:
                logger.warning("Realtime sync worker error: %s", exc)
                time.sleep(5)


def start_realtime_sync_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        worker = _RealtimeSyncWorker(name="ami-realtime-sync")
        worker.start()
        _worker_started = True
