#!/usr/bin/env python3
"""
Hub 2.0 - Auto Booking ⚡
Multi-conta, sniper, espiao, radar, ranking — tudo via API direta.
Mais rapido que o app — reserva em milissegundos.

Uso interativo:  python3 auto_booking.py
Modo sniper:     python3 auto_booking.py --sniper --area 17 --data 2026-04-03 --hora 20:00
Modo radar:      python3 auto_booking.py --radar --area 17 --data 2026-03-27 --hora 20:00
Ranking bots:    python3 auto_booking.py --ranking --dias 14
Ver horarios:    python3 auto_booking.py --area 17 --data 2026-03-27
Listar espacos:  python3 auto_booking.py --listar
Minhas reservas: python3 auto_booking.py --minhas
Cancelar:        python3 auto_booking.py --cancelar 1332211
Espiao:          python3 auto_booking.py --espiao 2026-03-20
Trocar reserva:  python3 auto_booking.py --trocar 1332211
Usar conta N:    python3 auto_booking.py --conta 2 --minhas
"""

import argparse
import base64
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

# ===== CONFIG =====
CONFIG_PATH = Path(__file__).parent / "accounts.json"
API_ACCOUNTS = "https://api-accounts.hubert.com.br"
API_MORADOR = "https://api-morador.hubert.com.br"

# ===== ANSI =====
R = "\033[91m"
G = "\033[92m"
Y = "\033[93m"
B = "\033[94m"
C = "\033[96m"
M = "\033[95m"
W = "\033[97m"
DIM = "\033[90m"
BOLD = "\033[1m"
RST = "\033[0m"


# ===== ACCOUNT =====


@dataclass
class Account:
    label: str
    cpf: str
    senha: str
    condominio: int
    unidade: str
    token: str = field(default="", repr=False)
    nome: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "cpf": self.cpf,
            "senha": self.senha,
            "condominio": self.condominio,
            "unidade": self.unidade,
        }


def load_accounts() -> list[Account]:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            return [Account(**d) for d in data]
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            print(f"  {R}Erro ao ler {CONFIG_PATH}: {e}{RST}")
    return []


def save_accounts(accounts: list[Account]) -> None:
    CONFIG_PATH.write_text(
        json.dumps([a.to_dict() for a in accounts], indent=2, ensure_ascii=False)
        + "\n"
    )


# ===== HUB CLIENT =====


class HubClient:
    def __init__(self, account: Account) -> None:
        self.account = account
        self.session = requests.Session()
        self.session.headers.update(
            {"Origin": "app-morador", "Content-Type": "application/json"}
        )

    @property
    def logged_in(self) -> bool:
        return bool(self.account.token)

    def login(self) -> bool:
        creds = base64.b64encode(
            f"{self.account.cpf}:{self.account.senha}".encode()
        ).decode()
        try:
            r = self.session.post(
                f"{API_ACCOUNTS}/api/v1/login",
                headers={"Authorization": f"Base {creds}"},
            )
            if r.status_code != 200:
                return False
            data = r.json()
            self.account.token = data["token"]
            self.account.nome = data["nome"]
            self.session.headers["Authorization"] = f"Bearer {data['token']}"
            return True
        except Exception as e:
            print(f"  {R}Erro login: {e}{RST}")
            return False

    def listar_areas(self) -> list[dict]:
        r = self.session.get(
            f"{API_MORADOR}/api/v1/areas",
            params={"codigoCondominio": self.account.condominio},
        )
        r.raise_for_status()
        return r.json()

    def ver_horarios(self, area: int, data: str) -> list[dict]:
        unidade = quote(self.account.unidade, safe="")
        url = (
            f"{API_MORADOR}/api/v1/areas/{area}/datasDisponiveis"
            f"?codigoCondominio={self.account.condominio}"
            f"&unidade={unidade}"
            f"&dataInicial={data}T00:00:00"
            f"&dataFinal={data}T23:59:00"
        )
        r = self.session.get(url)
        if r.status_code == 400:
            body = r.json()
            msg = body[0] if isinstance(body, list) else body
            if "quantidade de reservas" in str(msg).lower():
                print(
                    f"  {Y}⚠️  Reserva ativa nessa area! Use outra conta pra consultar.{RST}"
                )
            else:
                print(f"  {Y}⚠️  {msg}{RST}")
            return []
        r.raise_for_status()
        slots = []
        for dia in r.json().get("datas", []):
            for p in dia.get("periodos", []):
                slots.append(
                    {
                        "inicio": p["dataInicio"],
                        "fim": p["dataTermino"],
                        "vagas": p["quantidadeDeVagas"],
                    }
                )
        return slots

    def reservar(self, area: int, inicio: str, fim: str) -> dict:
        # Sanitiza datas: remove ms e Z pra garantir formato local
        inicio = inicio.split(".")[0].replace("Z", "")
        fim = fim.split(".")[0].replace("Z", "")
        try:
            r = self.session.post(
                f"{API_MORADOR}/api/v1/reservas",
                json={
                    "codigoArea": area,
                    "codigoCondominio": self.account.condominio,
                    "unidade": self.account.unidade,
                    "quantPessoas": 1,
                    "dataReserva": [{"dataInicial": inicio, "dataFinal": fim}],
                    "observacoes": "",
                },
            )
            return {"status": r.status_code, "body": r.json()}
        except Exception as e:
            return {"status": 0, "body": f"Erro: {e}"}

    def cancelar(self, codigo: int) -> dict:
        try:
            r = self.session.post(
                f"{API_MORADOR}/api/v1/reservas/{codigo}/cancelar",
                json={"motivo": "Aplicativo morador"},
            )
            return {"status": r.status_code, "body": r.json()}
        except Exception as e:
            return {"status": 0, "body": f"Erro: {e}"}

    def minhas_reservas(self) -> list[dict]:
        r = self.session.get(f"{API_MORADOR}/api/v1/reservas")
        r.raise_for_status()
        return [
            x
            for x in r.json()
            if x["condominio"]["codigo"] == self.account.condominio
            and x["unidade"] == self.account.unidade
            and x["situacao"]["codigo"] == 2
        ]

    def todas_reservas_condo(self) -> list[dict]:
        r = self.session.get(f"{API_MORADOR}/api/v1/reservas")
        r.raise_for_status()
        return [
            x for x in r.json() if x["condominio"]["codigo"] == self.account.condominio
        ]


# ===== DISPLAY FUNCTIONS =====


def banner() -> None:
    print(
        f"""
{C}╔══════════════════════════════════════════╗
║     {W}{BOLD}🏢 HUB 2.0 - AUTO BOOKING ⚡{RST}{C}        ║
║     {DIM}Reserva na velocidade da API{RST}{C}         ║
╚══════════════════════════════════════════╝{RST}"""
    )


def pick_client(clients: list[HubClient], prompt: str = "Conta") -> HubClient | None:
    if not clients:
        print(f"  {R}Nenhuma conta configurada.{RST}")
        return None
    if len(clients) == 1:
        return clients[0]
    print(f"\n  {C}Contas disponiveis:{RST}")
    for i, c in enumerate(clients, 1):
        status = f"{G}✅{RST}" if c.logged_in else f"{R}❌{RST}"
        nome = c.account.nome or c.account.cpf
        print(f"    {i}. {status} {c.account.label} — {nome} | {c.account.unidade}")
    while True:
        try:
            n = input(f"  {prompt} [1]: ").strip() or "1"
            idx = int(n) - 1
            if 0 <= idx < len(clients):
                return clients[idx]
            print(f"  {DIM}Escolha entre 1 e {len(clients)}{RST}")
        except ValueError:
            print(f"  {DIM}Digite um numero{RST}")
        except KeyboardInterrupt:
            return None


def mostrar_areas(client: HubClient) -> None:
    areas = client.listar_areas()
    tipos: dict[str, list] = {}
    for a in areas:
        t = a.get("tipoArea", {}).get("descricao", "Outros")
        tipos.setdefault(t, []).append(a)

    print(f"\n  {BOLD}{'Cod':>4}  {'Espaco':<40}  {'Tipo'}{RST}")
    print(f"  {'=' * 65}")
    for tipo in sorted(tipos):
        print(f"\n  {C}── {tipo} ──{RST}")
        for a in sorted(tipos[tipo], key=lambda x: x.get("codigoArea", 0)):
            cod = a.get("codigoArea", a.get("codigo", "?"))
            nome = a.get("nomeArea", a.get("descricao", "?")).strip()
            print(f"  {cod:>4}  {nome}")


def mostrar_horarios(client: HubClient, area: int, data: str) -> list[dict]:
    slots = client.ver_horarios(area, data)
    if not slots:
        print(f"\n  {R}❌ Sem horarios disponiveis em {data}{RST}")
        return []
    print(f"\n  {C}📅 Area {area} — {data}{RST}\n")
    for i, s in enumerate(slots, 1):
        h_ini = s["inicio"][11:16]
        h_fim = s["fim"][11:16]
        v = s["vagas"]
        icon = f"{G}✅{RST}" if v > 0 else f"{R}❌{RST}"
        print(
            f"  {i:>3}. {icon} {h_ini} - {h_fim}  ({v} vaga{'s' if v != 1 else ''})"
        )
    return slots


def espiao(client: HubClient, data_filtro: str) -> None:
    print(f"\n  {M}🕵️  MODO ESPIAO — reservas para {data_filtro}{RST}\n")
    reservas = client.todas_reservas_condo()

    filtradas = [
        r for r in reservas if r.get("dataInicial", "").startswith(data_filtro)
    ]
    if not filtradas:
        print("  Nenhuma reserva encontrada para essa data.")
        return

    filtradas.sort(key=lambda x: x.get("dataSolicitacao", ""))

    print(
        f"  {DIM}{'Solicitado em':>26}  {'Area':<28}  {'Horario':>11}  {'Nome':<28}  {'Unid'}{RST}"
    )
    print(f"  {'-' * 110}")

    for r in filtradas:
        sol = r.get("dataSolicitacao", "?")
        area = r["area"]["descricao"].strip()[:27]
        h_ini = r["dataInicial"][11:16]
        h_fim = r["dataFinal"][11:16]
        nome = r["nome"][:27]
        unid = r["unidade"]

        badge = ""
        if len(sol) >= 19:
            h = int(sol[11:13])
            m = int(sol[14:16])
            s = int(sol[17:19])
            if h == 0 and m == 0 and s <= 30:
                badge = f" {R}{BOLD}⚡ SPEED{RST}"
            elif h == 0 and m <= 1:
                badge = f" {Y}🏎️ RAPIDO{RST}"

        print(
            f"  {sol:>26}{badge}  {area:<28}  {h_ini}-{h_fim:>5}  {nome:<28}  {unid}"
        )

    rapidos = []
    for r in filtradas:
        sol = r.get("dataSolicitacao", "")
        if len(sol) < 19:
            continue
        h = int(sol[11:13])
        m = int(sol[14:16])
        if h == 0 and m <= 1:
            rapidos.append(r)

    if rapidos:
        print(f"\n  {Y}{BOLD}🏎️  {len(rapidos)} reservas nos primeiros 60 segundos!{RST}")
        print(f"  {DIM}Mais rapido: {rapidos[0].get('dataSolicitacao', '?')}{RST}")


def sniper(
    client: HubClient, area: int, data: str, hora: str, disparo: str = "00:00"
) -> None:
    h, m = map(int, hora.split(":"))
    dt = datetime.strptime(data, "%Y-%m-%d").replace(hour=h, minute=m)
    inicio = dt.strftime("%Y-%m-%dT%H:%M:%S")
    fim = (dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")

    h_d, m_d = map(int, disparo.split(":"))
    agora = datetime.now()
    alvo = agora.replace(hour=h_d, minute=m_d, second=0, microsecond=0)
    if alvo <= agora:
        alvo += timedelta(days=1)

    print(f"\n  {G}{BOLD}🎯 MODO SNIPER ATIVADO{RST}")
    print(f"  {C}📍 Area {area} | 📅 {data} {hora}{RST}")
    print(f"  {C}👤 {client.account.label} ({client.account.nome}){RST}")
    print(f"  {Y}⏰ Disparo as {alvo.strftime('%H:%M:%S')}{RST}")
    print(f"  {DIM}⏳ Ctrl+C para cancelar{RST}\n")

    relogged = False
    try:
        while True:
            agora = datetime.now()
            restante = (alvo - agora).total_seconds()
            if restante <= 0:
                break
            if restante <= 5 and not relogged:
                print(f"\n  {B}🔄 Renovando token...{RST}", end=" ", flush=True)
                if client.login():
                    print(f"{G}OK{RST}")
                else:
                    print(f"{R}FALHOU — disparando com token atual{RST}")
                relogged = True
            h_, r_ = divmod(int(restante), 3600)
            m_, s_ = divmod(r_, 60)
            color = R if restante <= 10 else Y if restante <= 60 else C
            print(
                f"\r  {color}⏱️  {h_:02d}:{m_:02d}:{s_:02d}{RST}  ",
                end="",
                flush=True,
            )
            time.sleep(0.1)
    except KeyboardInterrupt:
        print(f"\n\n  {Y}Cancelado.{RST}")
        return

    ts_disparo = datetime.now().strftime("%H:%M:%S.%f")[:12]
    print(f"\n\n  {G}{BOLD}🚀 DISPARANDO! [{ts_disparo}]{RST}")

    for i in range(1, 11):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
        r = client.reservar(area, inicio, fim)
        if r["status"] == 200:
            cod = r["body"].get("codigoReserva")
            print(f"\n  {G}{BOLD}✅ RESERVA CONFIRMADA as {ts}!{RST}")
            print(f"  {G}📋 Codigo: {cod}{RST}")
            print(f"  {G}📅 {data} {hora}{RST}")
            return
        msg = r["body"]
        if isinstance(msg, list):
            msg = msg[0]
        print(f"  {R}❌ Tentativa {i} [{ts}]: {msg}{RST}")
        if "não está disponível" in str(msg).lower():
            print(f"  {R}{BOLD}💀 Ja pegaram!{RST}")
            return
        time.sleep(0.02)

    print(f"  {R}{BOLD}💀 Falhou apos 10 tentativas.{RST}")


def radar(
    client: HubClient,
    consult: HubClient,
    area: int,
    data: str,
    hora: str | None = None,
    intervalo: int = 5,
) -> None:
    """Monitora area por cancelamentos e auto-reserva quando abrir."""
    print(f"\n  {M}{BOLD}📡 MODO RADAR — Monitorando cancelamentos{RST}")
    print(f"  {C}📍 Area {area} | 📅 {data}{RST}")
    if hora:
        print(f"  {C}🎯 Alvo: {hora}{RST}")
    print(f"  {C}👤 Reserva: {client.account.label} | Consulta: {consult.account.label}{RST}")
    print(f"  {DIM}🔄 Poll a cada {intervalo}s | Ctrl+C pra parar{RST}\n")

    ciclo = 0
    ultimo_estado: dict[str, int] = {}

    try:
        while True:
            ciclo += 1
            ts = datetime.now().strftime("%H:%M:%S")

            # Refresh token a cada 50 ciclos (~4min)
            if ciclo % 50 == 0:
                consult.login()
                if client is not consult:
                    client.login()

            slots = consult.ver_horarios(area, data)
            if not slots:
                print(
                    f"\r  {DIM}[{ts}] #{ciclo} — sem slots disponiveis (area bloqueada?){RST}  ",
                    end="",
                    flush=True,
                )
                time.sleep(intervalo)
                continue

            estado_atual = {s["inicio"][11:16]: s for s in slots}

            # Detectar slots que abriram (vagas > 0 e antes era 0 ou não existia)
            novos = []
            for h, s in estado_atual.items():
                if s["vagas"] > 0:
                    vagas_antes = ultimo_estado.get(h, 0)
                    if vagas_antes == 0 and ciclo > 1:
                        novos.append(s)

            # Filtrar por hora-alvo se especificada
            if hora and novos:
                target = hora.zfill(5)
                novos = [s for s in novos if s["inicio"][11:16] == target]

            # Se não tem novos mas é primeiro ciclo, checar se já tem vaga
            if ciclo == 1 and not novos:
                if hora:
                    target = hora.zfill(5)
                    for h, s in estado_atual.items():
                        if h == target and s["vagas"] > 0:
                            novos.append(s)
                # Se não tem hora-alvo no primeiro ciclo, não auto-reserva
                # (senão pega qualquer slot que já tava disponível)

            if novos:
                for s in novos:
                    h_display = s["inicio"][11:16]
                    print(f"\n\n  {G}{BOLD}📡 SLOT ABRIU! {h_display} disponivel!{RST}")
                    print(
                        f"  {G}🚀 Auto-reservando com {client.account.label}...{RST}"
                    )

                    # Refresh token antes de reservar
                    client.login()

                    for attempt in range(1, 6):
                        ts_try = datetime.now().strftime("%H:%M:%S.%f")[:12]
                        r = client.reservar(area, s["inicio"], s["fim"])
                        if r["status"] == 200:
                            cod = r["body"].get("codigoReserva")
                            print(
                                f"  {G}{BOLD}✅ RESERVA #{cod} [{ts_try}]!{RST}"
                            )
                            print(f"  {G}📅 {data} {h_display}{RST}")
                            return
                        msg = r["body"]
                        if isinstance(msg, list):
                            msg = msg[0]
                        print(f"  {Y}Tentativa {attempt} [{ts_try}]: {msg}{RST}")
                        if "não está disponível" in str(msg).lower():
                            print(f"  {R}💀 Alguem pegou antes!{RST}")
                            break
                        if "quantidade de reservas" in str(msg).lower():
                            print(
                                f"  {R}❌ Conta ja tem reserva nesse tipo de area!{RST}"
                            )
                            return

                    print(f"  {Y}Continuando monitoramento...{RST}\n")

            # Status compacto
            total_vagas = sum(1 for s in estado_atual.values() if s["vagas"] > 0)
            total_slots = len(estado_atual)
            print(
                f"\r  {DIM}[{ts}] #{ciclo} — {total_vagas}/{total_slots} slots livres{RST}  ",
                end="",
                flush=True,
            )

            ultimo_estado = {h: s["vagas"] for h, s in estado_atual.items()}
            time.sleep(intervalo)

    except KeyboardInterrupt:
        print(f"\n\n  {Y}📡 Radar desligado. {ciclo} ciclos.{RST}")


def ranking(client: HubClient, dias: int = 7) -> None:
    """Analisa quem usa automação no condomínio — ranking de boteiros."""
    print(f"\n  {M}{BOLD}🏆 RANKING DE BOTEIROS — ultimos {dias} dias{RST}\n")

    reservas = client.todas_reservas_condo()
    hoje = datetime.now()

    # Coletar reservas SPEED (solicitadas nos primeiros 30s da meia-noite)
    speeds: dict[str, list] = {}  # "NOME | UNID" -> [reserva, ...]
    rapidos: dict[str, list] = {}

    for r in reservas:
        sol = r.get("dataSolicitacao", "")
        if len(sol) < 19:
            continue

        # Filtrar por range de dias
        try:
            dt_sol = datetime.strptime(sol[:19], "%Y-%m-%dT%H:%M:%S")
            if (hoje - dt_sol).days > dias:
                continue
        except ValueError:
            continue

        h, m, s = int(sol[11:13]), int(sol[14:16]), int(sol[17:19])
        nome = r.get("nome", "?")[:30]
        unid = r.get("unidade", "?")
        key = f"{nome} | {unid}"

        if h == 0 and m == 0 and s <= 30:
            speeds.setdefault(key, []).append(r)
        elif h == 0 and m <= 1:
            rapidos.setdefault(key, []).append(r)

    if not speeds and not rapidos:
        print(f"  {DIM}Nenhuma reserva suspeita encontrada.{RST}")
        return

    # Ranking por SPEED (< 30s)
    if speeds:
        ranked = sorted(speeds.items(), key=lambda x: -len(x[1]))
        print(f"  {R}{BOLD}⚡ SPEED (<30s da meia-noite) — 100% automacao{RST}\n")
        print(f"  {'#':>3}  {'Vezes':>5}  {'Nome / Unidade':<45}  {'Ultimo'}")
        print(f"  {'-' * 80}")
        for i, (key, lista) in enumerate(ranked[:20], 1):
            ultimo = max(r.get("dataSolicitacao", "")[:10] for r in lista)
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i:>2}"
            print(f"  {medal:>3}  {len(lista):>5}x  {key:<45}  {ultimo}")
        total_speed = sum(len(v) for v in speeds.values())
        print(f"\n  {DIM}{len(speeds)} moradores, {total_speed} reservas SPEED{RST}")

    # Ranking por RAPIDO (< 2min)
    if rapidos:
        ranked_r = sorted(rapidos.items(), key=lambda x: -len(x[1]))
        print(f"\n  {Y}{BOLD}🏎️  RAPIDO (<2min) — provavelmente automacao{RST}\n")
        print(f"  {'#':>3}  {'Vezes':>5}  {'Nome / Unidade':<45}  {'Ultimo'}")
        print(f"  {'-' * 80}")
        for i, (key, lista) in enumerate(ranked_r[:15], 1):
            ultimo = max(r.get("dataSolicitacao", "")[:10] for r in lista)
            print(f"  {i:>3}  {len(lista):>5}x  {key:<45}  {ultimo}")

    # Horários mais disputados
    print(f"\n  {C}{BOLD}🔥 Horarios mais disputados (SPEED){RST}\n")
    hora_count: dict[str, int] = {}
    area_count: dict[str, int] = {}
    for lista in speeds.values():
        for r in lista:
            h = r.get("dataInicial", "")[11:16]
            a = r.get("area", {}).get("descricao", "?").strip()
            hora_count[h] = hora_count.get(h, 0) + 1
            area_count[a] = area_count.get(a, 0) + 1

    for h, cnt in sorted(hora_count.items(), key=lambda x: -x[1])[:10]:
        bar = "█" * min(cnt, 30)
        print(f"  {h}  {bar} {cnt}")

    print(f"\n  {C}{BOLD}🏟️  Areas mais disputadas{RST}\n")
    for a, cnt in sorted(area_count.items(), key=lambda x: -x[1])[:10]:
        bar = "█" * min(cnt, 30)
        print(f"  {a:<30}  {bar} {cnt}")


def trocar_reserva(clients: list[HubClient]) -> None:
    """Cancela com conta A, reserva com conta B — em milissegundos."""
    print(f"\n  {M}{BOLD}🔄 TROCA DE RESERVA{RST}")
    print(f"  {DIM}Cancela com uma conta, reserva com outra — atomico{RST}\n")

    if len(clients) < 2:
        print(f"  {Y}⚠️  Com 1 conta so, o slot fica vulneravel entre cancel e reserve.{RST}")
        print(f"  {DIM}Ideal: 2+ contas pra blindar.{RST}\n")

    src = pick_client(clients, "Conta que vai CANCELAR")
    if not src:
        return

    reservas = src.minhas_reservas()
    if not reservas:
        print(f"  {R}Nenhuma reserva ativa nessa conta.{RST}")
        return

    print(
        f"\n  {BOLD}{'#':>3}  {'Cod':>8}  {'Espaco':<35}  {'Data':>12}  {'Horario'}{RST}"
    )
    print(f"  {'-' * 75}")
    for i, r in enumerate(reservas, 1):
        a_name = r["area"]["descricao"].strip()
        d = r["dataInicial"][:10]
        print(
            f"  {i:>3}  {r['codigoReserva']:>8}  {a_name:<35}  {d:>12}  "
            f"{r['dataInicial'][11:16]}-{r['dataFinal'][11:16]}"
        )

    n = input(f"\n  Numero da reserva pra cancelar: ").strip()
    try:
        reserva = reservas[int(n) - 1]
    except (ValueError, IndexError):
        print(f"  {R}Numero invalido.{RST}")
        return

    dst = pick_client(clients, "Conta que vai RESERVAR")
    if not dst:
        return

    area_cod = reserva["area"]["codigo"]
    area_nome = reserva["area"]["descricao"].strip()
    # Limpa datas: remove ms e Z, garante formato local
    inicio = reserva["dataInicial"].split(".")[0].replace("Z", "")
    fim = reserva["dataFinal"].split(".")[0].replace("Z", "")
    cod_reserva = reserva["codigoReserva"]

    print(f"\n  {BOLD}Plano de execucao:{RST}")
    print(f"  {R}1. CANCELAR{RST} #{cod_reserva} ({area_nome}) com {src.account.label}")
    print(
        f"  {G}2. RESERVAR{RST} {area_nome} {inicio[11:16]}-{fim[11:16]} "
        f"com {dst.account.label}"
    )
    print(f"\n  {Y}⚠️  Se a reserva falhar apos o cancelamento, o slot fica livre!{RST}")

    confirm = input(f"\n  Confirma? (s/n) [s]: ").strip().lower() or "s"
    if confirm != "s":
        print(f"  {DIM}Abortado.{RST}")
        return

    # Refresh tokens antes de tudo pra maximizar janela
    print(f"\n  {B}🔄 Renovando tokens...{RST}")
    src.login()
    if dst is not src:
        dst.login()

    # EXECUTE — cancel + reserve back-to-back
    t0 = time.monotonic()

    print(f"  {R}❌ Cancelando #{cod_reserva}...{RST}", end=" ", flush=True)
    r_cancel = src.cancelar(cod_reserva)
    if r_cancel["status"] != 200:
        msg = r_cancel["body"]
        if isinstance(msg, list):
            msg = msg[0]
        print(f"\n  {R}Falha no cancelamento: {msg}{RST}")
        return
    t_cancel = time.monotonic()
    print(f"{G}OK ({(t_cancel - t0) * 1000:.0f}ms){RST}")

    # Rajada de tentativas de reserva — sem sleep entre as primeiras
    for attempt in range(1, 6):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
        r_reserva = dst.reservar(area_cod, inicio, fim)

        if r_reserva["status"] == 200:
            t_end = time.monotonic()
            novo_cod = r_reserva["body"].get("codigoReserva")
            print(f"  {G}{BOLD}✅ RESERVA CRIADA [{ts}]! Codigo: {novo_cod}{RST}")
            print(f"  {G}🔄 Troca completa em {(t_end - t0) * 1000:.0f}ms{RST}")
            return

        msg = r_reserva["body"]
        if isinstance(msg, list):
            msg = msg[0]
        print(f"  {Y}⏳ Tentativa {attempt} [{ts}]: {msg}{RST}")

        # Se "nao disponivel" alguem pegou no meio
        if "não está disponível" in str(msg).lower():
            print(f"  {R}{BOLD}💀 Alguem pegou o slot entre o cancel e o reserve!{RST}")
            return

        # Quantidade de reservas ativa = conta destino ja tem reserva nessa area
        if "quantidade de reservas" in str(msg).lower():
            print(
                f"  {R}{BOLD}❌ Conta destino ja tem reserva ativa nesse tipo de area!{RST}"
            )
            print(f"  {DIM}Cancele a reserva da conta destino primeiro.{RST}")
            return

        # Pequeno delay so a partir da tentativa 3
        if attempt >= 3:
            time.sleep(0.05)

    print(f"  {R}{BOLD}💀 Falhou apos 5 tentativas.{RST}")
    print(
        f"  {R}⚠️  A reserva #{cod_reserva} FOI CANCELADA "
        f"mas a nova NAO foi criada!{RST}"
    )


def trocar_cli(clients: list[HubClient], cod_reserva: int, conta_src: int, conta_dst: int) -> None:
    """Troca via CLI: --trocar CODIGO --conta N --conta-destino N."""
    src_idx = max(0, min(conta_src - 1, len(clients) - 1))
    dst_idx = max(0, min(conta_dst - 1, len(clients) - 1))
    if src_idx == dst_idx and len(clients) > 1:
        print(f"  {Y}⚠️  Mesma conta src/dst — slot fica vulneravel entre cancel e reserve.{RST}")
    src = clients[src_idx]
    dst = clients[dst_idx]

    # Buscar dados da reserva
    reservas = src.minhas_reservas()
    reserva = next((r for r in reservas if r["codigoReserva"] == cod_reserva), None)
    if not reserva:
        print(f"  {R}Reserva #{cod_reserva} nao encontrada na conta {src.account.label}.{RST}")
        return

    area_cod = reserva["area"]["codigo"]
    area_nome = reserva["area"]["descricao"].strip()
    inicio = reserva["dataInicial"].split(".")[0].replace("Z", "")
    fim = reserva["dataFinal"].split(".")[0].replace("Z", "")

    print(f"  {R}CANCELAR{RST} #{cod_reserva} ({area_nome}) → {src.account.label}")
    print(f"  {G}RESERVAR{RST} {inicio[11:16]}-{fim[11:16]} → {dst.account.label}")

    # Refresh tokens
    src.login()
    if dst is not src:
        dst.login()

    t0 = time.monotonic()
    r_cancel = src.cancelar(cod_reserva)
    if r_cancel["status"] != 200:
        msg = r_cancel["body"]
        if isinstance(msg, list):
            msg = msg[0]
        print(f"  {R}❌ Cancel falhou: {msg}{RST}")
        return
    print(f"  {G}✅ Cancelado ({(time.monotonic() - t0) * 1000:.0f}ms){RST}")

    for attempt in range(1, 6):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
        r_reserva = dst.reservar(area_cod, inicio, fim)
        if r_reserva["status"] == 200:
            novo_cod = r_reserva["body"].get("codigoReserva")
            print(f"  {G}✅ Reservado #{novo_cod} [{ts}] ({(time.monotonic() - t0) * 1000:.0f}ms total){RST}")
            return
        msg = r_reserva["body"]
        if isinstance(msg, list):
            msg = msg[0]
        if "não está disponível" in str(msg).lower():
            print(f"  {R}💀 Slot pego por outro! [{ts}]{RST}")
            return
        if "quantidade de reservas" in str(msg).lower():
            print(f"  {R}❌ Conta destino ja tem reserva ativa nesse tipo!{RST}")
            return
        if attempt >= 3:
            time.sleep(0.05)

    print(f"  {R}💀 Falhou. Reserva #{cod_reserva} foi cancelada mas nova nao criou!{RST}")


# ===== GERENCIAR CONTAS =====


def gerenciar_contas(accounts: list[Account]) -> list[Account]:
    while True:
        print(f"\n  {C}{BOLD}GERENCIAR CONTAS{RST}\n")
        if accounts:
            for i, a in enumerate(accounts, 1):
                print(
                    f"    {i}. {a.label} — CPF: {a.cpf} | Cond: {a.condominio} | Unid: {a.unidade}"
                )
        else:
            print("    Nenhuma conta cadastrada.")

        print(f"\n    {DIM}[A] Adicionar  [R] Remover  [V] Voltar{RST}")
        op = input("  > ").strip().upper()

        if op == "A":
            label = input("  Label (ex: Marlon, Esposa): ").strip()
            cpf = input("  CPF: ").strip()
            senha = input("  Senha: ").strip()
            condo = int(input("  Condominio [2078]: ").strip() or "2078")
            unid = input("  Unidade: ").strip()
            accounts.append(
                Account(
                    label=label,
                    cpf=cpf,
                    senha=senha,
                    condominio=condo,
                    unidade=unid,
                )
            )
            save_accounts(accounts)
            print(f"  {G}✅ Conta '{label}' adicionada!{RST}")
        elif op == "R":
            if not accounts:
                continue
            n = input("  Numero pra remover: ").strip()
            idx = int(n) - 1
            if 0 <= idx < len(accounts):
                removed = accounts.pop(idx)
                save_accounts(accounts)
                print(f"  {Y}Conta '{removed.label}' removida.{RST}")
        elif op == "V":
            return accounts


# ===== MENU INTERATIVO =====


def menu(clients: list[HubClient], accounts: list[Account]) -> None:
    while True:
        print(f"\n  {C}┌──────────────────────────────────┐{RST}")
        print(f"  {C}│{RST} 1. Gerenciar contas              {C}│{RST}")
        print(f"  {C}│{RST} 2. Ver espacos                   {C}│{RST}")
        print(f"  {C}│{RST} 3. Ver horarios                  {C}│{RST}")
        print(f"  {C}│{RST} 4. Reservar                      {C}│{RST}")
        print(f"  {C}│{RST} 5. Sniper (agendar meia-noite)   {C}│{RST}")
        print(f"  {C}│{RST} 6. Minhas reservas               {C}│{RST}")
        print(f"  {C}│{RST} 7. Cancelar reserva              {C}│{RST}")
        print(f"  {C}│{RST} 8. Espiao (quem reservou)        {C}│{RST}")
        print(f"  {C}│{RST} 9. Trocar reserva (cancel+book)  {C}│{RST}")
        print(f"  {C}│{RST} 10. Radar (monitora cancelamento) {C}│{RST}")
        print(f"  {C}│{RST} 11. Ranking (quem usa bot)        {C}│{RST}")
        print(f"  {C}│{RST} 0. Sair                           {C}│{RST}")
        print(f"  {C}└───────────────────────────────────┘{RST}")
        for c in clients:
            if c.logged_in:
                print(f"  {DIM}👤 {c.account.label}: {c.account.nome}{RST}")

        op = input(f"\n  > ").strip()

        if op == "1":
            accounts = gerenciar_contas(accounts)
            clients.clear()
            for a in accounts:
                c = HubClient(a)
                if c.login():
                    clients.append(c)
                    print(f"  {G}✅ {a.label}: {a.nome}{RST}")
                else:
                    print(f"  {R}❌ {a.label}: falha no login{RST}")

        elif op == "2":
            c = pick_client(clients)
            if c:
                mostrar_areas(c)

        elif op == "3":
            c = pick_client(clients, "Conta pra consultar")
            if not c:
                continue
            cod = input("  Codigo da area: ").strip()
            data = input("  Data (YYYY-MM-DD) [+7 dias]: ").strip()
            if not data:
                data = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            mostrar_horarios(c, int(cod), data)

        elif op == "4":
            c = pick_client(clients, "Conta pra reservar")
            if not c:
                continue
            cod = input("  Codigo da area: ").strip()
            data = input("  Data (YYYY-MM-DD): ").strip()
            consulta = c
            if len(clients) > 1:
                consulta = pick_client(clients, "Conta pra consultar horarios") or c
            slots = mostrar_horarios(consulta, int(cod), data)
            if not slots:
                continue
            idx = input(f"\n  Numero do horario: ").strip()
            slot = slots[int(idx) - 1]
            print(
                f"\n  {C}⏳ Reservando {slot['inicio'][11:16]} - {slot['fim'][11:16]} com {c.account.label}...{RST}"
            )
            r = c.reservar(int(cod), slot["inicio"], slot["fim"])
            if r["status"] == 200:
                print(
                    f"  {G}✅ RESERVA CRIADA! Codigo: {r['body'].get('codigoReserva')}{RST}"
                )
            else:
                msg = r["body"]
                if isinstance(msg, list):
                    msg = msg[0]
                print(f"  {R}❌ {msg}{RST}")

        elif op == "5":
            c = pick_client(clients, "Conta pra sniper")
            if not c:
                continue
            print(f"\n  {Y}⏰ SNIPER — Dispara reserva na hora exata{RST}")
            print(f"  {DIM}💡 Reservas abrem a MEIA-NOITE (00:00:00){RST}\n")
            cod = input("  Codigo da area: ").strip()
            data = input("  Data da reserva (YYYY-MM-DD): ").strip()
            hora = input("  Horario desejado (HH:MM): ").strip()
            disp = input("  Hora do disparo [00:00]: ").strip() or "00:00"
            sniper(c, int(cod), data, hora, disp)

        elif op == "6":
            c = pick_client(clients, "Conta")
            if not c:
                continue
            reservas = c.minhas_reservas()
            if not reservas:
                print(f"\n  {DIM}Nenhuma reserva ativa.{RST}")
                continue
            print(
                f"\n  {BOLD}{'Cod':>8}  {'Espaco':<35}  {'Data':>12}  {'Horario'}{RST}"
            )
            print(f"  {'-' * 70}")
            for r in reservas:
                a = r["area"]["descricao"].strip()
                d = r["dataInicial"][:10]
                print(
                    f"  {r['codigoReserva']:>8}  {a:<35}  {d:>12}  {r['dataInicial'][11:16]}-{r['dataFinal'][11:16]}"
                )

        elif op == "7":
            c = pick_client(clients, "Conta")
            if not c:
                continue
            cod = input("  Codigo da reserva: ").strip()
            r = c.cancelar(int(cod))
            print(
                f"  {G}✅ Cancelada!{RST}"
                if r["status"] == 200
                else f"  {R}❌ {r['body']}{RST}"
            )

        elif op == "8":
            c = pick_client(clients, "Conta")
            if not c:
                continue
            data = input("  Data pra espiar (YYYY-MM-DD) [amanha]: ").strip()
            if not data:
                data = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            espiao(c, data)

        elif op == "9":
            trocar_reserva(clients)

        elif op == "10":
            print(f"\n  {M}{BOLD}📡 RADAR — Monitora cancelamentos e auto-reserva{RST}")
            print(f"  {DIM}Use uma conta pra consultar e outra pra reservar{RST}\n")
            reserva_c = pick_client(clients, "Conta pra RESERVAR")
            if not reserva_c:
                continue
            consulta_c = reserva_c
            if len(clients) > 1:
                consulta_c = pick_client(clients, "Conta pra CONSULTAR horarios") or reserva_c
            cod = input("  Codigo da area: ").strip()
            data = input("  Data (YYYY-MM-DD) [+7 dias]: ").strip()
            if not data:
                data = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            hora_r = input("  Horario alvo (HH:MM) [vazio = qualquer]: ").strip() or None
            interv = input("  Intervalo em segundos [5]: ").strip() or "5"
            radar(reserva_c, consulta_c, int(cod), data, hora_r, int(interv))

        elif op == "11":
            c = pick_client(clients, "Conta")
            if not c:
                continue
            d = input("  Analisar ultimos N dias [7]: ").strip() or "7"
            ranking(c, int(d))

        elif op == "0":
            break


# ===== MAIN =====


def main() -> None:
    parser = argparse.ArgumentParser(description="Hub 2.0 Auto Booking ⚡")
    parser.add_argument("--listar", action="store_true", help="Listar espacos")
    parser.add_argument("--area", type=int)
    parser.add_argument("--data", type=str)
    parser.add_argument("--hora", type=str)
    parser.add_argument("--sniper", action="store_true", help="Modo sniper")
    parser.add_argument(
        "--disparo", type=str, default="00:00", metavar="HH:MM", help="Hora do disparo"
    )
    parser.add_argument("--minhas", action="store_true")
    parser.add_argument("--cancelar", type=int)
    parser.add_argument("--espiao", type=str, metavar="YYYY-MM-DD")
    parser.add_argument(
        "--trocar", type=int, metavar="COD_RESERVA",
        help="Trocar reserva: cancela com --conta, reserva com --conta-destino"
    )
    parser.add_argument("--radar", action="store_true", help="Modo radar: monitora cancelamentos")
    parser.add_argument(
        "--intervalo", type=int, default=5, help="Intervalo do radar em segundos (default: 5)"
    )
    parser.add_argument(
        "--ranking", action="store_true", help="Ranking de boteiros do condominio"
    )
    parser.add_argument("--dias", type=int, default=7, help="Dias pra analisar no ranking (default: 7)")
    parser.add_argument(
        "--conta-destino", type=int, default=2,
        help="Conta destino pra troca (default: 2)"
    )
    parser.add_argument(
        "--conta", type=int, default=1, help="Numero da conta (default: 1)"
    )
    args = parser.parse_args()

    banner()

    # Load accounts
    accounts = load_accounts()
    if not accounts:
        print(f"  {Y}Nenhuma conta em {CONFIG_PATH}{RST}")
        print(f"  {DIM}Criando config inicial...{RST}\n")
        label = input("  Label (ex: Marlon): ").strip() or "Principal"
        cpf = input("  CPF: ").strip()
        senha = input("  Senha: ").strip()
        condo = int(input("  Condominio [2078]: ").strip() or "2078")
        unid = input("  Unidade: ").strip()
        accounts = [
            Account(
                label=label, cpf=cpf, senha=senha, condominio=condo, unidade=unid
            )
        ]
        save_accounts(accounts)
        print(f"  {G}✅ Salvo em {CONFIG_PATH}{RST}\n")

    # Login all accounts
    clients: list[HubClient] = []
    for a in accounts:
        c = HubClient(a)
        if c.login():
            print(f"  {G}✅ {a.label}: {a.nome} | {a.unidade}{RST}")
            clients.append(c)
        else:
            print(f"  {R}❌ {a.label}: falha no login ({a.cpf}){RST}")

    if not clients:
        print(f"\n  {R}Nenhuma conta logou. Verifique accounts.json{RST}")
        sys.exit(1)

    print()

    # CLI mode — verifica se alguma acao foi pedida
    has_action = any([
        args.listar, args.espiao, args.sniper, args.minhas,
        args.cancelar, args.trocar, args.radar, args.ranking, args.area,
    ])
    if has_action:
        idx = max(0, min(args.conta - 1, len(clients) - 1))
        client = clients[idx]

        if args.ranking:
            ranking(client, args.dias)
        elif args.radar and args.area and args.data:
            # Radar: --conta pra reservar, conta seguinte pra consultar
            consult_idx = (idx + 1) % len(clients) if len(clients) > 1 else idx
            consult = clients[consult_idx]
            radar(client, consult, args.area, args.data, args.hora, args.intervalo)
        elif args.trocar:
            trocar_cli(clients, args.trocar, args.conta, args.conta_destino)
        elif args.listar:
            mostrar_areas(client)
        elif args.espiao:
            espiao(client, args.espiao)
        elif args.area and args.data and args.sniper:
            hora = args.hora or "20:00"
            sniper(client, args.area, args.data, hora, args.disparo)
        elif args.area and args.data and args.hora:
            h, m = map(int, args.hora.split(":"))
            dt = datetime.strptime(args.data, "%Y-%m-%d").replace(hour=h, minute=m)
            ini = dt.strftime("%Y-%m-%dT%H:%M:%S")
            fim = (dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
            r = client.reservar(args.area, ini, fim)
            if r["status"] == 200:
                print(
                    f"  {G}✅ Reserva criada! Codigo: {r['body'].get('codigoReserva')}{RST}"
                )
            else:
                msg = r["body"]
                if isinstance(msg, list):
                    msg = msg[0]
                print(f"  {R}❌ {msg}{RST}")
        elif args.area and args.data:
            mostrar_horarios(client, args.area, args.data)
        elif args.minhas:
            reservas = client.minhas_reservas()
            if not reservas:
                print("  Nenhuma reserva ativa.")
            for r in reservas:
                a = r["area"]["descricao"].strip()
                print(
                    f"  {r['codigoReserva']:>8}  {a:<35}  {r['dataInicial'][:10]}  {r['dataInicial'][11:16]}-{r['dataFinal'][11:16]}"
                )
        elif args.cancelar:
            r = client.cancelar(args.cancelar)
            print(
                f"  {G}✅ Cancelada!{RST}"
                if r["status"] == 200
                else f"  {R}❌ {r['body']}{RST}"
            )
        else:
            parser.print_help()
        return

    # Interactive mode
    menu(clients, accounts)


if __name__ == "__main__":
    main()
