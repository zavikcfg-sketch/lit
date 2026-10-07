#!/usr/bin/env python3
"""locations 2026-10-07.1 — локации в Remnawave: посмотреть и добавить.

Запускать на основном сервере в контейнере бота:
    docker cp /root/locations.py vpnbot-bot:/tmp/locations.py
    docker exec -w /app vpnbot-bot python /tmp/locations.py --list

Режимы:
  --list                          показать ноды, профили, инбаунды и хосты
  --create --direct                добавить «обычную» локацию на том же сервере,
                                  что и локация за CDN (без нового VPS, бесплатно)
  --create --remark "🇩🇪 Германия (обычный VPN)"
                                  добавить локацию на новой ноде (второй сервер)
        [--node UUID|часть имени] [--inbound UUID|часть тега]
        [--address IP] [--port N] [--sni X] [--security LAYER] [--dry-run]

По умолчанию берётся нода, которая ещё не используется ни в одном хосте, и её
инбаунд (приоритет: reality → tls → остальные). Адрес — это адрес ноды,
порт — порт инбаунда.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

SCRIPT_VERSION = "locations 2026-10-07.2"


def bootstrap_path() -> Path | None:
    env = os.environ.get("VPNBOT_DIR")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates += [Path.cwd(), Path("/app"), Path("/opt/vpnbot/vpn-bot")]
    try:
        candidates.append(Path(__file__).resolve().parents[1])
    except Exception:  # noqa: BLE001
        pass
    for path in candidates:
        try:
            if (path / "app" / "services" / "remnawave.py").is_file():
                return path
        except OSError:
            continue
    return None


APP_ROOT = bootstrap_path()
if APP_ROOT is None:
    print("!! Не нашёл каталог с пакетом app/ (код бота).")
    print("   Запусти так: docker exec -w /app vpnbot-bot python /tmp/locations.py --list")
    sys.exit(2)
sys.path.insert(0, str(APP_ROOT))
print(f"{SCRIPT_VERSION} | корень бота: {APP_ROOT}")


def arg(name: str, default: str | None = None) -> str | None:
    argv = sys.argv[1:]
    key = f"--{name}"
    if key in argv:
        idx = argv.index(key)
        if idx + 1 < len(argv) and not argv[idx + 1].startswith("--"):
            return argv[idx + 1]
        return "1"
    for item in argv:
        if item.startswith(f"{key}="):
            return item.split("=", 1)[1]
    return default


def flag(name: str) -> bool:
    return f"--{name}" in sys.argv[1:]


async def api(remna, method: str, path: str, payload: dict | None = None):
    fn = getattr(remna, "_request", None)
    if not callable(fn):
        raise SystemExit("!! клиент панели без метода _request — обнови код бота")
    return await fn(method, path, json=payload)


def as_list(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("configProfiles", "hosts", "nodes", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def inbound_line(item: dict, index: int) -> str:
    tag = item.get("tag") or "?"
    kind = item.get("type") or "?"
    network = item.get("network") or ""
    security = item.get("security") or ""
    port = item.get("port")
    profile = item.get("profileUuid") or item.get("configProfileUuid") or ""
    return (
        f"     {index}) uuid={item.get('uuid')} tag={tag!r} "
        f"type={kind}{('/' + network) if network else ''}"
        f"{(' security=' + security) if security else ''}"
        f"{(' port=' + str(port)) if port else ''}"
        f"{(' profile=' + profile) if profile else ''}"
    )


async def cmd_list(remna) -> int:
    profiles = as_list(await api(remna, "GET", "/api/config-profiles"))
    nodes = as_list(await api(remna, "GET", "/api/nodes"))
    hosts = as_list(await api(remna, "GET", "/api/hosts"))

    used_nodes: set[str] = set()
    for host in hosts:
        for uuid in host.get("nodes") or []:
            used_nodes.add(str(uuid))

    print("\n=== ПРОФИЛИ КОНФИГУРАЦИИ ===")
    for i, profile in enumerate(profiles, 1):
        print(f"  {i}) {profile.get('name')!r} uuid={profile.get('uuid')}")
        inbounds = profile.get("inbounds") or []
        for j, item in enumerate(inbounds, 1):
            if isinstance(item, dict):
                print(inbound_line(item, j))

    print("\n=== НОДЫ ===")
    for i, node in enumerate(nodes, 1):
        uuid = str(node.get("uuid"))
        cfg = node.get("configProfile") or {}
        active = cfg.get("activeInbounds") or []
        free = "  ← СВОБОДНА (нет ни в одном хосте)" if uuid not in used_nodes else ""
        conn = "🟢" if node.get("isConnected") else "🔴"
        state = "выключена" if node.get("isDisabled") else "включена"
        print(
            f"  {i}) {conn} {node.get('name')!r} address={node.get('address')} "
            f"port={node.get('port')} {state} инбаундов={len(active)}{free}"
        )
        print(f"     uuid={uuid}")
        for j, item in enumerate(active, 1):
            if isinstance(item, dict):
                print(inbound_line(item, j))

    print("\n=== ХОСТЫ (локации для клиентов) ===")
    if not hosts:
        print("  (пусто)")
    for i, host in enumerate(hosts, 1):
        inbound = host.get("inbound") or {}
        print(
            f"  {i}) {host.get('remark')!r} address={host.get('address')} port={host.get('port')} "
            f"{'выключен' if host.get('isDisabled') else 'включён'}"
        )
        print(
            f"     uuid={host.get('uuid')} security={host.get('securityLayer')!r} "
            f"sni={host.get('sni')!r} profile={inbound.get('configProfileUuid')} "
            f"inbound={inbound.get('configProfileInboundUuid')} nodes={host.get('nodes')}"
        )
    print("\nПодсказки:")
    print("  --create --direct — добавить «обычную» локацию на том же сервере (бесплатно)")
    print("  --create --remark \"...\" — локация на НОВОЙ ноде (второй сервер)")
    print("  инбаунд выбирается автоматически: reality → tls → любой")
    return 0


def pick_inbound(node: dict, want: str | None) -> dict | None:
    inbounds = [
        item
        for item in ((node.get("configProfile") or {}).get("activeInbounds") or [])
        if isinstance(item, dict)
    ]
    if not inbounds:
        return None
    if want:
        low = want.lower()
        for item in inbounds:
            if str(item.get("uuid", "")).lower() == low:
                return item
        for item in inbounds:
            if low in str(item.get("tag", "")).lower():
                return item
        print(f"!! инбаунд {want!r} не найден у ноды, беру автоматически")
    def score(item: dict) -> int:
        security = str(item.get("security") or "").lower()
        if "reality" in security:
            return 0
        if "tls" in security:
            return 1
        return 2

    return sorted(inbounds, key=score)[0]


def pick_direct_node(nodes: list, hosts: list, want: str | None) -> dict | None:
    """Нода для «обычной» локации: та же, что уже используется (обычно CDN-локация)."""
    if want:
        return pick_node(nodes, hosts, want)
    order: list[str] = []
    for host in hosts:
        for uuid in host.get("nodes") or []:
            value = str(uuid)
            if value not in order:
                order.append(value)
    for uuid in order:
        for node in nodes:
            if str(node.get("uuid")) == uuid:
                return node
    if len(nodes) == 1:
        return nodes[0]
    if not nodes:
        return None
    print("!! нод несколько — укажи --node uuid. Доступные:")
    for node in nodes:
        print(f"   {node.get('name')!r} uuid={node.get('uuid')} address={node.get('address')}")
    return None


def pick_node(nodes: list, hosts: list, want: str | None) -> dict | None:
    if not nodes:
        return None
    if want:
        low = want.lower()
        for node in nodes:
            if str(node.get("uuid", "")).lower() == low:
                return node
        for node in nodes:
            if low in str(node.get("name", "")).lower():
                return node
        print(f"!! нода {want!r} не найдена")
        return None
    used: set[str] = set()
    for host in hosts:
        for uuid in host.get("nodes") or []:
            used.add(str(uuid))
    free = [node for node in nodes if str(node.get("uuid")) not in used]
    if len(free) == 1:
        return free[0]
    if not free:
        print("!! все ноды уже используются в хостах — укажи --node uuid")
        return None
    print("!! свободных нод несколько — укажи --node uuid. Свободные:")
    for node in free:
        print(f"   {node.get('name')!r} uuid={node.get('uuid')} address={node.get('address')}")
    return None


async def cmd_create(remna) -> int:
    dry = flag("dry-run")
    direct = flag("direct")

    nodes = as_list(await api(remna, "GET", "/api/nodes"))
    hosts = as_list(await api(remna, "GET", "/api/hosts"))

    node = pick_direct_node(nodes, hosts, arg("node")) if direct else pick_node(nodes, hosts, arg("node"))
    if node is None:
        return 1

    remark = arg("remark")
    if not remark:
        if not direct:
            print("!! нужен --remark, например: --remark \"🇩🇪 Германия (обычный VPN)\"")
            return 2
        base = str(node.get("name") or "Локация").strip()
        remark = base if "обычн" in base.lower() else f"{base} (обычный VPN)"

    for host in hosts:
        if str(host.get("remark", "")).strip() == remark.strip():
            print(f"!! локация с названием {remark!r} уже есть (uuid={host.get('uuid')})")
            return 1
    inbound = pick_inbound(node, arg("inbound"))
    if inbound is None:
        print("!! у ноды нет активных инбаундов — проверь её профиль в панели")
        return 1

    address = arg("address") or str(node.get("address") or "")
    port = arg("port") or inbound.get("port")
    if not address:
        print("!! не знаю адрес — укажи --address IP")
        return 1
    try:
        port_int = int(str(port))
    except (TypeError, ValueError):
        print("!! не знаю порт — укажи --port, например --port 443")
        return 1

    inbound_uuid = str(inbound.get("uuid"))
    for host in hosts:
        host_inbound = str((host.get("inbound") or {}).get("configProfileInboundUuid") or "")
        try:
            host_port = int(str(host.get("port")))
        except (TypeError, ValueError):
            host_port = 0
        if (
            host_inbound == inbound_uuid
            and str(host.get("address") or "") == str(address)
            and host_port == port_int
        ):
            print(f"!! такая локация уже есть: {host.get('remark')!r} (uuid={host.get('uuid')})")
            return 1

    payload: dict = {
        "inbound": {
            "configProfileUuid": inbound.get("profileUuid") or inbound.get("configProfileUuid"),
            "configProfileInboundUuid": inbound.get("uuid"),
        },
        "remark": remark,
        "address": address,
        "port": port_int,
        "nodes": [str(node.get("uuid"))],
        "isDisabled": False,
    }
    if arg("sni"):
        payload["sni"] = arg("sni")
    if arg("security"):
        payload["securityLayer"] = arg("security")
    if direct:
        payload["serverDescription"] = arg("server-description") or "Обычное подключение"
    elif arg("server-description"):
        payload["serverDescription"] = arg("server-description")

    print("\nСОЗДАЮ ЛОКАЦИЮ:" + (" (прямое подключение, без CDN)" if direct else ""))
    print(f"  название: {remark}")
    print(f"  нода:     {node.get('name')} ({node.get('uuid')})")
    print(f"  инбаунд:  {inbound.get('tag')} ({inbound.get('uuid')})")
    print(f"  адрес:    {address}:{port_int}")
    print(f"  тело:     {json.dumps(payload, ensure_ascii=False)}")
    if dry:
        print("\n--dry-run: ничего не отправляю")
        return 0

    created = await api(remna, "POST", "/api/hosts", payload)
    created_uuid = created.get("uuid") if isinstance(created, dict) else None
    if not created_uuid:
        print(f"!! панель ответила неожиданно: {created!r}")
        return 1
    print(f"\nГОТОВО: локация создана, uuid={created_uuid}")
    print("Что дальше:")
    print("  1) Клиенты увидят новую локацию после обновления подписки (в приложении — потянуть список вниз).")
    print("  2) В боте: /loc — список локаций, /vpn — моя подписка.")
    print("  3) Если нужна другая страна на втором сервере — та же команда с --remark для неё.")
    return 0


async def main() -> int:
    from app.services.remnawave import get_remna

    try:
        remna = get_remna()
    except Exception as exc:  # noqa: BLE001
        print(f"!! клиент панели не создался: {type(exc).__name__}: {exc}")
        return 1

    mode = "list" if flag("list") or not any(a.startswith("--create") for a in sys.argv) else "create"
    if flag("create"):
        mode = "create"

    try:
        if mode == "list":
            return await cmd_list(remna)
        return await cmd_create(remna)
    except Exception as exc:  # noqa: BLE001
        print(f"!! ошибка: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
