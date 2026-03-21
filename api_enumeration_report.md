# Hub 2.0 API Enumeration Report
**Date:** 2026-03-21
**Target:** api-accounts.hubert.com.br / api-morador.hubert.com.br

---

## CRITICAL FINDING: Swagger Spec Exposed in Production

Both APIs expose their full Swagger/OpenAPI specification at:
- `https://api-accounts.hubert.com.br/swagger/v1/swagger.json` (29KB - 200 OK)
- `https://api-morador.hubert.com.br/swagger/v1/swagger.json` (122KB - 200 OK)

The Swagger UI itself returns 404, but the raw JSON spec is fully accessible with any valid Bearer token.
This reveals the **complete API surface**, including internal/admin endpoints.

---

## CRITICAL FINDING: IDOR on Multiple Endpoints

Several endpoints accept arbitrary `codigoCondominio` without validating if the authenticated user belongs to that condominio:

### Confirmed IDOR - Data Leaks:

| Endpoint | Severity | Data Exposed |
|---|---|---|
| `GET /api/v1/aplicativo/{cond}` | Medium | Menu config, feature flags per condominio |
| `GET /api/v1/areaConfiguracao/{cond}` | High | Full area config, rules, email contacts |
| `GET /api/v1/portaria/{cond}/veiculo` | **CRITICAL** | Vehicle plates, owner names, unit numbers |
| `GET /api/v1/liberacaoAcesso/{cond}/ativas` | **CRITICAL** | Full names, CPFs, RGs, photos, access authorizations |
| `GET /api/v1/financeiro/{cond}/prestacaocontas/periodos` | High | Financial periods, accounting data |
| `GET /api/v1/areas` | High | Returns ALL areas across ALL condominios (1.2MB response!) |
| `GET /api/v1/reservas` | **CRITICAL** | Returns ALL reservations across ALL condominios (1.5MB!) |

### IDOR Blocked (authorization checked):
- `GET /api/v1/cnd/{cond}/situacao/{unid}` - "Usuário não possui permissão"
- `GET /api/v1/tokenEntrega/{cond}/token/{unid}` - "Usuário não possui permissão"
- `GET /api/v1/pessoas/{cpf}/emails` (accounts) - "Não autorizado"

---

## All Discovered Endpoints

### api-accounts.hubert.com.br (Accounts API)

#### Auth & Login
| Method | Path | Status | Notes |
|---|---|---|---|
| POST | `/api/v1/login` | 405 (GET) | Login endpoint |
| POST | `/api/login/v1` | - | Legacy login |
| GET | `/api/v1/login/AcessosUsuario` | 204 | Returns user accesses |
| GET | `/api/v1/login/validaracesso` | 200 | "Token de acesso válido." |
| GET | `/api/v1/login/dispcadastrologin` | 400 | Requires Email param |
| POST | `/api/v1/login/alterarsenha` | - | Change password |
| POST | `/api/v1/login/esquecisenha` | - | Forgot password |
| POST | `/api/v1/login/efetivaesquecisenha` | - | Effectuate password reset |
| GET | `/api/v1/login/validaesquecisenhatoken` | - | Validate reset token |

#### MFA
| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/login/configuraMFA` | Configure MFA |
| POST | `/api/v1/login/finalizaMFA` | Finalize MFA setup |
| POST | `/api/v1/login/validaMFA` | Validate MFA |
| POST | `/api/v1/login/verificaMFA` | Verify MFA |
| POST | `/api/v1/login/configuratelefoneMFA` | Configure phone MFA |
| POST | `/api/v1/login/finalizatelefoneMFA` | Finalize phone MFA |

#### Employee Management (Hidden!)
| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/login/funcionario/{codFunc}/criarLogin` | Create employee login |
| POST | `/api/v1/login/funcionario/{codFunc}/resetarLogin` | Reset employee login |

#### People / Registration
| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/pessoas/{cpfCnpj}/cadastroBasico` | Basic registration by CPF |
| PUT | `/api/v1/pessoas/{codPessoa}/cadastroBasico` | Update registration |
| GET | `/api/v1/pessoas/{cpfCnpj}/emails` | Get emails by CPF (blocked) |
| POST | `/api/v1/pessoas/{codPessoa}/emails/{codEmail}/cadastrarSenha` | Register password |
| POST | `/api/v1/pessoas/{codPessoa}/emails/{codEmail}/enviarToken` | Send email token |
| POST | `/api/v1/pessoas/{codPessoa}/emails/{codEmail}/efetivarToken` | Effectuate email token |

#### Pre-Authorization / Invites
| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/preautorizacao` | Send invite |
| POST | `/api/v1/preautorizacao/efetivacadastro` | Accept invite |
| POST | `/api/v1/preautorizacao/cadastroproprietario` | Owner registration |
| GET | `/api/v1/preautorizacao/proprietario` | Owner invite |
| GET | `/api/v1/preautorizacao/validatoken` | Validate invite token |

#### LGPD Terms
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/termosLgpd` | 200 | Lists all LGPD terms |
| GET | `/api/v1/termosLgpd/termosAssinados` | 200 | User's signed terms |
| GET | `/api/v1/termosLgpd/termosAssinadosApp` | - | App-specific signed terms |
| GET | `/api/v1/termosLgpd/termosAssinadosPortal/{codUsuario}` | - | Portal signed terms (IDOR?) |
| GET | `/api/v1/termosLgpd/{codTermo}` | - | Get specific term |
| POST | `/api/v1/termosLgpd/{codTermo}/assinatura` | - | Sign term |
| POST | `/api/v1/termosLgpd/{codTermo}/assinaturaPortal/{codUsuario}` | - | Sign for portal (IDOR?) |

#### Misc
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/healthcheck` | 200 | App name, SQL datetime, server info |
| POST | `/api/v1/captcha` | - | reCAPTCHA verification |
| GET | `/api/template/v1/gettemplate` | 400 | Template retrieval |
| POST | `/api/template/v1/inserirtemplate` | - | Template insertion |

---

### api-morador.hubert.com.br (Morador API)

#### Areas & Reservations
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/areas` | 200 (1.2MB) | **ALL areas, ALL condominios!** |
| GET | `/api/v1/areas/tipos` | 200 | Area types list |
| GET | `/api/v1/areas/{codArea}` | 200/400 | Specific area |
| GET | `/api/v1/areas/{codArea}/regras` | 200 | Area rules/regulations |
| GET | `/api/v1/areas/{codArea}/datasDisponiveis` | 500 | Available dates |
| GET | `/api/v1/areas/{codArea}/datasOcupadas` | 400 | Occupied dates |
| GET | `/api/v1/areas/{codArea}/bloqueio` | 400 | Blocked dates |
| GET | `/api/v1/areas/{codArea}/configuracaoDePeriodos` | 200 | Period config |
| GET | `/api/v1/areas/{codArea}/configuracaoDePeriodosAgrupado` | 200 | Grouped periods |
| GET | `/api/v1/reservas` | 200 (1.5MB) | **ALL reservations!** |
| POST | `/api/v1/reservas` | - | Create reservation |
| GET | `/api/v1/reservas/{codReserva}` | - | Get reservation |
| PUT | `/api/v1/reservas/{codReserva}/atualizar` | - | Update reservation |
| POST | `/api/v1/reservas/{codReserva}/cancelar` | - | Cancel reservation |
| POST | `/api/v1/reservas/{codReserva}/confirmar` | - | Confirm reservation |
| GET | `/api/v1/reservas/{codArea}/visaoMorador` | 500 | Resident view |

#### Area Configuration (Admin-level)
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/areaConfiguracao/{cond}` | 200 | **Full config, no auth check!** |
| PUT | `/api/v1/areaConfiguracao/{codArea}` | - | Update area config |
| POST | `/api/v1/areaConfiguracao` | - | Create area |
| POST | `/api/v1/areaConfiguracao/{codArea}/bloqueio` | - | Create block |
| PUT | `/api/v1/areaConfiguracao/{codArea}/bloqueio/{codBloqueio}` | - | Update block |
| GET | `/api/v1/areaConfiguracao/{codArea}/horario` | - | Area schedule |
| POST | `/api/v1/areaConfiguracao/{codArea}/horario` | - | Create schedule |
| PUT | `/api/v1/areaConfiguracao/{codArea}/horario/{codHorario}` | - | Update schedule |
| GET | `/api/v1/areaConfiguracao/reservaBloqueia` | - | Block reservation config |

#### Portal Integration (Internal!)
| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/areas/integracaoPortal/agenda` | Mirror portal agenda inserts |
| PUT | `/api/v1/areas/integracaoPortal/agenda` | Mirror portal agenda updates |
| POST | `/api/v1/areas/integracaoPortal/agendabloqueio` | Mirror block inserts |
| PUT | `/api/v1/areas/integracaoPortal/agendabloqueio` | Mirror block updates |
| POST | `/api/v1/areas/integracaoPortal/agendahoras` | Mirror hours inserts |
| PUT | `/api/v1/areas/integracaoPortal/agendahoras` | Mirror hours updates |
| POST | `/api/v1/reservas/integracaoPortal/parametroReserva` | Mirror reservation params |
| PUT | `/api/v1/reservas/integracaoPortal/parametroReserva` | Mirror reservation updates |

#### Financial
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/financeiro/recibosEmAberto` | 400 | Open receipts (needs cond+unit) |
| GET | `/api/v1/financeiro/{cond}/prestacaocontas/periodos` | 200 | **Accounting periods, no auth!** |
| GET | `/api/v1/financeiro/{cond}/prestacaocontas` | 400 | Needs period param |
| GET | `/api/v1/financeiro/{cond}/prestacaocontas/pastafacil` | - | PDF URL |
| GET | `/api/v1/financeiro/{cond}/aplicacoes` | 204 | Financial applications |
| GET | `/api/v1/financeiro/{cond}/extratoBoleto/{unid}` | - | Invoice extract |
| POST | `/api/v1/boleto/avulso` | - | Generate invoice |
| GET | `/api/v1/boleto/avulso/{codRecibo}/cancelar` | - | Cancel invoice |
| GET | `/api/v1/boleto/{codRecibo}/cancelarBoletoAvulso` | - | Cancel invoice (alt) |
| GET | `/api/integracao/v1/financeiro/recibosEmAberto` | 400 | Integration endpoint |

#### Access Control / Portaria
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/liberacaoAcesso` | 400 | Needs unit |
| GET | `/api/v1/liberacaoAcesso/{cond}/ativas` | 200 | **Active accesses - names, CPFs, photos!** |
| GET | `/api/v1/liberacaoAcesso/log` | 400 | Access logs |
| POST | `/api/v1/liberacaoAcesso` | - | Create access auth |
| PUT | `/api/v1/liberacaoAcesso/status` | - | Update status |
| PUT | `/api/v1/liberacaoAcesso/{codLib}/deletar` | - | Delete access |
| POST | `/api/v1/portaria/liberacaoAcesso` | - | Portal access registration |
| GET | `/api/v1/portaria/liberacaoAcesso/{cond}` | 204 | Portal access list |
| PUT | `/api/v1/portaria/liberacaoAcesso/{id}/saida` | - | Register exit |
| GET | `/api/v1/portaria/{cond}/veiculo` | 200 | **Vehicles - plates, names, units!** |
| GET | `/api/v1/portaria/entregas` | 400 | Delivery notices |
| POST | `/api/v1/portaria/entregas` | - | Create delivery notice |
| POST | `/api/v1/portaria/entregas/{codAviso}/confirmacao` | - | Confirm delivery |
| GET | `/api/v1/portaria/tiposEntrega` | 200 | Delivery types |

#### Construction/Obras
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/obras` | 400 | Construction list |
| POST | `/api/v1/obras` | - | Register construction |
| GET | `/api/v1/obras/{codObra}` | - | Construction details |
| PUT | `/api/v1/obras/{codObra}` | - | Update construction |

#### Documents & CND
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/documento` | 400 | Documents (needs unit) |
| GET | `/api/v1/documento/tipoDisponivel` | 400 | Available doc types |
| GET | `/api/v1/cnd/{cond}/situacao/{unid}` | 400 | CND status (auth checked) |
| POST | `/api/v1/cnd/{cond}/gerarCnd/{unid}` | - | Generate CND |
| GET | `/api/v1/cnd/autenticidade/{token}` | - | CND authenticity check |

#### Delivery Tokens
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/tokenEntrega/{cond}/token/{unid}` | 400 | Get delivery token (auth checked) |
| PUT | `/api/v1/tokenEntrega/{cond}/novoToken/{unid}` | - | Generate new delivery token |

#### App Config
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/aplicativo/{cond}` | 200 | **App menus/features, no auth!** |
| PUT | `/api/v1/aplicativo/{cond}` | - | Update menu status |
| GET | `/api/v1/aplicativo/{cond}/logacessofuncionalidade` | - | Feature access log |

#### Calendar
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/calendario/feriados` | 200 | Holiday list |
| GET | `/api/v1/calendario/datasMagna` | 200 | Special dates |

#### Entity (broken)
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/entidade` | 500 | MediatR handler missing - stack trace leak |

#### Healthcheck
| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/api/v1/healthcheck` | 200 | App name, SQL datetime |

---

## Vulnerability Summary

### CRITICAL
1. **Swagger spec exposed** - Full API documentation accessible to any authenticated user
2. **IDOR on liberacaoAcesso/{cond}/ativas** - Leaks full names, CPFs, RGs, photos of ALL residents in ANY condominio
3. **IDOR on portaria/{cond}/veiculo** - Leaks vehicle plates, owner names, unit numbers for ANY condominio
4. **Mass data dump on /api/v1/reservas** - Returns 1.5MB of ALL reservations across ALL condominios
5. **Mass data dump on /api/v1/areas** - Returns 1.2MB of ALL areas across ALL condominios

### HIGH
6. **IDOR on areaConfiguracao/{cond}** - Admin-level area configuration for any condominio
7. **IDOR on financeiro/{cond}/prestacaocontas/periodos** - Financial periods for any condominio
8. **Portal integration endpoints exposed** - Internal sync endpoints callable by regular users
9. **Stack trace leaks** - /api/v1/entidade and other 500 errors return full .NET stack traces

### MEDIUM
10. **IDOR on aplicativo/{cond}** - Feature flags and menu config for any condominio
11. **Employee login management endpoints** - criarLogin/resetarLogin exposed
12. **Healthcheck leaks** - Server datetime, app version, SQL connectivity info
13. **Error message information disclosure** - Detailed MediatR/C# class names in error responses

### LOW
14. **LGPD terms accessible** - Terms list and signed terms enumerable
15. **Calendar/holidays public** - Not sensitive but no auth check on data scope
