use base64::{engine::general_purpose::STANDARD as B64, Engine};
use chrono::{Local, NaiveTime};
use clap::{Parser, Subcommand};
use colored::Colorize;
use dialoguer::{Input, Select};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::PathBuf;
use std::thread;
use std::time::Duration;
use std::{fs, process};

const API_ACCOUNTS: &str = "https://api-accounts.hubert.com.br";
const API_MORADOR: &str = "https://api-morador.hubert.com.br";

// ===== CLI =====

#[derive(Parser)]
#[command(name = "hub20", version, about = "🏢 Hub 2.0 Auto Booking ⚡")]
struct Cli {
    /// Numero da conta (default: 1)
    #[arg(long, short, default_value = "1")]
    conta: usize,

    #[command(subcommand)]
    cmd: Option<Cmd>,
}

#[derive(Subcommand)]
enum Cmd {
    /// Listar espacos do condominio
    Listar,
    /// Ver horarios disponiveis
    Horarios {
        /// Codigo da area
        area: i64,
        /// Data (YYYY-MM-DD)
        data: String,
    },
    /// Reservar horario
    Reservar {
        /// Codigo da area
        area: i64,
        /// Data (YYYY-MM-DD)
        data: String,
        /// Horario (HH:MM)
        hora: String,
    },
    /// Sniper - dispara reserva na hora exata
    Sniper {
        /// Codigo da area
        area: i64,
        /// Data da reserva (YYYY-MM-DD)
        data: String,
        /// Horario desejado (HH:MM)
        hora: String,
        /// Hora do disparo (HH:MM)
        #[arg(long, default_value = "00:00")]
        disparo: String,
    },
    /// Minhas reservas ativas
    Minhas,
    /// Cancelar reserva
    Cancelar {
        /// Codigo da reserva
        codigo: i64,
    },
    /// Espiao - ver quem reservou e quando
    Espiao {
        /// Data (YYYY-MM-DD)
        data: String,
    },
    /// Trocar reserva - cancela com uma conta, reserva com outra
    Trocar {
        /// Codigo da reserva pra cancelar
        codigo: i64,
        /// Conta destino (numero)
        #[arg(long, default_value = "2")]
        destino: usize,
    },
}

// ===== CONFIG =====

#[derive(Serialize, Deserialize, Clone)]
struct AccountConfig {
    label: String,
    cpf: String,
    senha: String,
    condominio: i64,
    unidade: String,
}

struct Account {
    config: AccountConfig,
    token: String,
    nome: String,
}

impl Account {
    fn new(config: AccountConfig) -> Self {
        Self {
            config,
            token: String::new(),
            nome: String::new(),
        }
    }
}

fn config_path() -> PathBuf {
    let exe = std::env::current_exe().unwrap_or_default();
    let dir = exe.parent().unwrap_or(std::path::Path::new("."));
    // Check next to binary first, then current dir
    let next_to_exe = dir.join("accounts.json");
    if next_to_exe.exists() {
        return next_to_exe;
    }
    let cwd = std::env::current_dir().unwrap_or_default().join("accounts.json");
    if cwd.exists() {
        return cwd;
    }
    // Default: current dir
    cwd
}

fn load_accounts() -> Vec<AccountConfig> {
    let path = config_path();
    if path.exists() {
        let data = fs::read_to_string(&path).unwrap_or_default();
        serde_json::from_str(&data).unwrap_or_default()
    } else {
        Vec::new()
    }
}

fn save_accounts(accounts: &[AccountConfig]) {
    let path = config_path();
    let json = serde_json::to_string_pretty(accounts).unwrap();
    fs::write(path, json).ok();
}

// ===== HTTP CLIENT =====

struct HubClient {
    agent: ureq::Agent,
}

impl HubClient {
    fn new() -> Self {
        Self {
            agent: ureq::agent(),
        }
    }

    fn login(&self, account: &mut Account) -> bool {
        let creds = B64.encode(format!("{}:{}", account.config.cpf, account.config.senha));
        match self
            .agent
            .post(&format!("{API_ACCOUNTS}/api/v1/login"))
            .set("Authorization", &format!("Base {creds}"))
            .set("Origin", "app-morador")
            .set("Content-Type", "application/json")
            .call()
        {
            Ok(resp) => {
                if let Ok(data) = resp.into_json::<Value>() {
                    account.token = data["token"].as_str().unwrap_or("").to_string();
                    account.nome = data["nome"].as_str().unwrap_or("").to_string();
                    !account.token.is_empty()
                } else {
                    false
                }
            }
            Err(_) => false,
        }
    }

    fn get(&self, url: &str, token: &str) -> Result<Value, (u16, Value)> {
        match self
            .agent
            .get(url)
            .set("Authorization", &format!("Bearer {token}"))
            .set("Origin", "app-morador")
            .call()
        {
            Ok(resp) => resp.into_json::<Value>().map_err(|e| (0, json!({"error": e.to_string()}))),
            Err(ureq::Error::Status(code, resp)) => {
                let body = resp.into_json::<Value>().unwrap_or(json!({"error": "?"}));
                Err((code, body))
            }
            Err(e) => Err((502, json!({"error": e.to_string()}))),
        }
    }

    fn post(&self, url: &str, token: &str, body: &Value) -> (u16, Value) {
        match self
            .agent
            .post(url)
            .set("Authorization", &format!("Bearer {token}"))
            .set("Origin", "app-morador")
            .set("Content-Type", "application/json")
            .send_json(body.clone())
        {
            Ok(resp) => {
                let status = resp.status();
                let data = resp.into_json::<Value>().unwrap_or(json!({}));
                (status, data)
            }
            Err(ureq::Error::Status(code, resp)) => {
                let data = resp.into_json::<Value>().unwrap_or(json!({"error": "?"}));
                (code, data)
            }
            Err(e) => (502, json!({"error": e.to_string()})),
        }
    }

    fn listar_areas(&self, account: &Account) -> Vec<Value> {
        let url = format!(
            "{API_MORADOR}/api/v1/areas?codigoCondominio={}",
            account.config.condominio
        );
        match self.get(&url, &account.token) {
            Ok(Value::Array(arr)) => arr,
            _ => vec![],
        }
    }

    fn ver_horarios(&self, account: &Account, area: i64, data: &str) -> Vec<Value> {
        let unidade = urlencoding(&account.config.unidade);
        let url = format!(
            "{API_MORADOR}/api/v1/areas/{area}/datasDisponiveis\
             ?codigoCondominio={}\
             &unidade={unidade}\
             &dataInicial={data}T00:00:00\
             &dataFinal={data}T23:59:00",
            account.config.condominio
        );
        match self.get(&url, &account.token) {
            Ok(data) => {
                let mut slots = vec![];
                if let Some(datas) = data["datas"].as_array() {
                    for d in datas {
                        if let Some(periodos) = d["periodos"].as_array() {
                            for p in periodos {
                                slots.push(p.clone());
                            }
                        }
                    }
                }
                slots
            }
            Err((400, body)) => {
                let msg = if body.is_array() {
                    body[0].as_str().unwrap_or("Erro").to_string()
                } else {
                    body.to_string()
                };
                if msg.to_lowercase().contains("quantidade de reservas") {
                    eprintln!(
                        "  {} Reserva ativa nessa area! Use outra conta pra consultar.",
                        "⚠️".yellow()
                    );
                } else {
                    eprintln!("  {} {}", "⚠️".yellow(), msg);
                }
                vec![]
            }
            Err((_, body)) => {
                eprintln!("  {} {}", "❌".red(), body);
                vec![]
            }
        }
    }

    fn reservar(&self, account: &Account, area: i64, inicio: &str, fim: &str) -> (u16, Value) {
        let body = json!({
            "codigoArea": area,
            "codigoCondominio": account.config.condominio,
            "unidade": account.config.unidade,
            "quantPessoas": 1,
            "dataReserva": [{"dataInicial": inicio, "dataFinal": fim}],
            "observacoes": ""
        });
        self.post(
            &format!("{API_MORADOR}/api/v1/reservas"),
            &account.token,
            &body,
        )
    }

    fn cancelar(&self, account: &Account, codigo: i64) -> (u16, Value) {
        self.post(
            &format!("{API_MORADOR}/api/v1/reservas/{codigo}/cancelar"),
            &account.token,
            &json!({"motivo": "Aplicativo morador"}),
        )
    }

    fn todas_reservas(&self, account: &Account) -> Vec<Value> {
        let url = format!("{API_MORADOR}/api/v1/reservas");
        match self.get(&url, &account.token) {
            Ok(Value::Array(arr)) => arr
                .into_iter()
                .filter(|x| {
                    x["condominio"]["codigo"].as_i64() == Some(account.config.condominio)
                })
                .collect(),
            _ => vec![],
        }
    }

    fn minhas_reservas(&self, account: &Account) -> Vec<Value> {
        self.todas_reservas(account)
            .into_iter()
            .filter(|x| {
                x["unidade"].as_str() == Some(&account.config.unidade)
                    && x["situacao"]["codigo"].as_i64() == Some(2)
            })
            .collect()
    }
}

fn urlencoding(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                String::from(b as char)
            }
            _ => format!("%{:02X}", b),
        })
        .collect()
}

// ===== DISPLAY =====

fn banner() {
    println!();
    println!("{}", "╔══════════════════════════════════════════╗".cyan());
    println!(
        "{}     {} {}        {}",
        "║".cyan(),
        "🏢 HUB 2.0 - AUTO BOOKING ⚡".white().bold(),
        " ",
        "║".cyan()
    );
    println!(
        "{}     {}         {}",
        "║".cyan(),
        "Reserva na velocidade da API".dimmed(),
        "║".cyan()
    );
    println!("{}", "╚══════════════════════════════════════════╝".cyan());
}

fn pick_account(accounts: &[Account]) -> Option<usize> {
    if accounts.is_empty() {
        eprintln!("  {} Nenhuma conta configurada.", "❌".red());
        return None;
    }
    if accounts.len() == 1 {
        return Some(0);
    }
    let items: Vec<String> = accounts
        .iter()
        .map(|a| {
            let nome = if a.nome.is_empty() {
                &a.config.cpf
            } else {
                &a.nome
            };
            format!("{} — {} | {}", a.config.label, nome, a.config.unidade)
        })
        .collect();

    Select::new()
        .with_prompt("Conta")
        .items(&items)
        .default(0)
        .interact()
        .ok()
}

fn show_areas(client: &HubClient, account: &Account) {
    let areas = client.listar_areas(account);
    if areas.is_empty() {
        println!("  {} Nenhuma area encontrada.", "❌".red());
        return;
    }

    // Group by type
    let mut tipos: std::collections::BTreeMap<String, Vec<&Value>> =
        std::collections::BTreeMap::new();
    for a in &areas {
        let t = a["tipoArea"]["descricao"]
            .as_str()
            .unwrap_or("Outros")
            .to_string();
        tipos.entry(t).or_default().push(a);
    }

    println!();
    println!("  {:>4}  {:<40}", "Cod".bold(), "Espaco".bold());
    println!("  {}", "=".repeat(50));
    for (tipo, mut items) in tipos {
        println!("\n  {}", format!("── {} ──", tipo).cyan());
        items.sort_by_key(|a| a["codigoArea"].as_i64().unwrap_or(0));
        for a in items {
            let cod = a["codigoArea"]
                .as_i64()
                .or_else(|| a["codigo"].as_i64())
                .unwrap_or(0);
            let nome = a["nomeArea"]
                .as_str()
                .or_else(|| a["descricao"].as_str())
                .unwrap_or("?")
                .trim();
            println!("  {:>4}  {}", cod, nome);
        }
    }
}

fn show_horarios(client: &HubClient, account: &Account, area: i64, data: &str) -> Vec<Value> {
    let slots = client.ver_horarios(account, area, data);
    if slots.is_empty() {
        println!(
            "\n  {} Sem horarios disponiveis em {}",
            "❌".red(),
            data
        );
        return vec![];
    }
    println!("\n  {} Area {} — {}\n", "📅".cyan(), area, data);
    for (i, s) in slots.iter().enumerate() {
        let ini = s["dataInicio"].as_str().unwrap_or("?");
        let fim = s["dataTermino"].as_str().unwrap_or("?");
        let vagas = s["quantidadeDeVagas"].as_i64().unwrap_or(0);
        let h_ini = &ini[11..16.min(ini.len())];
        let h_fim = &fim[11..16.min(fim.len())];
        let icon = if vagas > 0 {
            "✅".green().to_string()
        } else {
            "❌".red().to_string()
        };
        println!(
            "  {:>3}. {} {} - {}  ({} vaga{})",
            i + 1,
            icon,
            h_ini,
            h_fim,
            vagas,
            if vagas != 1 { "s" } else { "" }
        );
    }
    slots
}

fn show_espiao(client: &HubClient, account: &Account, data: &str) {
    println!(
        "\n  {} MODO ESPIAO — reservas para {}\n",
        "🕵️".purple(),
        data
    );
    let reservas = client.todas_reservas(account);
    let mut filtradas: Vec<&Value> = reservas
        .iter()
        .filter(|r| {
            r["dataInicial"]
                .as_str()
                .unwrap_or("")
                .starts_with(data)
        })
        .collect();

    if filtradas.is_empty() {
        println!("  Nenhuma reserva encontrada para essa data.");
        return;
    }

    filtradas.sort_by(|a, b| {
        let sa = a["dataSolicitacao"].as_str().unwrap_or("");
        let sb = b["dataSolicitacao"].as_str().unwrap_or("");
        sa.cmp(sb)
    });

    println!(
        "  {:>26}  {:<28}  {:>11}  {:<28}  {}",
        "Solicitado em".dimmed(),
        "Area".dimmed(),
        "Horario".dimmed(),
        "Nome".dimmed(),
        "Unid".dimmed()
    );
    println!("  {}", "-".repeat(110));

    let mut rapidos = 0;
    let mut primeiro_rapido = String::new();

    for r in &filtradas {
        let sol = r["dataSolicitacao"].as_str().unwrap_or("?");
        let area = r["area"]["descricao"]
            .as_str()
            .unwrap_or("?")
            .trim();
        let area_trunc: String = area.chars().take(27).collect();
        let di = r["dataInicial"].as_str().unwrap_or("?");
        let df = r["dataFinal"].as_str().unwrap_or("?");
        let h_ini = if di.len() >= 16 { &di[11..16] } else { "?" };
        let h_fim = if df.len() >= 16 { &df[11..16] } else { "?" };
        let nome: String = r["nome"]
            .as_str()
            .unwrap_or("?")
            .chars()
            .take(27)
            .collect();
        let unid = r["unidade"].as_str().unwrap_or("?");

        // Speed badge
        let mut badge = String::new();
        if sol.len() >= 19 {
            let h: u32 = sol[11..13].parse().unwrap_or(99);
            let m: u32 = sol[14..16].parse().unwrap_or(99);
            let s: u32 = sol[17..19].parse().unwrap_or(99);
            if h == 0 && m == 0 && s <= 30 {
                badge = format!(" {}", "⚡ SPEED".red().bold());
                rapidos += 1;
                if primeiro_rapido.is_empty() {
                    primeiro_rapido = sol.to_string();
                }
            } else if h == 0 && m <= 1 {
                badge = format!(" {}", "🏎️ RAPIDO".yellow());
                rapidos += 1;
                if primeiro_rapido.is_empty() {
                    primeiro_rapido = sol.to_string();
                }
            }
        }

        println!(
            "  {:>26}{}  {:<28}  {}-{:>5}  {:<28}  {}",
            sol, badge, area_trunc, h_ini, h_fim, nome, unid
        );
    }

    if rapidos > 0 {
        println!(
            "\n  {} {} reservas nos primeiros 60 segundos!",
            "🏎️".yellow(),
            rapidos.to_string().yellow().bold()
        );
        println!("  {} Mais rapido: {}", "".dimmed(), primeiro_rapido.dimmed());
    }
}

fn do_sniper(client: &HubClient, account: &mut Account, area: i64, data: &str, hora: &str, disparo: &str) {
    let parts: Vec<&str> = hora.split(':').collect();
    let h: u32 = parts[0].parse().unwrap_or(20);
    let m: u32 = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);

    let inicio = format!("{data}T{:02}:{:02}:00", h, m);
    let h_fim = h + 1;
    let fim = format!("{data}T{:02}:{:02}:00", h_fim, m);

    let d_parts: Vec<&str> = disparo.split(':').collect();
    let dh: u32 = d_parts[0].parse().unwrap_or(0);
    let dm: u32 = d_parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);
    let target_time = NaiveTime::from_hms_opt(dh, dm, 0).unwrap();

    println!("\n  {}", "🎯 MODO SNIPER ATIVADO".green().bold());
    println!(
        "  {} Area {} | {} {} {}",
        "📍".cyan(),
        area,
        "📅",
        data,
        hora
    );
    println!(
        "  {} {} ({})",
        "👤".cyan(),
        account.config.label,
        account.nome
    );
    println!(
        "  {} Disparo as {}",
        "⏰".yellow(),
        format!("{:02}:{:02}:00", dh, dm)
    );
    println!("  {}", "⏳ Ctrl+C para cancelar".dimmed());
    println!();

    let mut relogged = false;

    loop {
        let now = Local::now();
        let now_time = now.time();
        let mut diff = (target_time - now_time).num_seconds();

        // If target already passed today, it's for tomorrow
        if diff < -2 {
            diff += 86400;
        }

        if diff <= 0 {
            break;
        }

        if diff <= 5 && !relogged {
            println!("\n  {} Renovando token...", "🔄".blue());
            client.login(account);
            relogged = true;
        }

        let hh = diff / 3600;
        let mm = (diff % 3600) / 60;
        let ss = diff % 60;

        let countdown = format!("{:02}:{:02}:{:02}", hh, mm, ss);
        let colored = if diff <= 10 {
            countdown.red().to_string()
        } else if diff <= 60 {
            countdown.yellow().to_string()
        } else {
            countdown.cyan().to_string()
        };
        print!("\r  ⏱️  {}  ", colored);
        use std::io::Write;
        std::io::stdout().flush().ok();
        thread::sleep(Duration::from_millis(100));
    }

    let ts = Local::now().format("%H:%M:%S%.3f").to_string();
    println!("\n\n  {} [{}]", "🚀 DISPARANDO!".green().bold(), ts);

    for i in 1..=10 {
        let ts = Local::now().format("%H:%M:%S%.3f").to_string();
        let (status, body) = client.reservar(account, area, &inicio, &fim);
        if status == 200 {
            let cod = body["codigoReserva"].as_i64().unwrap_or(0);
            println!(
                "\n  {} as {}!",
                "✅ RESERVA CONFIRMADA".green().bold(),
                ts
            );
            println!("  {} Codigo: {}", "📋".green(), cod);
            println!("  {} {} {}", "📅".green(), data, hora);
            return;
        }
        let msg = if body.is_array() {
            body[0].as_str().unwrap_or("?").to_string()
        } else {
            body.to_string()
        };
        println!("  {} Tentativa {} [{}]: {}", "❌".red(), i, ts, msg);
        if msg.to_lowercase().contains("não está disponível") {
            println!("  {}", "💀 Ja pegaram!".red().bold());
            return;
        }
        thread::sleep(Duration::from_millis(20));
    }

    println!("  {}", "💀 Falhou apos 10 tentativas.".red().bold());
}

fn do_trocar(client: &HubClient, accounts: &mut Vec<Account>, src_idx: usize, dst_idx: usize, cod_reserva: i64) {
    println!("\n  {}", "🔄 TROCA DE RESERVA".purple().bold());

    // Find reservation in source account
    let reservas = client.minhas_reservas(&accounts[src_idx]);
    let reserva = reservas.iter().find(|r| r["codigoReserva"].as_i64() == Some(cod_reserva));
    let reserva = match reserva {
        Some(r) => r.clone(),
        None => {
            println!("  {} Reserva #{} nao encontrada na conta {}.",
                "❌".red(), cod_reserva, accounts[src_idx].config.label);
            return;
        }
    };

    let area_cod = reserva["area"]["codigo"].as_i64().unwrap_or(0);
    let area_nome = reserva["area"]["descricao"].as_str().unwrap_or("?").trim();
    // Clean dates: strip ms and Z
    let inicio_raw = reserva["dataInicial"].as_str().unwrap_or("?");
    let fim_raw = reserva["dataFinal"].as_str().unwrap_or("?");
    let inicio = inicio_raw.split('.').next().unwrap_or(inicio_raw).replace("Z", "");
    let fim = fim_raw.split('.').next().unwrap_or(fim_raw).replace("Z", "");
    let h_ini = if inicio.len() >= 16 { &inicio[11..16] } else { "?" };
    let h_fim = if fim.len() >= 16 { &fim[11..16] } else { "?" };

    println!("  {} #{} ({}) com {}", "CANCELAR".red(), cod_reserva, area_nome, accounts[src_idx].config.label);
    println!("  {} {} {}-{} com {}", "RESERVAR".green(), area_nome, h_ini, h_fim, accounts[dst_idx].config.label);
    println!("\n  {}", "⚠️  Se a reserva falhar apos cancelar, o slot fica livre!".yellow());

    // Refresh tokens
    println!("\n  {} Renovando tokens...", "🔄".blue());
    client.login(&mut accounts[src_idx]);
    if src_idx != dst_idx {
        client.login(&mut accounts[dst_idx]);
    }

    // EXECUTE
    let t0 = std::time::Instant::now();

    print!("  {} Cancelando #{}... ", "❌".red(), cod_reserva);
    use std::io::Write;
    std::io::stdout().flush().ok();

    let (status, body) = client.cancelar(&accounts[src_idx], cod_reserva);
    if status != 200 {
        let msg = if body.is_array() {
            body[0].as_str().unwrap_or("?").to_string()
        } else {
            body.to_string()
        };
        println!("\n  {} Cancel falhou: {}", "❌".red(), msg);
        return;
    }
    let t_cancel = t0.elapsed();
    println!("{} ({}ms)", "OK".green(), t_cancel.as_millis());

    // Reserve burst
    for attempt in 1..=5 {
        let ts = Local::now().format("%H:%M:%S%.3f").to_string();
        let (status, body) = client.reservar(&accounts[dst_idx], area_cod, &inicio, &fim);

        if status == 200 {
            let novo_cod = body["codigoReserva"].as_i64().unwrap_or(0);
            let elapsed = t0.elapsed();
            println!(
                "  {} [{}]! Codigo: {} ({}ms total)",
                "✅ RESERVA CRIADA".green().bold(), ts, novo_cod, elapsed.as_millis()
            );
            return;
        }

        let msg = if body.is_array() {
            body[0].as_str().unwrap_or("?").to_string()
        } else {
            body.to_string()
        };
        println!("  {} Tentativa {} [{}]: {}", "⏳".yellow(), attempt, ts, msg);

        if msg.to_lowercase().contains("não está disponível") {
            println!("  {}", "💀 Alguem pegou o slot entre cancel e reserve!".red().bold());
            return;
        }
        if msg.to_lowercase().contains("quantidade de reservas") {
            println!("  {}", "❌ Conta destino ja tem reserva ativa nesse tipo!".red().bold());
            return;
        }
        if attempt >= 3 {
            thread::sleep(Duration::from_millis(50));
        }
    }

    println!("  {}", "💀 Falhou. Reserva cancelada mas nova nao criou!".red().bold());
}

// ===== INTERACTIVE MENU =====

fn interactive_menu(client: &HubClient, accounts: &mut Vec<Account>, configs: &mut Vec<AccountConfig>) {
    loop {
        println!("\n  {}", "┌──────────────────────────────────┐".cyan());
        println!("  {} 1. Gerenciar contas              {}", "│".cyan(), "│".cyan());
        println!("  {} 2. Ver espacos                   {}", "│".cyan(), "│".cyan());
        println!("  {} 3. Ver horarios                  {}", "│".cyan(), "│".cyan());
        println!("  {} 4. Reservar                      {}", "│".cyan(), "│".cyan());
        println!("  {} 5. Sniper (agendar meia-noite)   {}", "│".cyan(), "│".cyan());
        println!("  {} 6. Minhas reservas               {}", "│".cyan(), "│".cyan());
        println!("  {} 7. Cancelar reserva              {}", "│".cyan(), "│".cyan());
        println!("  {} 8. Espiao (quem reservou)        {}", "│".cyan(), "│".cyan());
        println!("  {} 9. Trocar reserva (cancel+book)  {}", "│".cyan(), "│".cyan());
        println!("  {} 0. Sair                          {}", "│".cyan(), "│".cyan());
        println!("  {}", "└──────────────────────────────────┘".cyan());

        for a in accounts.iter() {
            if !a.token.is_empty() {
                println!("  {} {}: {}", "👤".dimmed(), a.config.label.dimmed(), a.nome.dimmed());
            }
        }

        let op: String = Input::new()
            .with_prompt("  >")
            .interact_text()
            .unwrap_or_default();

        match op.trim() {
            "1" => {
                manage_accounts(client, accounts, configs);
            }
            "2" => {
                if let Some(idx) = pick_account(accounts) {
                    show_areas(client, &accounts[idx]);
                }
            }
            "3" => {
                if let Some(idx) = pick_account(accounts) {
                    let area: String = Input::new()
                        .with_prompt("  Codigo da area")
                        .interact_text()
                        .unwrap_or_default();
                    let default_date = (Local::now() + chrono::Duration::days(7))
                        .format("%Y-%m-%d")
                        .to_string();
                    let data: String = Input::new()
                        .with_prompt("  Data (YYYY-MM-DD)")
                        .default(default_date)
                        .interact_text()
                        .unwrap_or_default();
                    let area_n: i64 = area.trim().parse().unwrap_or(0);
                    show_horarios(client, &accounts[idx], area_n, data.trim());
                }
            }
            "4" => {
                if let Some(idx) = pick_account(accounts) {
                    let area: String = Input::new()
                        .with_prompt("  Codigo da area")
                        .interact_text()
                        .unwrap_or_default();
                    let data: String = Input::new()
                        .with_prompt("  Data (YYYY-MM-DD)")
                        .interact_text()
                        .unwrap_or_default();
                    let area_n: i64 = area.trim().parse().unwrap_or(0);

                    // Use different account for consulting if available
                    let consult_idx = if accounts.len() > 1 {
                        println!("  {} Conta pra consultar horarios:", "💡".dimmed());
                        pick_account(accounts).unwrap_or(idx)
                    } else {
                        idx
                    };

                    let slots = show_horarios(client, &accounts[consult_idx], area_n, data.trim());
                    if slots.is_empty() {
                        continue;
                    }
                    let n: String = Input::new()
                        .with_prompt("\n  Numero do horario")
                        .interact_text()
                        .unwrap_or_default();
                    let slot_idx: usize = n.trim().parse::<usize>().unwrap_or(1) - 1;
                    if slot_idx >= slots.len() {
                        continue;
                    }
                    let ini = slots[slot_idx]["dataInicio"].as_str().unwrap_or("?");
                    let fim = slots[slot_idx]["dataTermino"].as_str().unwrap_or("?");
                    println!(
                        "\n  ⏳ Reservando {} - {} com {}...",
                        &ini[11..16.min(ini.len())],
                        &fim[11..16.min(fim.len())],
                        accounts[idx].config.label
                    );
                    let (status, body) = client.reservar(&accounts[idx], area_n, ini, fim);
                    if status == 200 {
                        let cod = body["codigoReserva"].as_i64().unwrap_or(0);
                        println!(
                            "  {} Codigo: {}",
                            "✅ RESERVA CRIADA!".green().bold(),
                            cod
                        );
                    } else {
                        let msg = if body.is_array() {
                            body[0].as_str().unwrap_or("?").to_string()
                        } else {
                            body.to_string()
                        };
                        println!("  {} {}", "❌".red(), msg);
                    }
                }
            }
            "5" => {
                if let Some(idx) = pick_account(accounts) {
                    println!("\n  {}", "⏰ SNIPER — Dispara reserva na hora exata".yellow());
                    println!("  {}", "💡 Reservas abrem a MEIA-NOITE (00:00:00)".dimmed());
                    let area: String = Input::new()
                        .with_prompt("  Codigo da area")
                        .interact_text()
                        .unwrap_or_default();
                    let data: String = Input::new()
                        .with_prompt("  Data da reserva (YYYY-MM-DD)")
                        .interact_text()
                        .unwrap_or_default();
                    let hora: String = Input::new()
                        .with_prompt("  Horario desejado (HH:MM)")
                        .interact_text()
                        .unwrap_or_default();
                    let disparo: String = Input::new()
                        .with_prompt("  Hora do disparo")
                        .default("00:00".to_string())
                        .interact_text()
                        .unwrap_or_default();
                    do_sniper(
                        client,
                        &mut accounts[idx],
                        area.trim().parse().unwrap_or(0),
                        data.trim(),
                        hora.trim(),
                        disparo.trim(),
                    );
                }
            }
            "6" => {
                if let Some(idx) = pick_account(accounts) {
                    let reservas = client.minhas_reservas(&accounts[idx]);
                    if reservas.is_empty() {
                        println!("\n  {}", "Nenhuma reserva ativa.".dimmed());
                        continue;
                    }
                    println!(
                        "\n  {:>8}  {:<35}  {:>12}  {}",
                        "Cod".bold(),
                        "Espaco".bold(),
                        "Data".bold(),
                        "Horario".bold()
                    );
                    println!("  {}", "-".repeat(70));
                    for r in &reservas {
                        let cod = r["codigoReserva"].as_i64().unwrap_or(0);
                        let area = r["area"]["descricao"].as_str().unwrap_or("?").trim();
                        let di = r["dataInicial"].as_str().unwrap_or("?");
                        let df = r["dataFinal"].as_str().unwrap_or("?");
                        let data = &di[..10.min(di.len())];
                        let h_ini = if di.len() >= 16 { &di[11..16] } else { "?" };
                        let h_fim = if df.len() >= 16 { &df[11..16] } else { "?" };
                        println!(
                            "  {:>8}  {:<35}  {:>12}  {}-{}",
                            cod, area, data, h_ini, h_fim
                        );
                    }
                }
            }
            "7" => {
                if let Some(idx) = pick_account(accounts) {
                    let cod: String = Input::new()
                        .with_prompt("  Codigo da reserva")
                        .interact_text()
                        .unwrap_or_default();
                    let cod_n: i64 = cod.trim().parse().unwrap_or(0);
                    let (status, body) = client.cancelar(&accounts[idx], cod_n);
                    if status == 200 {
                        println!("  {}", "✅ Cancelada!".green());
                    } else {
                        println!("  {} {}", "❌".red(), body);
                    }
                }
            }
            "8" => {
                if let Some(idx) = pick_account(accounts) {
                    let default_date = (Local::now() + chrono::Duration::days(1))
                        .format("%Y-%m-%d")
                        .to_string();
                    let data: String = Input::new()
                        .with_prompt("  Data pra espiar (YYYY-MM-DD)")
                        .default(default_date)
                        .interact_text()
                        .unwrap_or_default();
                    show_espiao(client, &accounts[idx], data.trim());
                }
            }
            "9" => {
                if accounts.len() < 2 {
                    println!("  {} Troca precisa de 2+ contas.", "⚠️".yellow());
                }
                if let Some(src_idx) = pick_account(accounts) {
                    let reservas = client.minhas_reservas(&accounts[src_idx]);
                    if reservas.is_empty() {
                        println!("  {} Nenhuma reserva ativa.", "❌".red());
                        continue;
                    }
                    println!("\n  {:>3}  {:>8}  {:<35}  {:>12}  {}", "#".bold(), "Cod".bold(), "Espaco".bold(), "Data".bold(), "Horario".bold());
                    println!("  {}", "-".repeat(75));
                    for (i, r) in reservas.iter().enumerate() {
                        let cod = r["codigoReserva"].as_i64().unwrap_or(0);
                        let area = r["area"]["descricao"].as_str().unwrap_or("?").trim();
                        let di = r["dataInicial"].as_str().unwrap_or("?");
                        let df = r["dataFinal"].as_str().unwrap_or("?");
                        let h_ini = if di.len() >= 16 { &di[11..16] } else { "?" };
                        let h_fim = if df.len() >= 16 { &df[11..16] } else { "?" };
                        println!("  {:>3}  {:>8}  {:<35}  {:>12}  {}-{}", i + 1, cod, area, &di[..10.min(di.len())], h_ini, h_fim);
                    }
                    let n: String = Input::new()
                        .with_prompt("\n  Numero da reserva")
                        .interact_text()
                        .unwrap_or_default();
                    let r_idx: usize = n.trim().parse::<usize>().unwrap_or(1) - 1;
                    if r_idx >= reservas.len() { continue; }
                    let cod = reservas[r_idx]["codigoReserva"].as_i64().unwrap_or(0);

                    println!("  {} Conta que vai RESERVAR:", "💡".dimmed());
                    if let Some(dst_idx) = pick_account(accounts) {
                        do_trocar(client, accounts, src_idx, dst_idx, cod);
                    }
                }
            }
            "0" => break,
            _ => {}
        }
    }
}

fn manage_accounts(client: &HubClient, accounts: &mut Vec<Account>, configs: &mut Vec<AccountConfig>) {
    println!("\n  {}\n", "GERENCIAR CONTAS".cyan().bold());
    if !accounts.is_empty() {
        for (i, a) in accounts.iter().enumerate() {
            println!(
                "    {}. {} — CPF: {} | Cond: {} | Unid: {}",
                i + 1,
                a.config.label,
                a.config.cpf,
                a.config.condominio,
                a.config.unidade
            );
        }
    } else {
        println!("    Nenhuma conta cadastrada.");
    }

    let items = vec!["Adicionar", "Remover", "Voltar"];
    let sel = Select::new()
        .with_prompt("  Acao")
        .items(&items)
        .default(2)
        .interact()
        .unwrap_or(2);

    match sel {
        0 => {
            let label: String = Input::new()
                .with_prompt("  Label")
                .interact_text()
                .unwrap_or_default();
            let cpf: String = Input::new()
                .with_prompt("  CPF")
                .interact_text()
                .unwrap_or_default();
            let senha: String = Input::new()
                .with_prompt("  Senha")
                .interact_text()
                .unwrap_or_default();
            let condo: String = Input::new()
                .with_prompt("  Condominio")
                .default("2078".to_string())
                .interact_text()
                .unwrap_or_default();
            let unid: String = Input::new()
                .with_prompt("  Unidade")
                .interact_text()
                .unwrap_or_default();

            let config = AccountConfig {
                label: label.trim().to_string(),
                cpf: cpf.trim().to_string(),
                senha: senha.trim().to_string(),
                condominio: condo.trim().parse().unwrap_or(2078),
                unidade: unid.trim().to_string(),
            };
            let mut account = Account::new(config.clone());
            if client.login(&mut account) {
                println!(
                    "  {} {}: {}",
                    "✅".green(),
                    account.config.label,
                    account.nome
                );
                configs.push(config);
                save_accounts(configs);
                accounts.push(account);
            } else {
                println!("  {} Falha no login", "❌".red());
            }
        }
        1 => {
            if accounts.is_empty() {
                return;
            }
            let items: Vec<String> = accounts.iter().map(|a| a.config.label.clone()).collect();
            if let Ok(idx) = Select::new().with_prompt("Remover").items(&items).interact() {
                let removed = accounts.remove(idx);
                configs.retain(|c| c.cpf != removed.config.cpf);
                save_accounts(configs);
                println!("  {} Conta '{}' removida.", "✅".yellow(), removed.config.label);
            }
        }
        _ => {}
    }
}

// ===== MAIN =====

fn main() {
    let cli = Cli::parse();

    banner();

    let mut configs = load_accounts();
    if configs.is_empty() {
        println!("  {} Nenhuma conta em accounts.json", "⚠️".yellow());
        println!("  {}", "Criando config inicial...".dimmed());

        let label: String = Input::new()
            .with_prompt("  Label (ex: Marlon)")
            .default("Principal".to_string())
            .interact_text()
            .unwrap_or_default();
        let cpf: String = Input::new()
            .with_prompt("  CPF")
            .interact_text()
            .unwrap_or_default();
        let senha: String = Input::new()
            .with_prompt("  Senha")
            .interact_text()
            .unwrap_or_default();
        let condo: String = Input::new()
            .with_prompt("  Condominio")
            .default("2078".to_string())
            .interact_text()
            .unwrap_or_default();
        let unid: String = Input::new()
            .with_prompt("  Unidade")
            .interact_text()
            .unwrap_or_default();

        configs.push(AccountConfig {
            label: label.trim().to_string(),
            cpf: cpf.trim().to_string(),
            senha: senha.trim().to_string(),
            condominio: condo.trim().parse().unwrap_or(2078),
            unidade: unid.trim().to_string(),
        });
        save_accounts(&configs);
        println!("  {} Salvo!", "✅".green());
    }

    let client = HubClient::new();

    // Login all accounts
    let mut accounts: Vec<Account> = Vec::new();
    for cfg in &configs {
        let mut account = Account::new(cfg.clone());
        if client.login(&mut account) {
            println!(
                "  {} {}: {} | {}",
                "✅".green(),
                account.config.label,
                account.nome,
                account.config.unidade
            );
            accounts.push(account);
        } else {
            println!(
                "  {} {}: falha no login ({})",
                "❌".red(),
                cfg.label,
                cfg.cpf
            );
        }
    }

    if accounts.is_empty() {
        eprintln!("\n  {} Nenhuma conta logou. Verifique accounts.json", "❌".red());
        process::exit(1);
    }

    println!();

    // CLI subcommand mode
    if let Some(cmd) = cli.cmd {
        let idx = (cli.conta - 1).min(accounts.len() - 1);
        match cmd {
            Cmd::Listar => show_areas(&client, &accounts[idx]),
            Cmd::Horarios { area, data } => {
                show_horarios(&client, &accounts[idx], area, &data);
            }
            Cmd::Reservar { area, data, hora } => {
                let parts: Vec<&str> = hora.split(':').collect();
                let h: u32 = parts[0].parse().unwrap_or(20);
                let m: u32 = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);
                let inicio = format!("{data}T{:02}:{:02}:00", h, m);
                let fim = format!("{data}T{:02}:{:02}:00", h + 1, m);
                let (status, body) = client.reservar(&accounts[idx], area, &inicio, &fim);
                if status == 200 {
                    let cod = body["codigoReserva"].as_i64().unwrap_or(0);
                    println!(
                        "  {} Codigo: {}",
                        "✅ Reserva criada!".green().bold(),
                        cod
                    );
                } else {
                    let msg = if body.is_array() {
                        body[0].as_str().unwrap_or("?").to_string()
                    } else {
                        body.to_string()
                    };
                    println!("  {} {}", "❌".red(), msg);
                }
            }
            Cmd::Sniper {
                area,
                data,
                hora,
                disparo,
            } => {
                do_sniper(&client, &mut accounts[idx], area, &data, &hora, &disparo);
            }
            Cmd::Minhas => {
                let reservas = client.minhas_reservas(&accounts[idx]);
                if reservas.is_empty() {
                    println!("  Nenhuma reserva ativa.");
                }
                for r in &reservas {
                    let cod = r["codigoReserva"].as_i64().unwrap_or(0);
                    let area = r["area"]["descricao"].as_str().unwrap_or("?").trim();
                    let di = r["dataInicial"].as_str().unwrap_or("?");
                    let df = r["dataFinal"].as_str().unwrap_or("?");
                    let h_ini = if di.len() >= 16 { &di[11..16] } else { "?" };
                    let h_fim = if df.len() >= 16 { &df[11..16] } else { "?" };
                    println!(
                        "  {:>8}  {:<35}  {}  {}-{}",
                        cod,
                        area,
                        &di[..10.min(di.len())],
                        h_ini,
                        h_fim
                    );
                }
            }
            Cmd::Cancelar { codigo } => {
                let (status, body) = client.cancelar(&accounts[idx], codigo);
                if status == 200 {
                    println!("  {}", "✅ Cancelada!".green());
                } else {
                    println!("  {} {}", "❌".red(), body);
                }
            }
            Cmd::Espiao { data } => {
                show_espiao(&client, &accounts[idx], &data);
            }
            Cmd::Trocar { codigo, destino } => {
                let dst_idx = (destino - 1).min(accounts.len() - 1);
                do_trocar(&client, &mut accounts, idx, dst_idx, codigo);
            }
        }
        return;
    }

    // Interactive menu
    interactive_menu(&client, &mut accounts, &mut configs);
}
