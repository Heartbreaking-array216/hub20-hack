#!/usr/bin/env node
/**
 * Hub 2.0 - Auto Booking ⚡
 * Node.js CLI — zero dependências externas (usa fetch nativo do Node 18+)
 *
 * Uso:
 *   node hub20.mjs                          # menu interativo
 *   node hub20.mjs listar                   # espacos
 *   node hub20.mjs horarios 17 2026-04-03   # ver horarios
 *   node hub20.mjs reservar 17 2026-04-03 20:00
 *   node hub20.mjs sniper 17 2026-04-03 20:00
 *   node hub20.mjs minhas
 *   node hub20.mjs cancelar 1332456
 *   node hub20.mjs espiao 2026-04-03
 *   node hub20.mjs trocar 1332456           # cancel conta 1, book conta 2
 */

import { readFileSync, writeFileSync, existsSync } from 'fs';
import { createInterface } from 'readline';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dir = dirname(fileURLToPath(import.meta.url));
const CONFIG = join(__dir, 'accounts.json');
const API_ACC = 'https://api-accounts.hubert.com.br';
const API_MOR = 'https://api-morador.hubert.com.br';

// ===== ANSI =====
const R = '\x1b[91m', G = '\x1b[92m', Y = '\x1b[93m', B = '\x1b[94m';
const C = '\x1b[96m', M = '\x1b[95m', DIM = '\x1b[90m', BOLD = '\x1b[1m', RST = '\x1b[0m';

// ===== CONFIG =====
function loadAccounts() {
  try {
    if (existsSync(CONFIG)) return JSON.parse(readFileSync(CONFIG, 'utf8'));
  } catch (e) { console.error(`  ${R}Erro ao ler accounts.json: ${e.message}${RST}`); }
  return [];
}

function saveAccounts(accounts) {
  writeFileSync(CONFIG, JSON.stringify(accounts.map(a => ({
    label: a.label, cpf: a.cpf, senha: a.senha, condominio: a.condominio, unidade: a.unidade
  })), null, 2) + '\n');
}

// ===== READLINE =====
const rl = createInterface({ input: process.stdin, output: process.stdout });
const ask = (q) => new Promise(r => rl.question(q, r));
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// ===== HTTP =====
async function api(method, url, token, body = null) {
  const headers = { 'Content-Type': 'application/json', 'Origin': 'app-morador' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);
  try {
    const r = await fetch(url, opts);
    const data = await r.json().catch(() => null);
    return { status: r.status, data };
  } catch (e) {
    return { status: 0, data: `Erro rede: ${e.message}` };
  }
}

// ===== ACCOUNT =====
class Account {
  constructor(cfg) {
    this.label = cfg.label;
    this.cpf = cfg.cpf;
    this.senha = cfg.senha;
    this.condominio = cfg.condominio;
    this.unidade = cfg.unidade;
    this.token = '';
    this.nome = '';
  }

  async login() {
    const creds = Buffer.from(`${this.cpf}:${this.senha}`).toString('base64');
    try {
      const resp = await fetch(`${API_ACC}/api/v1/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Base ${creds}`, 'Origin': 'app-morador' },
      });
      const data = await resp.json();
      if (resp.status === 200 && data.token) {
        this.token = data.token;
        this.nome = data.nome;
        return true;
      }
    } catch {}
    return false;
  }

  async listarAreas() {
    const r = await api('GET', `${API_MOR}/api/v1/areas?codigoCondominio=${this.condominio}`, this.token);
    return r.status === 200 ? r.data : [];
  }

  async verHorarios(area, data) {
    const unid = encodeURIComponent(this.unidade);
    const url = `${API_MOR}/api/v1/areas/${area}/datasDisponiveis?codigoCondominio=${this.condominio}&unidade=${unid}&dataInicial=${data}T00:00:00&dataFinal=${data}T23:59:00`;
    const r = await api('GET', url, this.token);
    if (r.status === 400) {
      const msg = Array.isArray(r.data) ? r.data[0] : JSON.stringify(r.data);
      if (String(msg).toLowerCase().includes('quantidade de reservas'))
        console.log(`  ${Y}⚠️  Reserva ativa nessa area! Use outra conta.${RST}`);
      else
        console.log(`  ${Y}⚠️  ${msg}${RST}`);
      return [];
    }
    if (r.status !== 200) return [];
    const slots = [];
    for (const d of r.data?.datas || [])
      for (const p of d.periodos || [])
        slots.push({ inicio: p.dataInicio, fim: p.dataTermino, vagas: p.quantidadeDeVagas });
    return slots;
  }

  async reservar(area, inicio, fim) {
    // Sanitizar datas
    inicio = inicio.split('.')[0].replace('Z', '');
    fim = fim.split('.')[0].replace('Z', '');
    return api('POST', `${API_MOR}/api/v1/reservas`, this.token, {
      codigoArea: area, codigoCondominio: this.condominio, unidade: this.unidade,
      quantPessoas: 1, dataReserva: [{ dataInicial: inicio, dataFinal: fim }], observacoes: ''
    });
  }

  async cancelar(codigo) {
    return api('POST', `${API_MOR}/api/v1/reservas/${codigo}/cancelar`, this.token, { motivo: 'Aplicativo morador' });
  }

  async minhasReservas() {
    const r = await api('GET', `${API_MOR}/api/v1/reservas`, this.token);
    if (r.status !== 200) return [];
    return r.data.filter(x =>
      x.condominio?.codigo === this.condominio &&
      x.unidade === this.unidade &&
      x.situacao?.codigo === 2
    );
  }

  async todasReservasCondo() {
    const r = await api('GET', `${API_MOR}/api/v1/reservas`, this.token);
    if (r.status !== 200) return [];
    return r.data.filter(x => x.condominio?.codigo === this.condominio);
  }
}

// ===== DISPLAY =====
function banner() {
  console.log(`
${C}╔══════════════════════════════════════════╗
║     ${RST}${BOLD}🏢 HUB 2.0 - AUTO BOOKING ⚡${RST}${C}        ║
║     ${DIM}Node.js — zero dependencias${RST}${C}          ║
╚══════════════════════════════════════════╝${RST}`);
}

function fmtMsg(body) {
  return Array.isArray(body) ? body[0] : typeof body === 'string' ? body : JSON.stringify(body);
}

function calcFim(data, hora) {
  const d = new Date(`${data}T${hora.padStart(5, '0')}:00`);
  d.setTime(d.getTime() + 3600000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
}

async function pickAccount(accounts, prompt = 'Conta') {
  if (!accounts.length) { console.log(`  ${R}Nenhuma conta.${RST}`); return null; }
  if (accounts.length === 1) return accounts[0];
  console.log(`\n  ${C}Contas:${RST}`);
  accounts.forEach((a, i) => {
    const st = a.token ? `${G}✅${RST}` : `${R}❌${RST}`;
    console.log(`    ${i + 1}. ${st} ${a.label} — ${a.nome || a.cpf}`);
  });
  const n = await ask(`  ${prompt} [1]: `) || '1';
  const idx = parseInt(n) - 1;
  return (idx >= 0 && idx < accounts.length) ? accounts[idx] : null;
}

// ===== FEATURES =====
async function showAreas(acct) {
  const areas = await acct.listarAreas();
  const tipos = {};
  for (const a of areas) {
    const t = a.tipoArea?.descricao || 'Outros';
    (tipos[t] = tipos[t] || []).push(a);
  }
  console.log(`\n  ${BOLD}${'Cod'.padStart(4)}  ${'Espaco'.padEnd(40)}${RST}`);
  console.log(`  ${'='.repeat(50)}`);
  for (const tipo of Object.keys(tipos).sort()) {
    console.log(`\n  ${C}── ${tipo} ──${RST}`);
    tipos[tipo].sort((a, b) => (a.codigoArea || 0) - (b.codigoArea || 0));
    for (const a of tipos[tipo]) {
      const cod = a.codigoArea || a.codigo;
      const nome = (a.nomeArea || a.descricao || '?').trim();
      console.log(`  ${String(cod).padStart(4)}  ${nome}`);
    }
  }
}

async function showHorarios(acct, area, data) {
  const slots = await acct.verHorarios(area, data);
  if (!slots.length) { console.log(`\n  ${R}❌ Sem horarios em ${data}${RST}`); return []; }
  console.log(`\n  ${C}📅 Area ${area} — ${data}${RST}\n`);
  slots.forEach((s, i) => {
    const ini = s.inicio.substring(11, 16);
    const fim = s.fim.substring(11, 16);
    const icon = s.vagas > 0 ? `${G}✅${RST}` : `${R}❌${RST}`;
    console.log(`  ${String(i + 1).padStart(3)}. ${icon} ${ini} - ${fim}  (${s.vagas} vaga${s.vagas !== 1 ? 's' : ''})`);
  });
  return slots;
}

async function showEspiao(acct, dataFiltro) {
  console.log(`\n  ${M}🕵️  MODO ESPIAO — reservas para ${dataFiltro}${RST}\n`);
  const reservas = await acct.todasReservasCondo();
  const filtradas = reservas.filter(r => (r.dataInicial || '').startsWith(dataFiltro));
  if (!filtradas.length) { console.log('  Nenhuma reserva.'); return; }
  filtradas.sort((a, b) => (a.dataSolicitacao || '').localeCompare(b.dataSolicitacao || ''));

  console.log(`  ${DIM}${'Solicitado em'.padStart(26)}  ${'Area'.padEnd(28)}  ${'Horario'.padStart(11)}  ${'Nome'.padEnd(28)}  Unid${RST}`);
  console.log(`  ${'-'.repeat(110)}`);
  let rapidos = 0, primeiro = '';
  for (const r of filtradas) {
    const sol = r.dataSolicitacao || '?';
    const area = (r.area?.descricao || '?').trim().substring(0, 27);
    const hIni = (r.dataInicial || '?').substring(11, 16);
    const hFim = (r.dataFinal || '?').substring(11, 16);
    const nome = (r.nome || '?').substring(0, 27);
    let badge = '';
    if (sol.length >= 19) {
      const h = parseInt(sol.substring(11, 13));
      const m = parseInt(sol.substring(14, 16));
      const s = parseInt(sol.substring(17, 19));
      if (h === 0 && m === 0 && s <= 30) { badge = ` ${R}${BOLD}⚡ SPEED${RST}`; rapidos++; if (!primeiro) primeiro = sol; }
      else if (h === 0 && m <= 1) { badge = ` ${Y}🏎️ RAPIDO${RST}`; rapidos++; if (!primeiro) primeiro = sol; }
    }
    console.log(`  ${sol.padStart(26)}${badge}  ${area.padEnd(28)}  ${hIni}-${hFim.padStart(5)}  ${nome.padEnd(28)}  ${r.unidade}`);
  }
  if (rapidos > 0) {
    console.log(`\n  ${Y}${BOLD}🏎️  ${rapidos} reservas nos primeiros 60 segundos!${RST}`);
    console.log(`  ${DIM}Mais rapido: ${primeiro}${RST}`);
  }
}

async function doSniper(acct, area, data, hora, disparo = '00:00') {
  const inicio = `${data}T${hora.padStart(5, '0')}:00`;
  const fim = calcFim(data, hora);
  const [dh, dm] = disparo.split(':').map(Number);

  console.log(`\n  ${G}${BOLD}🎯 MODO SNIPER ATIVADO${RST}`);
  console.log(`  ${C}📍 Area ${area} | 📅 ${data} ${hora}${RST}`);
  console.log(`  ${C}👤 ${acct.label} (${acct.nome})${RST}`);
  console.log(`  ${Y}⏰ Disparo as ${String(dh).padStart(2, '0')}:${String(dm).padStart(2, '0')}:00${RST}`);
  console.log(`  ${DIM}⏳ Ctrl+C para cancelar${RST}\n`);

  let relogged = false;
  while (true) {
    const now = new Date();
    const target = new Date();
    target.setHours(dh, dm, 0, 0);
    if (target <= new Date(now.getTime() - 1000)) target.setDate(target.getDate() + 1);
    const diff = (target - now) / 1000;
    if (diff <= 0) break;
    if (diff <= 5 && !relogged) {
      process.stdout.write(`\n  ${B}🔄 Renovando token... ${RST}`);
      const ok = await acct.login();
      console.log(ok ? `${G}OK${RST}` : `${R}FALHOU${RST}`);
      relogged = true;
    }
    const hh = Math.floor(diff / 3600);
    const mm = Math.floor((diff % 3600) / 60);
    const ss = Math.floor(diff % 60);
    const color = diff <= 10 ? R : diff <= 60 ? Y : C;
    process.stdout.write(`\r  ${color}⏱️  ${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}${RST}  `);
    await sleep(100);
  }

  const tsD = new Date().toLocaleTimeString('pt-BR', { hour12: false, fractionalSecondDigits: 3 });
  console.log(`\n\n  ${G}${BOLD}🚀 DISPARANDO! [${tsD}]${RST}`);

  for (let i = 1; i <= 10; i++) {
    const ts = new Date().toLocaleTimeString('pt-BR', { hour12: false, fractionalSecondDigits: 3 });
    const r = await acct.reservar(area, inicio, fim);
    if (r.status === 200) {
      const cod = r.data?.codigoReserva || '?';
      console.log(`\n  ${G}${BOLD}✅ RESERVA CONFIRMADA as ${ts}!${RST}`);
      console.log(`  ${G}📋 Codigo: ${cod}${RST}`);
      return;
    }
    const msg = fmtMsg(r.data);
    console.log(`  ${R}❌ Tentativa ${i} [${ts}]: ${msg}${RST}`);
    if (String(msg).includes('não está disponível')) { console.log(`  ${R}${BOLD}💀 Ja pegaram!${RST}`); return; }
    await sleep(20);
  }
  console.log(`  ${R}${BOLD}💀 Falhou apos 10 tentativas.${RST}`);
}

async function doTrocar(accounts, codReserva, srcIdx = 0, dstIdx = 1) {
  const src = accounts[srcIdx];
  const dst = accounts[dstIdx];
  if (!src || !dst) { console.log(`  ${R}Contas invalidas.${RST}`); return; }

  const reservas = await src.minhasReservas();
  const reserva = reservas.find(r => r.codigoReserva === codReserva);
  if (!reserva) { console.log(`  ${R}Reserva #${codReserva} nao encontrada.${RST}`); return; }

  const areaCod = reserva.area?.codigoArea || reserva.area?.codigo;
  const areaNome = (reserva.area?.descricao || '?').trim();
  const inicio = (reserva.dataInicial || '').split('.')[0].replace('Z', '');
  const fim = (reserva.dataFinal || '').split('.')[0].replace('Z', '');

  console.log(`\n  ${M}${BOLD}🔄 TROCA DE RESERVA${RST}`);
  console.log(`  ${R}CANCELAR${RST} #${codReserva} (${areaNome}) → ${src.label}`);
  console.log(`  ${G}RESERVAR${RST} ${areaNome} ${inicio.substring(11, 16)}-${fim.substring(11, 16)} → ${dst.label}`);

  // Refresh tokens
  console.log(`\n  ${B}🔄 Renovando tokens...${RST}`);
  await src.login();
  if (src !== dst) await dst.login();

  const t0 = performance.now();
  process.stdout.write(`  ${R}❌ Cancelando #${codReserva}...${RST} `);
  const rc = await src.cancelar(codReserva);
  if (rc.status !== 200) { console.log(`\n  ${R}Falhou: ${fmtMsg(rc.data)}${RST}`); return; }
  console.log(`${G}OK (${Math.round(performance.now() - t0)}ms)${RST}`);

  for (let i = 1; i <= 5; i++) {
    const ts = new Date().toLocaleTimeString('pt-BR', { hour12: false, fractionalSecondDigits: 3 });
    const rr = await dst.reservar(areaCod, inicio, fim);
    if (rr.status === 200) {
      const cod = rr.data?.codigoReserva || '?';
      console.log(`  ${G}${BOLD}✅ RESERVA CRIADA [${ts}]! Codigo: ${cod} (${Math.round(performance.now() - t0)}ms total)${RST}`);
      return;
    }
    const msg = fmtMsg(rr.data);
    console.log(`  ${Y}⏳ Tentativa ${i} [${ts}]: ${msg}${RST}`);
    if (String(msg).includes('não está disponível')) { console.log(`  ${R}${BOLD}💀 Slot pego!${RST}`); return; }
    if (String(msg).includes('quantidade de reservas')) { console.log(`  ${R}❌ Conta destino ja tem reserva ativa nesse tipo!${RST}`); return; }
    if (i >= 3) await sleep(50);
  }
  console.log(`  ${R}${BOLD}💀 Falhou. Reserva cancelada mas nova nao criou!${RST}`);
}

// ===== MENU =====
async function menu(accounts) {
  while (true) {
    console.log(`\n  ${C}┌──────────────────────────────────┐${RST}`);
    console.log(`  ${C}│${RST} 1. Gerenciar contas              ${C}│${RST}`);
    console.log(`  ${C}│${RST} 2. Ver espacos                   ${C}│${RST}`);
    console.log(`  ${C}│${RST} 3. Ver horarios                  ${C}│${RST}`);
    console.log(`  ${C}│${RST} 4. Reservar                      ${C}│${RST}`);
    console.log(`  ${C}│${RST} 5. Sniper (agendar meia-noite)   ${C}│${RST}`);
    console.log(`  ${C}│${RST} 6. Minhas reservas               ${C}│${RST}`);
    console.log(`  ${C}│${RST} 7. Cancelar reserva              ${C}│${RST}`);
    console.log(`  ${C}│${RST} 8. Espiao (quem reservou)        ${C}│${RST}`);
    console.log(`  ${C}│${RST} 9. Trocar reserva (cancel+book)  ${C}│${RST}`);
    console.log(`  ${C}│${RST} 0. Sair                          ${C}│${RST}`);
    console.log(`  ${C}└──────────────────────────────────┘${RST}`);
    for (const a of accounts) if (a.token) console.log(`  ${DIM}👤 ${a.label}: ${a.nome}${RST}`);

    const op = (await ask('\n  > ')).trim();

    if (op === '1') {
      console.log(`\n  ${C}${BOLD}GERENCIAR CONTAS${RST}`);
      accounts.forEach((a, i) => console.log(`    ${i + 1}. ${a.label} — ${a.cpf} | ${a.condominio} | ${a.unidade}`));
      const act = (await ask(`  [A]dicionar [R]emover [V]oltar: `)).toUpperCase();
      if (act === 'A') {
        const label = await ask('  Label: ');
        const cpf = await ask('  CPF: ');
        const senha = await ask('  Senha: ');
        const condo = parseInt(await ask('  Condominio [2078]: ') || '2078');
        const unid = await ask('  Unidade: ');
        const a = new Account({ label, cpf, senha, condominio: condo, unidade: unid });
        if (await a.login()) {
          accounts.push(a);
          saveAccounts(accounts);
          console.log(`  ${G}✅ ${a.label}: ${a.nome}${RST}`);
        } else console.log(`  ${R}❌ Falha no login${RST}`);
      } else if (act === 'R' && accounts.length > 0) {
        const n = parseInt(await ask('  Numero: '));
        if (n >= 1 && n <= accounts.length) {
          const removed = accounts.splice(n - 1, 1)[0];
          saveAccounts(accounts);
          console.log(`  ${Y}Removida: ${removed.label}${RST}`);
        }
      }
    } else if (op === '2') {
      const a = await pickAccount(accounts);
      if (a) await showAreas(a);
    } else if (op === '3') {
      const a = await pickAccount(accounts, 'Conta pra consultar');
      if (!a) continue;
      const cod = await ask('  Codigo da area: ');
      const d = new Date(); d.setDate(d.getDate() + 7);
      const data = (await ask(`  Data [${d.toISOString().split('T')[0]}]: `)) || d.toISOString().split('T')[0];
      await showHorarios(a, parseInt(cod), data.trim());
    } else if (op === '4') {
      const a = await pickAccount(accounts, 'Conta pra reservar');
      if (!a) continue;
      const cod = await ask('  Codigo da area: ');
      const data = await ask('  Data (YYYY-MM-DD): ');
      const consulta = accounts.length > 1 ? (await pickAccount(accounts, 'Conta pra consultar')) || a : a;
      const slots = await showHorarios(consulta, parseInt(cod), data.trim());
      if (!slots.length) continue;
      const n = parseInt(await ask('\n  Numero do horario: '));
      const slot = slots[n - 1];
      if (!slot) continue;
      console.log(`\n  ${C}⏳ Reservando ${slot.inicio.substring(11, 16)} - ${slot.fim.substring(11, 16)} com ${a.label}...${RST}`);
      const r = await a.reservar(parseInt(cod), slot.inicio, slot.fim);
      if (r.status === 200) console.log(`  ${G}✅ RESERVA CRIADA! Codigo: ${r.data?.codigoReserva}${RST}`);
      else console.log(`  ${R}❌ ${fmtMsg(r.data)}${RST}`);
    } else if (op === '5') {
      const a = await pickAccount(accounts, 'Conta pra sniper');
      if (!a) continue;
      console.log(`\n  ${Y}⏰ SNIPER — Reservas abrem a MEIA-NOITE${RST}`);
      const cod = await ask('  Codigo da area: ');
      const data = await ask('  Data (YYYY-MM-DD): ');
      const hora = await ask('  Horario (HH:MM): ');
      const disp = (await ask('  Disparo [00:00]: ')) || '00:00';
      await doSniper(a, parseInt(cod), data.trim(), hora.trim(), disp.trim());
    } else if (op === '6') {
      const a = await pickAccount(accounts);
      if (!a) continue;
      const reservas = await a.minhasReservas();
      if (!reservas.length) { console.log(`\n  ${DIM}Nenhuma reserva ativa.${RST}`); continue; }
      console.log(`\n  ${BOLD}${'Cod'.padStart(8)}  ${'Espaco'.padEnd(35)}  ${'Data'.padStart(12)}  Horario${RST}`);
      console.log(`  ${'-'.repeat(70)}`);
      for (const r of reservas) {
        const area = (r.area?.descricao || '').trim();
        console.log(`  ${String(r.codigoReserva).padStart(8)}  ${area.padEnd(35)}  ${(r.dataInicial || '').substring(0, 10).padStart(12)}  ${(r.dataInicial || '').substring(11, 16)}-${(r.dataFinal || '').substring(11, 16)}`);
      }
    } else if (op === '7') {
      const a = await pickAccount(accounts);
      if (!a) continue;
      const cod = await ask('  Codigo da reserva: ');
      const r = await a.cancelar(parseInt(cod));
      console.log(r.status === 200 ? `  ${G}✅ Cancelada!${RST}` : `  ${R}❌ ${fmtMsg(r.data)}${RST}`);
    } else if (op === '8') {
      const a = await pickAccount(accounts);
      if (!a) continue;
      const d = new Date(); d.setDate(d.getDate() + 1);
      const data = (await ask(`  Data [${d.toISOString().split('T')[0]}]: `)) || d.toISOString().split('T')[0];
      await showEspiao(a, data.trim());
    } else if (op === '9') {
      if (accounts.length < 2) console.log(`  ${Y}⚠️  Melhor com 2+ contas.${RST}`);
      const src = await pickAccount(accounts, 'Conta que CANCELA');
      if (!src) continue;
      const reservas = await src.minhasReservas();
      if (!reservas.length) { console.log(`  ${R}Nenhuma reserva.${RST}`); continue; }
      reservas.forEach((r, i) => {
        const area = (r.area?.descricao || '').trim();
        console.log(`  ${String(i + 1).padStart(3)}. #${r.codigoReserva}  ${area}  ${(r.dataInicial || '').substring(11, 16)}-${(r.dataFinal || '').substring(11, 16)}`);
      });
      const n = parseInt(await ask('\n  Numero: '));
      const reserva = reservas[n - 1];
      if (!reserva) continue;
      const dst = await pickAccount(accounts, 'Conta que RESERVA');
      if (!dst) continue;
      const srcIdx = accounts.indexOf(src);
      const dstIdx = accounts.indexOf(dst);
      await doTrocar(accounts, reserva.codigoReserva, srcIdx, dstIdx);
    } else if (op === '0') {
      break;
    }
  }
  rl.close();
}

// ===== MAIN =====
async function main() {
  banner();

  const configs = loadAccounts();
  if (!configs.length) {
    console.log(`  ${Y}Nenhuma conta em accounts.json${RST}`);
    console.log(`  ${DIM}Copie accounts.example.json → accounts.json e edite.${RST}`);
    rl.close();
    process.exit(1);
  }

  const accounts = configs.map(c => new Account(c));
  for (const a of accounts) {
    if (await a.login()) console.log(`  ${G}✅ ${a.label}: ${a.nome} | ${a.unidade}${RST}`);
    else console.log(`  ${R}❌ ${a.label}: falha no login${RST}`);
  }

  const logged = accounts.filter(a => a.token);
  if (!logged.length) { console.log(`\n  ${R}Nenhuma conta logou.${RST}`); rl.close(); process.exit(1); }
  console.log();

  // CLI mode
  const args = process.argv.slice(2);
  if (args.length > 0) {
    const cmd = args[0];
    const a = logged[0];
    if (cmd === 'listar') await showAreas(a);
    else if (cmd === 'horarios' && args[1] && args[2]) await showHorarios(a, parseInt(args[1]), args[2]);
    else if (cmd === 'reservar' && args[1] && args[2] && args[3]) {
      const inicio = `${args[2]}T${args[3].padStart(5, '0')}:00`;
      const fim = calcFim(args[2], args[3]);
      const r = await a.reservar(parseInt(args[1]), inicio, fim);
      if (r.status === 200) console.log(`  ${G}✅ Codigo: ${r.data?.codigoReserva}${RST}`);
      else console.log(`  ${R}❌ ${fmtMsg(r.data)}${RST}`);
    }
    else if (cmd === 'sniper' && args[1] && args[2] && args[3]) await doSniper(a, parseInt(args[1]), args[2], args[3], args[4] || '00:00');
    else if (cmd === 'minhas') {
      const reservas = await a.minhasReservas();
      if (!reservas.length) console.log('  Nenhuma reserva ativa.');
      for (const r of reservas) console.log(`  ${String(r.codigoReserva).padStart(8)}  ${(r.area?.descricao || '').trim().padEnd(35)}  ${(r.dataInicial || '').substring(0, 10)}  ${(r.dataInicial || '').substring(11, 16)}-${(r.dataFinal || '').substring(11, 16)}`);
    }
    else if (cmd === 'cancelar' && args[1]) {
      const r = await a.cancelar(parseInt(args[1]));
      console.log(r.status === 200 ? `  ${G}✅ Cancelada!${RST}` : `  ${R}❌ ${fmtMsg(r.data)}${RST}`);
    }
    else if (cmd === 'espiao' && args[1]) await showEspiao(a, args[1]);
    else if (cmd === 'trocar' && args[1]) await doTrocar(logged, parseInt(args[1]), 0, Math.min(1, logged.length - 1));
    else console.log(`Uso: node hub20.mjs [listar|horarios|reservar|sniper|minhas|cancelar|espiao|trocar]`);
    rl.close();
    return;
  }

  // Interactive
  await menu(accounts);
}

main().catch(e => { console.error(e); process.exit(1); });
