"""Backend do site: serve os arquivos estáticos, a API de login e o portal.

Um único processo cuida de tudo — a lead page e o login continuam sendo
entregues como arquivos estáticos, exatamente como antes. As páginas do
portal (pages/portal-*.html) exigem sessão válida e são renderizadas como
templates Jinja2, preenchidas com dados buscados ao vivo na API da
Acessórias — o token nunca chega ao navegador, só o HTML já pronto.

As buscas na Acessórias rodam em paralelo (asyncio.gather) dentro de cada
página, não uma atrás da outra — o tempo de carregar o Início é o da
chamada mais lenta das quatro, não a soma das quatro.
"""
import asyncio
import calendar as modulo_calendario
import os
import secrets
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()  # precisa rodar antes de importar acessorias (lê env em cada chamada, mas o token já deve estar carregado)

import acessorias  # noqa: E402
import email_envio  # noqa: E402
from auth import (  # noqa: E402
    TAMANHO_MAXIMO_EMAIL,
    TAMANHO_MINIMO_SENHA,
    consumir_token_redefinicao,
    email_da_conta,
    emitir_token_redefinicao,
    gerar_hash,
    limpar_falhas_login,
    login_bloqueado,
    redefinicao_bloqueada,
    registrar_falha_login,
    registrar_pedido_redefinicao,
    token_redefinicao_valido,
    verificar_senha,
)
from database import inicializar_schema, obter_conexao  # noqa: E402

RAIZ = Path(__file__).parent.parent
PAGINAS = RAIZ / "pages"

# Cookie de sessão só como "Secure" (HTTPS) quando ENV=production está
# definido — em desenvolvimento local (http://) o navegador descartaria
# um cookie Secure e o login pareceria não "colar".
HTTPS_ONLY = os.environ.get("ENV") == "production"

SECRET_SESSAO = os.environ.get("SESSION_SECRET")
if not SECRET_SESSAO:
    if HTTPS_ONLY:
        # Nunca subir em produção com uma chave adivinhável: sem ela,
        # qualquer um que já viu este código forjaria um cookie de sessão
        # válido pra qualquer cliente ou funcionário.
        raise RuntimeError(
            "SESSION_SECRET não definido no ambiente — obrigatório em "
            "produção (ver backend/.env.example). O servidor não sobe sem ele."
        )
    print(
        "AVISO: SESSION_SECRET não definido no ambiente — gerando uma chave "
        "aleatória só para esta execução (sessões caem a cada restart). "
        "Defina a variável antes de publicar (ver backend/.env.example)."
    )
    SECRET_SESSAO = secrets.token_hex(32)

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_SESSAO,
    session_cookie="facchini_sessao",
    max_age=60 * 60 * 8,  # 8 horas
    https_only=HTTPS_ONLY,
    same_site="lax",
)

CABECALHOS_SEGURANCA = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}
if HTTPS_ONLY:
    CABECALHOS_SEGURANCA["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


@app.middleware("http")
async def cabecalhos_seguranca(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers.update(CABECALHOS_SEGURANCA)
    return resposta


templates = Jinja2Templates(directory=str(PAGINAS))


@app.on_event("startup")
def ao_iniciar() -> None:
    inicializar_schema()


def _registrar_acesso(email: str, nome: str, tipo: str) -> None:
    """Item 11 da referência do usuário sobre o Acessórias — histórico de
    acessos não existe na API deles, é 100% nosso. Chamado só depois de
    login bem-sucedido (não registra tentativa falha, isso já é outro
    mecanismo — auth.registrar_falha_login)."""
    with obter_conexao() as conexao:
        conexao.execute(
            "INSERT INTO historico_acessos (email, nome, tipo) VALUES (?, ?, ?)",
            (email, nome, tipo),
        )


@app.post("/api/login")
async def login(request: Request):
    corpo = await request.json()
    email = str(corpo.get("usuario", "")).strip().lower()
    senha = str(corpo.get("senha", ""))

    if not email or not senha or len(email) > TAMANHO_MAXIMO_EMAIL:
        return JSONResponse({"erro": "Informe usuário e senha."}, status_code=400)

    ip = _ip_cliente(request)
    if login_bloqueado(email, ip):
        return JSONResponse(
            {"erro": "Muitas tentativas. Aguarde alguns minutos e tente de novo."},
            status_code=429,
        )

    with obter_conexao() as conexao:
        usuario = conexao.execute(
            "SELECT id, nome, senha_hash, deve_trocar_senha FROM usuarios WHERE email = ?", (email,)
        ).fetchone()

        if not verificar_senha(senha, usuario["senha_hash"] if usuario else None):
            registrar_falha_login(email, ip)
            return JSONResponse({"erro": "Usuário ou senha incorretos."}, status_code=401)

        empresas = [
            linha["identificador_acessorias"]
            for linha in conexao.execute(
                "SELECT identificador_acessorias FROM usuario_empresas WHERE usuario_id = ? ORDER BY id",
                (usuario["id"],),
            )
        ]

    limpar_falhas_login(email)
    _registrar_acesso(email, usuario["nome"], "cliente")
    deve_trocar_senha = bool(usuario["deve_trocar_senha"])
    request.session["usuario_id"] = usuario["id"]
    request.session["nome"] = usuario["nome"]
    request.session["empresas"] = empresas
    request.session["deve_trocar_senha"] = deve_trocar_senha

    # Uma empresa só: entra direto nela, sem tela extra. Mais de uma: cai
    # numa tela de escolha primeiro (mesmo padrão da própria Acessórias) —
    # empresa_ativa fica vazia até o cliente escolher.
    if len(empresas) == 1:
        request.session["empresa_ativa"] = empresas[0]
        destino = "portal-inicio.html"
    else:
        request.session["empresa_ativa"] = None
        destino = "selecionar-empresa.html" if empresas else "portal-inicio.html"

    return {"ok": True, "destino": destino}


@app.post("/api/trocar-senha")
async def trocar_senha(request: Request):
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    erro = await _trocar_senha_da_conta(
        request, "cliente", request.session["usuario_id"], bool(request.session.get("deve_trocar_senha"))
    )
    if erro:
        return erro

    # Sem redirecionamento: o cliente continua na mesma página do portal,
    # só o aviso flutuante some. Trocou aqui, não aparece mais em nenhum
    # login futuro — mas se só fechar sem trocar, volta a aparecer na
    # próxima vez que entrar (deve_trocar_senha continua 1 no banco).
    request.session["deve_trocar_senha"] = False
    return {"ok": True}


@app.post("/api/selecionar-empresa")
async def selecionar_empresa(request: Request):
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    corpo = await request.json()
    identificador = str(corpo.get("identificador", ""))

    if identificador not in request.session.get("empresas", []):
        return JSONResponse({"erro": "Empresa inválida."}, status_code=400)

    request.session["empresa_ativa"] = identificador
    return {"ok": True, "destino": "portal-inicio.html"}


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/pages/login.html", status_code=303)


# --- Painel da equipe (Central de Atendimento) ---------------------------
# Login separado do cliente por decisão do usuário: são níveis de acesso
# bem diferentes (funcionário vê solicitações de toda a Facchini, cliente
# só a própria empresa), então usam chaves de sessão próprias
# (funcionario_id, não usuario_id) mesmo dividindo o mesmo cookie —
# nenhuma rota do cliente aceita sessão de funcionário nem vice-versa.

@app.post("/api/equipe/login")
async def equipe_login(request: Request):
    corpo = await request.json()
    email = str(corpo.get("usuario", "")).strip().lower()
    senha = str(corpo.get("senha", ""))

    if not email or not senha or len(email) > TAMANHO_MAXIMO_EMAIL:
        return JSONResponse({"erro": "Informe usuário e senha."}, status_code=400)

    ip = _ip_cliente(request)
    if login_bloqueado(email, ip):
        return JSONResponse(
            {"erro": "Muitas tentativas. Aguarde alguns minutos e tente de novo."},
            status_code=429,
        )

    with obter_conexao() as conexao:
        funcionario = conexao.execute(
            "SELECT id, nome, senha_hash, deve_trocar_senha FROM funcionarios WHERE email = ?", (email,)
        ).fetchone()

    if not verificar_senha(senha, funcionario["senha_hash"] if funcionario else None):
        registrar_falha_login(email, ip)
        return JSONResponse({"erro": "Usuário ou senha incorretos."}, status_code=401)

    limpar_falhas_login(email)
    _registrar_acesso(email, funcionario["nome"], "equipe")
    request.session["funcionario_id"] = funcionario["id"]
    request.session["funcionario_nome"] = funcionario["nome"]
    request.session["funcionario_deve_trocar_senha"] = bool(funcionario["deve_trocar_senha"])
    return {"ok": True, "destino": "equipe-atendimento.html"}


@app.post("/api/equipe/trocar-senha")
async def equipe_trocar_senha(request: Request):
    if not _tem_sessao_equipe(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    erro = await _trocar_senha_da_conta(
        request,
        "equipe",
        request.session["funcionario_id"],
        bool(request.session.get("funcionario_deve_trocar_senha")),
    )
    if erro:
        return erro

    request.session["funcionario_deve_trocar_senha"] = False
    return {"ok": True}


@app.get("/equipe/logout")
async def equipe_logout(request: Request):
    request.session.pop("funcionario_id", None)
    request.session.pop("funcionario_nome", None)
    request.session.pop("funcionario_deve_trocar_senha", None)
    return RedirectResponse("/pages/equipe-login.html", status_code=303)


def _tem_sessao_equipe(request: Request) -> bool:
    return bool(request.session.get("funcionario_id"))


def _guarda_equipe(request: Request) -> RedirectResponse | None:
    if not _tem_sessao_equipe(request):
        return RedirectResponse("/pages/equipe-login.html", status_code=303)
    return None


def _tem_sessao(request: Request) -> bool:
    return bool(request.session.get("usuario_id"))


def _guarda_portal(request: Request) -> RedirectResponse | None:
    """Toda página do portal passa por aqui antes de montar qualquer dado.
    Protege contra acesso direto por URL: se o login tem mais de uma
    empresa e nenhuma foi escolhida ainda nesta sessão, força a tela de
    seleção em vez de cair numa página sem saber qual empresa mostrar."""
    if not _tem_sessao(request):
        return RedirectResponse("/pages/login.html", status_code=303)
    if not request.session.get("empresa_ativa") and len(request.session.get("empresas", [])) > 1:
        return RedirectResponse("/pages/selecionar-empresa.html", status_code=303)
    return None


MESES_PT = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def _data(texto: str, formato: str = "%Y-%m-%d") -> date | None:
    try:
        return datetime.strptime(texto, formato).date()
    except (ValueError, TypeError):
        return None


def _formatar_vencimentos(bruto: list[dict]) -> list[dict]:
    hoje = date.today()
    vencimentos = []
    for item in bruto:
        prazo = _data(item.get("EntDtPrazo", ""))
        if not prazo:
            continue
        dias_restantes = (prazo - hoje).days
        competencia = _data(item.get("EntCompetencia", ""))
        vencimentos.append({
            "dia": f"{prazo.day:02d}",
            "mes": MESES_PT[prazo.month - 1],
            "nome": item.get("Nome", ""),
            "competencia": f"Competência {competencia.month:02d}/{competencia.year}" if competencia else "",
            "dias_restantes": max(dias_restantes, 0),
            "breve": dias_restantes <= 7,
        })
    vencimentos.sort(key=lambda v: v["dias_restantes"])
    return vencimentos


def _formatar_documentos(bruto: list[dict]) -> list[dict]:
    bruto_ordenado = sorted(bruto, key=lambda item: item.get("EntDtEntrega", ""), reverse=True)
    documentos = []
    for item in bruto_ordenado:
        entrega = _data(item.get("EntDtEntrega", ""))
        competencia = _data(item.get("EntCompetencia", ""))
        anexos = item.get("Anexos") or []
        documentos.append({
            "nome": item.get("Nome", ""),
            "referencia": f"{competencia.month:02d}/{competencia.year}" if competencia else "Atualizado",
            "tipo": item.get("Config", {}).get("DptoNome", ""),
            "data_envio": entrega.strftime("%d/%m/%Y") if entrega else "",
            "anexo_url": anexos[0] if anexos else None,
        })
    return documentos


def _classe_status_obrigacao(status: str) -> str:
    if status.startswith("Atrasada"):
        return "atrasada"
    # "Ent. antecipada", "Ent. no prazo" (entregue) e "Dispensada" (não
    # precisa de ação) são todo "resolvido" pro cliente — só "Pendente"
    # continua contando como em aberto.
    if status.startswith("Ent.") or status.startswith("Dispensada"):
        return "concluido"
    return "andamento"


def _formatar_obrigacoes(bruto: list[dict]) -> list[dict]:
    bruto_ordenado = sorted(bruto, key=lambda item: item.get("EntDtPrazo", ""))
    obrigacoes = []
    for item in bruto_ordenado:
        prazo = _data(item.get("EntDtPrazo", ""))
        competencia = _data(item.get("EntCompetencia", ""))
        status = item.get("Status", "")
        obrigacoes.append({
            "nome": item.get("Nome", ""),
            "competencia": f"{competencia.month:02d}/{competencia.year}" if competencia else "",
            "prazo": prazo.strftime("%d/%m/%Y") if prazo else "",
            "tipo": item.get("Config", {}).get("DptoNome", ""),
            "status": status,
            "classe_status": _classe_status_obrigacao(status),
        })
    return obrigacoes


_STATUS_PARA_CLASSE = {
    "Finalizada": "concluido",
    "Cliente": "respondido",
}


def _formatar_atendimentos(bruto: list[dict]) -> list[dict]:
    atendimentos = []
    for item in bruto:
        abertura = item.get("SolDHAbertura", "")
        status = item.get("SolStatus", "")
        atendimentos.append({
            "id": item.get("SolID", ""),
            "assunto": item.get("SolAssunto", ""),
            "data": abertura.split(" ")[0] if abertura else "",
            "status": status,
            "classe_status": _STATUS_PARA_CLASSE.get(status, "andamento"),
        })
    return atendimentos


def _formatar_solicitacoes(bruto: list[dict]) -> list[dict]:
    # SolID maior = criada depois — mais simples e mais confiável que
    # tentar ordenar a data "DD/MM/AAAA HH:MM:SS" como texto.
    bruto_ordenado = sorted(bruto, key=lambda item: int(item.get("SolID") or 0), reverse=True)
    solicitacoes = []
    for item in bruto_ordenado:
        abertura = item.get("SolDHAbertura", "")
        status = item.get("SolStatus", "")
        solicitacoes.append({
            "id": item.get("SolID", ""),
            "assunto": item.get("SolAssunto", ""),
            "data": abertura.split(" ")[0] if abertura else "",
            "prioridade": item.get("SolPrioridade", ""),
            "status": status,
            "classe_status": _STATUS_PARA_CLASSE.get(status, "andamento"),
        })
    return solicitacoes


_STATUS_BOLETO_LABEL = {"P": "Pendente", "Q": "Quitado", "C": "Cancelado"}
_STATUS_BOLETO_CLASSE = {"P": "andamento", "Q": "concluido", "C": "atrasada"}


def _boletos_pagos_localmente(identificador: str) -> set[tuple[str, str, str]]:
    with obter_conexao() as conexao:
        linhas = conexao.execute(
            "SELECT vencimento, valor, competencia FROM boletos_pagos_local WHERE identificador_acessorias = ?",
            (identificador,),
        ).fetchall()
    return {(linha["vencimento"], linha["valor"], linha["competencia"]) for linha in linhas}


def _formatar_boletos(bruto: list[dict], pagos_localmente: set[tuple[str, str, str]] | None = None) -> list[dict]:
    pagos_localmente = pagos_localmente or set()

    def chave_vencimento(item: dict) -> date:
        return _data(item.get("Vencimento", ""), "%d/%m/%Y") or date.min

    bruto_ordenado = sorted(bruto, key=chave_vencimento, reverse=True)
    boletos = []
    for item in bruto_ordenado:
        status = item.get("Status", "")
        vencimento = item.get("Vencimento", "")
        valor = item.get("Valor", "")
        competencia = item.get("Competencia", "")
        boletos.append({
            "competencia": competencia,
            "vencimento": vencimento,
            "valor": valor,
            "status": _STATUS_BOLETO_LABEL.get(status, status),
            "classe_status": _STATUS_BOLETO_CLASSE.get(status, "andamento"),
            "nota_url": item.get("PDFNota") or None,
            # Só local — a Acessórias não expõe escrita nisso (ver
            # boletos_pagos_local em database.py). Não sobrepõe o status
            # real vindo de lá, é uma marcação à parte.
            "pago_local": (vencimento, valor, competencia) in pagos_localmente,
        })
    return boletos


_PRIORIDADE_ORDEM = {"Muito alta": 0, "Alta": 1, "Média": 2, "Baixa": 3}
# Reaproveita as cores já existentes de etiqueta-status (vermelho/azul/verde)
# pra prioridade também, em vez de criar uma paleta nova só pra isso.
_PRIORIDADE_PARA_CLASSE = {"Muito alta": "atrasada", "Alta": "atrasada", "Média": "andamento", "Baixa": "concluido"}


def _formatar_atendimento_equipe(bruto: list[dict]) -> list[dict]:
    """Fila da equipe: mais urgente (prioridade) e mais antiga (esperando
    há mais tempo) primeiro — diferente da lista do cliente
    (_formatar_solicitacoes), que ordena só por mais recente."""
    hoje = datetime.now()

    def chave_ordenacao(item: dict) -> tuple:
        prioridade = _PRIORIDADE_ORDEM.get(item.get("SolPrioridade", ""), 99)
        abertura = _data(item.get("SolDHAbertura", "").split(" ")[0], "%d/%m/%Y") or date.max
        return (prioridade, abertura)

    bruto_ordenado = sorted(bruto, key=chave_ordenacao)
    atendimentos = []
    for item in bruto_ordenado:
        abertura_texto = item.get("SolDHAbertura", "")
        abertura_data = _data(abertura_texto.split(" ")[0], "%d/%m/%Y") if abertura_texto else None
        dias_aberto = (hoje.date() - abertura_data).days if abertura_data else None
        status = item.get("SolStatus", "")
        atendimentos.append({
            "id": item.get("SolID", ""),
            "assunto": item.get("SolAssunto", ""),
            "empresa": item.get("EmpNome") or item.get("EmpCNPJ", ""),
            "data": abertura_data.strftime("%d/%m/%Y") if abertura_data else "",
            "dias_aberto": dias_aberto,
            "prioridade": item.get("SolPrioridade", ""),
            "classe_prioridade": _PRIORIDADE_PARA_CLASSE.get(item.get("SolPrioridade", ""), "andamento"),
            "status": status,
            "classe_status": _STATUS_PARA_CLASSE.get(status, "andamento"),
        })
    return atendimentos


async def _montar_contexto_atendimento(request: Request) -> dict:
    solicitacoes_brutas = await acessorias.listar_todas_solicitacoes()
    return {
        "nome_usuario": request.session.get("funcionario_nome", "equipe"),
        "deve_trocar_senha": bool(request.session.get("funcionario_deve_trocar_senha")),
        "atendimentos": _formatar_atendimento_equipe(solicitacoes_brutas),
    }


def _identificador_ativo(request: Request) -> str | None:
    return request.session.get("empresa_ativa")


def _cabecalho(request: Request, empresa_dados: dict | None, identificador: str | None) -> dict:
    fantasia = (empresa_dados or {}).get("Fantasia") or (empresa_dados or {}).get("Razao") or "Cliente"
    cnpj = (empresa_dados or {}).get("Identificador") or identificador or "—"
    return {
        "nome_usuario": request.session.get("nome", "cliente"),
        "empresa": {
            "fantasia": fantasia,
            "cnpj": cnpj,
            # fantasia nunca é vazio (o "or 'Cliente'" acima garante isso).
            "inicial": fantasia[:1].upper(),
        },
        # Controla o aviso flutuante de troca de senha (portal-shell.css /
        # portal.js) — presente em toda página do portal.
        "deve_trocar_senha": bool(request.session.get("deve_trocar_senha")),
        # Só mostra "Trocar empresa" no menu do usuário quando faz sentido.
        "multiplas_empresas": len(request.session.get("empresas", [])) > 1,
    }


async def _montar_contexto_inicio(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto.update({"vencimentos": [], "documentos": [], "atendimentos": []})
        return contexto

    # As quatro chamadas são independentes entre si — rodar em paralelo em
    # vez de uma depois da outra é a diferença entre a página demorar o
    # tempo da mais lenta ou a soma de todas.
    empresa_dados, vencimentos_brutos, documentos_brutos, atendimentos_brutos = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_vencimentos(identificador),
        acessorias.listar_documentos_entregues(identificador),
        acessorias.listar_solicitacoes_da_empresa(identificador, limite=3),
    )

    contexto = _cabecalho(request, empresa_dados, identificador)
    contexto.update({
        "vencimentos": _formatar_vencimentos(vencimentos_brutos),
        "documentos": _formatar_documentos(documentos_brutos)[:10],
        "atendimentos": _formatar_atendimentos(atendimentos_brutos),
    })
    return contexto


async def _montar_contexto_documentos(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto["documentos"] = []
        return contexto

    empresa_dados, documentos_brutos = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_documentos_entregues(identificador, dias_atras=365),
    )
    contexto = _cabecalho(request, empresa_dados, identificador)
    contexto["documentos"] = _formatar_documentos(documentos_brutos)
    return contexto


async def _montar_contexto_obrigacoes(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto["obrigacoes"] = []
        return contexto

    empresa_dados, obrigacoes_brutas = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_obrigacoes(identificador),
    )
    contexto = _cabecalho(request, empresa_dados, identificador)
    contexto["obrigacoes"] = _formatar_obrigacoes(obrigacoes_brutas)
    return contexto


def _montar_semanas_calendario(obrigacoes: list[dict], ano: int, mes: int) -> list[list[dict | None]]:
    """Reaproveita a mesma lista já formatada por _formatar_obrigacoes (não
    busca nada novo na Acessórias) e organiza em semanas domingo-sábado,
    cada dia com as obrigações que vencem nele. Dias fora do mês (início/
    fim da grade) viram None — o template só desenha a célula vazia."""
    por_dia: dict[int, list[dict]] = {}
    for item in obrigacoes:
        prazo = _data(item["prazo"], "%d/%m/%Y")
        if prazo and prazo.year == ano and prazo.month == mes:
            por_dia.setdefault(prazo.day, []).append(item)

    calendario = modulo_calendario.Calendar(firstweekday=6)  # domingo primeiro
    semanas = []
    for semana in calendario.monthdayscalendar(ano, mes):
        linha = [{"dia": dia, "itens": por_dia.get(dia, [])} if dia else None for dia in semana]
        semanas.append(linha)
    return semanas


async def _montar_contexto_calendario(request: Request, ano: int, mes: int) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto.update({"semanas": [], "mes_nome": "", "mes_anterior": {}, "mes_seguinte": {}})
        return contexto

    # Janela ampla (±120 dias) o bastante pra cobrir qualquer mês vizinho
    # sem precisar buscar de novo na Acessórias a cada troca de mês — o
    # cache de _get já resolve isso, então navegar entre meses próximos
    # não paga chamada de rede extra.
    empresa_dados, obrigacoes_brutas = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_obrigacoes(identificador, dias_atras=120, dias_a_frente=120),
    )
    contexto = _cabecalho(request, empresa_dados, identificador)
    obrigacoes = _formatar_obrigacoes(obrigacoes_brutas)
    contexto["semanas"] = _montar_semanas_calendario(obrigacoes, ano, mes)
    contexto["mes_nome"] = f"{MESES_PT[mes - 1]} {ano}"
    contexto["mes_anterior"] = {"ano": ano - 1, "mes": 12} if mes == 1 else {"ano": ano, "mes": mes - 1}
    contexto["mes_seguinte"] = {"ano": ano + 1, "mes": 1} if mes == 12 else {"ano": ano, "mes": mes + 1}
    return contexto


async def _montar_contexto_solicitacoes(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto.update({"solicitacoes": [], "departamentos": []})
        return contexto

    empresa_dados, solicitacoes_brutas, departamentos = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_solicitacoes_da_empresa(identificador, limite=20, max_paginas=5),
        acessorias.listar_departamentos(identificador),
    )
    contexto = _cabecalho(request, empresa_dados, identificador)
    contexto["solicitacoes"] = _formatar_solicitacoes(solicitacoes_brutas)
    contexto["departamentos"] = departamentos
    return contexto


async def _montar_contexto_financeiro(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto["boletos"] = []
        return contexto

    empresa_dados, boletos_brutos = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_boletos(identificador),
    )
    contexto = _cabecalho(request, empresa_dados, identificador)
    contexto["boletos"] = _formatar_boletos(boletos_brutos, _boletos_pagos_localmente(identificador))
    return contexto


def _data_cadastro(texto: str) -> str:
    # A Acessórias usa "0000-00-00" como "sem data definida" em vez de
    # omitir o campo — mostrar isso cru pro cliente ficaria estranho.
    data = _data(texto)
    return data.strftime("%d/%m/%Y") if data else "—"


def _historico_acessos(request: Request, limite: int = 10) -> list[dict]:
    """Item 11 da referência do usuário sobre o Acessórias — não vem de
    lá, é histórico local (tabela historico_acessos, gravada em
    _registrar_acesso a cada login bem-sucedido)."""
    usuario_id = request.session.get("usuario_id")
    if not usuario_id:
        return []
    with obter_conexao() as conexao:
        usuario = conexao.execute("SELECT email FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if not usuario:
            return []
        linhas = conexao.execute(
            "SELECT criado_em FROM historico_acessos WHERE email = ? AND tipo = 'cliente' ORDER BY id DESC LIMIT ?",
            (usuario["email"], limite),
        ).fetchall()
    acessos = []
    for linha in linhas:
        momento = datetime.strptime(linha["criado_em"], "%Y-%m-%d %H:%M:%S")
        acessos.append({"data_hora": momento.strftime("%d/%m/%Y às %H:%M")})
    return acessos


async def _montar_contexto_perfil(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto.update({"perfil": None, "contatos": [], "inscricoes": [], "acessos": []})
        return contexto

    dados = await acessorias.buscar_perfil_empresa(identificador)
    contexto = _cabecalho(request, dados, identificador)
    contexto["acessos"] = _historico_acessos(request)
    if not dados:
        # Falha real da Acessórias (não "campo vazio") — o template mostra
        # o aviso de "não conseguimos carregar" em vez de uma ficha em
        # branco, que pareceria um bug nosso.
        contexto.update({"perfil": None, "contatos": [], "inscricoes": []})
        return contexto

    contexto["perfil"] = {
        "razao": dados.get("Razao", ""),
        "fantasia": dados.get("Fantasia", ""),
        "cnpj": dados.get("Identificador", identificador),
        "status": dados.get("Status", ""),
        "regime": dados.get("Regime", "") or "—",
        "telefone": dados.get("Telefone", "") or "—",
        "uf": dados.get("UF", "") or "—",
        "cliente_desde": _data_cadastro(dados.get("ClienteDesde", "")),
    }
    contexto["contatos"] = dados.get("ContatosNaEmpresa", [])
    contexto["inscricoes"] = dados.get("InscricoesEstaduais", [])
    return contexto


# Páginas do portal exigem sessão válida — cada página nova do portal
# ganha uma rota igual a esta, seguindo o mesmo padrão: checar
# _guarda_portal antes de tudo, e só então montar dados.
@app.get("/pages/portal-inicio.html")
async def pagina_portal_inicio(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_inicio(request)
    return templates.TemplateResponse(request, "portal-inicio.html", contexto)


@app.get("/pages/portal-documentos.html")
async def pagina_portal_documentos(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_documentos(request)
    return templates.TemplateResponse(request, "portal-documentos.html", contexto)


@app.get("/pages/portal-obrigacoes.html")
async def pagina_portal_obrigacoes(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_obrigacoes(request)
    return templates.TemplateResponse(request, "portal-obrigacoes.html", contexto)


@app.get("/pages/portal-calendario.html")
async def pagina_portal_calendario(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    hoje = date.today()
    try:
        ano = int(request.query_params.get("ano", hoje.year))
        mes = int(request.query_params.get("mes", hoje.month))
        if not 1 <= mes <= 12:
            raise ValueError
    except ValueError:
        ano, mes = hoje.year, hoje.month
    contexto = await _montar_contexto_calendario(request, ano, mes)
    return templates.TemplateResponse(request, "portal-calendario.html", contexto)


@app.get("/pages/portal-solicitacoes.html")
async def pagina_portal_solicitacoes(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_solicitacoes(request)
    return templates.TemplateResponse(request, "portal-solicitacoes.html", contexto)


@app.get("/pages/portal-financeiro.html")
async def pagina_portal_financeiro(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_financeiro(request)
    return templates.TemplateResponse(request, "portal-financeiro.html", contexto)


@app.get("/pages/portal-perfil.html")
async def pagina_portal_perfil(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_perfil(request)
    return templates.TemplateResponse(request, "portal-perfil.html", contexto)


@app.get("/pages/equipe-atendimento.html")
async def pagina_equipe_atendimento(request: Request):
    guarda = _guarda_equipe(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_atendimento(request)
    return templates.TemplateResponse(request, "equipe-atendimento.html", contexto)


TAMANHO_MAXIMO_ANEXO = 30 * 1024 * 1024  # 30MB — mesmo limite da Acessórias


@app.post("/api/solicitacoes")
async def api_criar_solicitacao(
    request: Request,
    assunto: str = Form(...),
    departamento: str = Form(...),
    prioridade: str = Form(...),
    descricao: str = Form(...),
    arquivo: UploadFile | None = File(None),
):
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    identificador = _identificador_ativo(request)
    if not identificador:
        return JSONResponse({"erro": "Nenhuma empresa selecionada."}, status_code=400)

    assunto = assunto.strip()
    descricao = descricao.strip()
    if not assunto or not descricao:
        return JSONResponse({"erro": "Preencha assunto e descrição."}, status_code=400)

    arquivo_bytes = None
    arquivo_nome = None
    if arquivo and arquivo.filename:
        arquivo_bytes = await arquivo.read()
        if len(arquivo_bytes) > TAMANHO_MAXIMO_ANEXO:
            return JSONResponse({"erro": "O anexo passa de 30MB — envie um arquivo menor."}, status_code=400)
        arquivo_nome = arquivo.filename

    resultado = await acessorias.criar_solicitacao(
        identificador, assunto, departamento, prioridade, descricao,
        arquivo_nome=arquivo_nome, arquivo_bytes=arquivo_bytes,
    )
    if "Erro" in resultado:
        return JSONResponse({"erro": resultado["Erro"]}, status_code=400)

    return {"ok": True}


@app.post("/api/boletos/alternar-pago")
async def api_alternar_pago(request: Request):
    """"Marcar como pago" (item 6) — só local, a Acessórias não tem
    escrita pra isso. Usa a empresa ativa da sessão, nunca uma vinda do
    corpo da requisição, pra um cliente nunca conseguir marcar boleto de
    empresa que não é a dele."""
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    identificador = _identificador_ativo(request)
    if not identificador:
        return JSONResponse({"erro": "Nenhuma empresa selecionada."}, status_code=400)

    corpo = await request.json()
    vencimento = str(corpo.get("vencimento", "")).strip()
    valor = str(corpo.get("valor", "")).strip()
    competencia = str(corpo.get("competencia", "")).strip()
    if not vencimento or not valor or not competencia:
        return JSONResponse({"erro": "Dados do boleto inválidos."}, status_code=400)

    with obter_conexao() as conexao:
        existente = conexao.execute(
            """SELECT id FROM boletos_pagos_local
               WHERE identificador_acessorias = ? AND vencimento = ? AND valor = ? AND competencia = ?""",
            (identificador, vencimento, valor, competencia),
        ).fetchone()
        if existente:
            conexao.execute("DELETE FROM boletos_pagos_local WHERE id = ?", (existente["id"],))
            pago = False
        else:
            conexao.execute(
                """INSERT INTO boletos_pagos_local (identificador_acessorias, vencimento, valor, competencia)
                   VALUES (?, ?, ?, ?)""",
                (identificador, vencimento, valor, competencia),
            )
            pago = True

    return {"ok": True, "pago": pago}


# Não passa por _guarda_portal — é justamente essa página que resolve o
# caso de "sessão válida, mas nenhuma empresa escolhida ainda".
@app.get("/pages/selecionar-empresa.html")
async def pagina_selecionar_empresa(request: Request):
    if not _tem_sessao(request):
        return RedirectResponse("/pages/login.html", status_code=303)

    identificadores = request.session.get("empresas", [])
    dados_das_empresas = await asyncio.gather(*(acessorias.buscar_empresa(i) for i in identificadores))
    empresas = [
        {
            "identificador": identificador,
            "fantasia": (dados or {}).get("Fantasia") or (dados or {}).get("Razao") or identificador,
            "cnpj": (dados or {}).get("Identificador") or identificador,
        }
        for identificador, dados in zip(identificadores, dados_das_empresas)
    ]
    return templates.TemplateResponse(
        request,
        "selecionar-empresa.html",
        {"nome_usuario": request.session.get("nome", "cliente"), "empresas": empresas},
    )


class ArquivosEstaticos(StaticFiles):
    """StaticFiles do FastAPI não desliga o cache do navegador sozinho —
    ao contrário do scripts/dev-server.py (que existe só por causa disso).
    Sem isso, editar JS/CSS localmente e recarregar a página pode continuar
    servindo a versão antiga por dias, e parece um bug no código quando não
    é. Em produção (ENV=production) mantém cache normal — é o que
    docs/DEPLOY.md já recomenda para esses arquivos."""

    async def get_response(self, path: str, scope):
        resposta = await super().get_response(path, scope)
        if not HTTPS_ONLY:
            resposta.headers["Cache-Control"] = "no-store, must-revalidate"
        return resposta


# --- Senha: troca, "esqueceu sua senha?" e primeiro acesso por e-mail -----

def _ip_cliente(request: Request) -> str:
    # Atrás do proxy do Railway o uvicorn roda com --proxy-headers, então
    # request.client.host já é o IP real de quem acessou.
    return request.client.host if request.client else "desconhecido"


async def _corpo_json(request: Request) -> dict:
    try:
        corpo = await request.json()
    except ValueError:
        return {}
    return corpo if isinstance(corpo, dict) else {}


def _validar_nova_senha(nova_senha: str, confirmacao: str) -> JSONResponse | None:
    if not nova_senha or nova_senha != confirmacao:
        return JSONResponse({"erro": "As senhas não coincidem."}, status_code=400)
    if len(nova_senha) < TAMANHO_MINIMO_SENHA:
        return JSONResponse(
            {"erro": f"Use uma senha com pelo menos {TAMANHO_MINIMO_SENHA} caracteres."}, status_code=400
        )
    return None


async def _trocar_senha_da_conta(
    request: Request, tipo: str, conta_id: int, troca_obrigatoria_na_sessao: bool
) -> JSONResponse | None:
    """Usado por /api/trocar-senha e /api/equipe/trocar-senha. Exige a
    senha atual, a não ser na troca obrigatória logo depois de entrar com
    a senha provisória (a pessoa acabou de digitá-la no login). Só conta
    como troca obrigatória se a sessão E o banco ainda disserem que sim —
    se a senha já foi trocada por outro caminho (ex.: link do e-mail),
    uma sessão antiga não ganha passe livre. Devolve a resposta de erro,
    ou None quando a senha foi trocada."""
    corpo = await _corpo_json(request)
    senha_atual = str(corpo.get("senhaAtual", ""))
    nova_senha = str(corpo.get("novaSenha", ""))
    confirmacao = str(corpo.get("confirmacao", ""))

    erro = _validar_nova_senha(nova_senha, confirmacao)
    if erro:
        return erro

    tabela = "funcionarios" if tipo == "equipe" else "usuarios"
    with obter_conexao() as conexao:
        conta = conexao.execute(
            f"SELECT email, senha_hash, deve_trocar_senha FROM {tabela} WHERE id = ?", (conta_id,)
        ).fetchone()
    if not conta:
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    troca_obrigatoria = troca_obrigatoria_na_sessao and bool(conta["deve_trocar_senha"])
    if not troca_obrigatoria:
        if not senha_atual:
            return JSONResponse({"erro": "Informe sua senha atual.", "exigeSenhaAtual": True}, status_code=400)
        # Mesmo contador do login: uma sessão roubada não vira um jeito de
        # chutar a senha atual sem limite.
        ip = _ip_cliente(request)
        if login_bloqueado(conta["email"], ip):
            return JSONResponse(
                {"erro": "Muitas tentativas. Aguarde alguns minutos e tente de novo.", "exigeSenhaAtual": True},
                status_code=429,
            )
        if not verificar_senha(senha_atual, conta["senha_hash"]):
            registrar_falha_login(conta["email"], ip)
            return JSONResponse({"erro": "Senha atual incorreta.", "exigeSenhaAtual": True}, status_code=400)

    # Principalmente com a senha provisória comum do lote inicial
    # (criar_usuarios_em_massa.py --senha-comum): "trocar" pela mesma senha
    # deixaria a conta aberta pra qualquer outro cliente que a conhece.
    if verificar_senha(nova_senha, conta["senha_hash"]):
        return JSONResponse({"erro": "A nova senha precisa ser diferente da atual."}, status_code=400)

    with obter_conexao() as conexao:
        conexao.execute(
            f"UPDATE {tabela} SET senha_hash = ?, deve_trocar_senha = 0 WHERE id = ?",
            (gerar_hash(nova_senha), conta_id),
        )
    return None


MENSAGEM_REDEFINICAO_NEUTRA = (
    "Se este e-mail estiver cadastrado no portal, você vai receber em instantes um link "
    "para definir uma nova senha. Confira também a caixa de spam."
)


def _enviar_link_redefinicao(tipo: str, email: str) -> None:
    """Roda em segundo plano (BackgroundTasks → threadpool), depois que a
    resposta já saiu: o tempo de resposta é o mesmo exista a conta ou não,
    e o SMTP (bloqueante) nunca trava o event loop. Nada aqui vai pro log
    além de avisos genéricos — nunca o token nem o link."""
    if not email_envio.smtp_configurado():
        print("AVISO: pedido de redefinição de senha recebido, mas o SMTP não está configurado "
              "(SMTP_USUARIO/SMTP_SENHA) — nenhum e-mail foi enviado. Ver backend/.env.example.")
        return
    tabela = "funcionarios" if tipo == "equipe" else "usuarios"
    with obter_conexao() as conexao:
        conta = conexao.execute(f"SELECT id, email, nome FROM {tabela} WHERE email = ?", (email,)).fetchone()
    if not conta:
        return
    token = emitir_token_redefinicao(tipo, conta["id"])
    email_envio.enviar_link_redefinicao(conta["email"], conta["nome"], token)


@app.post("/api/esqueci-senha")
async def esqueci_senha(request: Request, tarefas: BackgroundTasks):
    """Sem autoatendimento de cadastro: isso só manda link pra quem já tem
    conta criada pelo escritório. A resposta é sempre a mesma, exista o
    e-mail ou não — não dá pra usar isso pra descobrir quem é cliente."""
    corpo = await _corpo_json(request)
    email = str(corpo.get("email", "")).strip().lower()
    tipo = "equipe" if corpo.get("tipo") == "equipe" else "cliente"

    if not email or "@" not in email or len(email) > TAMANHO_MAXIMO_EMAIL:
        return JSONResponse({"erro": "Informe um e-mail válido."}, status_code=400)

    ip = _ip_cliente(request)
    if redefinicao_bloqueada(email, ip):
        return JSONResponse(
            {"erro": "Muitos pedidos seguidos. Aguarde um pouco e tente de novo."}, status_code=429
        )
    registrar_pedido_redefinicao(email, ip)

    tarefas.add_task(_enviar_link_redefinicao, tipo, email)
    return {"ok": True, "mensagem": MENSAGEM_REDEFINICAO_NEUTRA}


@app.post("/api/redefinir-senha/validar")
async def validar_link_redefinicao(request: Request):
    """Só pra página avisar logo de cara que o link expirou, em vez de
    deixar a pessoa digitar a senha nova duas vezes à toa."""
    corpo = await _corpo_json(request)
    return {"valido": token_redefinicao_valido(str(corpo.get("token", "")))}


@app.post("/api/redefinir-senha")
async def redefinir_senha(request: Request):
    corpo = await _corpo_json(request)
    token = str(corpo.get("token", ""))
    nova_senha = str(corpo.get("novaSenha", ""))
    confirmacao = str(corpo.get("confirmacao", ""))

    erro = _validar_nova_senha(nova_senha, confirmacao)
    if erro:
        return erro

    resultado = consumir_token_redefinicao(token, nova_senha)
    if not resultado:
        return JSONResponse(
            {"erro": "Este link é inválido, já foi usado ou expirou. Peça um novo.", "linkInvalido": True},
            status_code=400,
        )

    tipo, conta_id = resultado
    email = email_da_conta(tipo, conta_id)
    if email:
        # Provou que é dono da caixa de e-mail — destrava o login dele.
        limpar_falhas_login(email)
    return {"ok": True, "destino": "equipe-login.html" if tipo == "equipe" else "login.html"}


# Um app só para os dois domínios: www.facchiniassessoria.com.br é a lead
# page, portal.facchiniassessoria.com.br cai direto no login.
def _no_portal(request: Request) -> bool:
    return (request.url.hostname or "").startswith("portal.")


@app.get("/")
@app.get("/index.html")
async def raiz(request: Request):
    if _no_portal(request):
        return RedirectResponse("/pages/login.html", status_code=303)
    return FileResponse(RAIZ / "index.html")


@app.get("/robots.txt")
async def robots(request: Request):
    if _no_portal(request):
        return PlainTextResponse("User-agent: *\nDisallow: /\n")
    return FileResponse(RAIZ / "robots.txt")


@app.get("/sitemap.xml")
async def sitemap():
    return FileResponse(RAIZ / "sitemap.xml")


@app.get("/site.webmanifest")
async def manifesto():
    return FileResponse(RAIZ / "site.webmanifest", media_type="application/manifest+json")


# Só as pastas públicas — nunca a raiz do projeto, que expõe backend/.env,
# o banco SQLite e o código-fonte. Páginas do portal com rota própria
# (acima) têm precedência sobre o estático de /pages.
for _pasta in ("css", "js", "assets", "pages"):
    app.mount(f"/{_pasta}", ArquivosEstaticos(directory=RAIZ / _pasta), name=_pasta)
