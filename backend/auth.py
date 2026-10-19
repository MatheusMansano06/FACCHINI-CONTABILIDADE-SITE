"""Hash de senha, proteção contra força bruta e tokens de redefinição.

O contador de tentativas fica no SQLite (tabela tentativas_acesso, ver
database.py), não em memória: sobrevive a restart/deploy e vale igual
pra todos os workers. Cada linha é um evento com uma "chave" — ex.:
"login:fulano@empresa.com.br", "login-ip:200.1.2.3" — e o limite é só
contar quantas linhas daquela chave caíram dentro da janela.

O login do cliente e o da equipe dividem o mesmo contador por e-mail
(backend/app.py) — não importa de qual tabela a conta é.
"""
import hashlib
import hmac
import secrets
import time
from getpass import getpass

import bcrypt

from database import obter_conexao

TENTATIVAS_MAXIMAS = 5
JANELA_BLOQUEIO_SEGUNDOS = 15 * 60

# Limite mais largo por IP: pega quem testa muitos e-mails diferentes a
# partir da mesma máquina (o limite por e-mail sozinho não vê isso). Folgado
# o bastante pra um escritório inteiro atrás do mesmo IP errar a senha
# algumas vezes sem travar todo mundo.
TENTATIVAS_MAXIMAS_POR_IP = 30

# "Esqueceu sua senha?": no máximo 3 e-mails por conta e 10 pedidos por IP
# a cada hora — evita usar o formulário pra encher a caixa de alguém.
PEDIDOS_REDEFINICAO_POR_EMAIL = 3
PEDIDOS_REDEFINICAO_POR_IP = 10
JANELA_REDEFINICAO_SEGUNDOS = 60 * 60

VALIDADE_TOKEN_SEGUNDOS = 60 * 60  # link do e-mail vale 1 hora

TAMANHO_MINIMO_SENHA = 8
TAMANHO_MAXIMO_EMAIL = 254

# Hash de uma senha qualquer, só pra gastar o mesmo tempo de bcrypt quando
# o e-mail nem existe — sem isso, "usuário não existe" responde bem mais
# rápido que "senha errada" e dá pra descobrir quem é cliente pelo tempo.
_HASH_FICTICIO = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt()).decode("utf-8")


def gerar_senha_temporaria() -> str:
    """Senha temporária aleatória pra conta nova, dada pelo administrador ao
    cliente — ele é obrigado a trocar no primeiro acesso (ver
    deve_trocar_senha em database.py). Gerada a cada chamada, nunca fixa no
    código: quem ler o repositório não aprende a senha de ninguém."""
    return secrets.token_urlsafe(9)


def gerar_hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_senha(senha: str, senha_hash: str | None) -> bool:
    """senha_hash None (conta inexistente) ainda roda o bcrypt contra um
    hash fictício e devolve False — mesmo tempo de resposta nos dois casos."""
    if senha_hash is None:
        bcrypt.checkpw(senha.encode("utf-8"), _HASH_FICTICIO.encode("utf-8"))
        return False
    return bcrypt.checkpw(senha.encode("utf-8"), senha_hash.encode("utf-8"))


# --- Limite de tentativas (persistido no SQLite) -------------------------

def _registrar_evento(chave: str) -> None:
    with obter_conexao() as conexao:
        conexao.execute("INSERT INTO tentativas_acesso (chave, momento) VALUES (?, ?)", (chave, time.time()))


def _excedeu(chave: str, maximo: int, janela: int) -> bool:
    agora = time.time()
    with obter_conexao() as conexao:
        # Faxina barata a cada consulta: nenhum limite olha mais de 1 dia
        # pra trás, então nada mais velho que isso precisa ficar guardado.
        conexao.execute("DELETE FROM tentativas_acesso WHERE momento < ?", (agora - 24 * 60 * 60,))
        (total,) = conexao.execute(
            "SELECT COUNT(*) FROM tentativas_acesso WHERE chave = ? AND momento > ?",
            (chave, agora - janela),
        ).fetchone()
    return total >= maximo


def _limpar(chave: str) -> None:
    with obter_conexao() as conexao:
        conexao.execute("DELETE FROM tentativas_acesso WHERE chave = ?", (chave,))


def login_bloqueado(email: str, ip: str) -> bool:
    return _excedeu(f"login:{email}", TENTATIVAS_MAXIMAS, JANELA_BLOQUEIO_SEGUNDOS) or _excedeu(
        f"login-ip:{ip}", TENTATIVAS_MAXIMAS_POR_IP, JANELA_BLOQUEIO_SEGUNDOS
    )


def registrar_falha_login(email: str, ip: str) -> None:
    _registrar_evento(f"login:{email}")
    _registrar_evento(f"login-ip:{ip}")


def limpar_falhas_login(email: str) -> None:
    """Só zera o contador do e-mail. O do IP continua — acertar a própria
    senha não pode "apagar" os erros que o mesmo IP fez em outras contas."""
    _limpar(f"login:{email}")


def redefinicao_bloqueada(email: str, ip: str) -> bool:
    """Conta todo pedido (exista a conta ou não) — o limite em si não
    revela nada sobre quem é cliente."""
    return _excedeu(
        f"redefinir:{email}", PEDIDOS_REDEFINICAO_POR_EMAIL, JANELA_REDEFINICAO_SEGUNDOS
    ) or _excedeu(f"redefinir-ip:{ip}", PEDIDOS_REDEFINICAO_POR_IP, JANELA_REDEFINICAO_SEGUNDOS)


def registrar_pedido_redefinicao(email: str, ip: str) -> None:
    _registrar_evento(f"redefinir:{email}")
    _registrar_evento(f"redefinir-ip:{ip}")


# --- Tokens de redefinição de senha --------------------------------------
# O token em si só existe no link do e-mail; o banco guarda apenas o
# SHA-256 dele. Quem copiar o banco não consegue usar nenhum link pendente.

TABELA_POR_TIPO = {"cliente": "usuarios", "equipe": "funcionarios"}


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def emitir_token_redefinicao(tipo: str, conta_id: int) -> str:
    """Gera um token novo e invalida qualquer outro ainda pendente da mesma
    conta — só o link do e-mail mais recente funciona."""
    token = secrets.token_urlsafe(32)
    with obter_conexao() as conexao:
        conexao.execute(
            "DELETE FROM tokens_redefinicao_senha WHERE tipo = ? AND conta_id = ?", (tipo, conta_id)
        )
        conexao.execute(
            "INSERT INTO tokens_redefinicao_senha (tipo, conta_id, token_hash, expira_em) VALUES (?, ?, ?, ?)",
            (tipo, conta_id, _hash_token(token), time.time() + VALIDADE_TOKEN_SEGUNDOS),
        )
    return token


def _buscar_token_valido(conexao, token: str):
    if not token or len(token) > 200:
        return None
    token_hash = _hash_token(token)
    linha = conexao.execute(
        "SELECT id, tipo, conta_id, token_hash, expira_em FROM tokens_redefinicao_senha WHERE token_hash = ?",
        (token_hash,),
    ).fetchone()
    if not linha or not hmac.compare_digest(linha["token_hash"], token_hash):
        return None
    if linha["expira_em"] < time.time() or linha["tipo"] not in TABELA_POR_TIPO:
        return None
    return linha


def token_redefinicao_valido(token: str) -> bool:
    with obter_conexao() as conexao:
        return _buscar_token_valido(conexao, token) is not None


def consumir_token_redefinicao(token: str, nova_senha: str) -> tuple[str, int] | None:
    """Troca a senha da conta dona do token e apaga o token (uso único).
    Devolve (tipo, conta_id) — tipo "cliente" ou "equipe" — ou None se o link for
    inválido, expirado ou já usado. O DELETE com checagem de rowcount
    garante que dois envios simultâneos do mesmo link não passam os dois."""
    senha_hash = gerar_hash(nova_senha)
    with obter_conexao() as conexao:
        linha = _buscar_token_valido(conexao, token)
        if not linha:
            return None
        apagado = conexao.execute("DELETE FROM tokens_redefinicao_senha WHERE id = ?", (linha["id"],))
        if apagado.rowcount != 1:
            return None
        tabela = TABELA_POR_TIPO[linha["tipo"]]  # nome vem do dicionário fixo, nunca do usuário
        conexao.execute(
            f"UPDATE {tabela} SET senha_hash = ?, deve_trocar_senha = 0 WHERE id = ?",
            (senha_hash, linha["conta_id"]),
        )
        # Qualquer outro link pendente da mesma conta também morre aqui.
        conexao.execute(
            "DELETE FROM tokens_redefinicao_senha WHERE tipo = ? AND conta_id = ?",
            (linha["tipo"], linha["conta_id"]),
        )
        conexao.execute("DELETE FROM tokens_redefinicao_senha WHERE expira_em < ?", (time.time(),))
        return linha["tipo"], linha["conta_id"]


def email_da_conta(tipo: str, conta_id: int) -> str | None:
    tabela = TABELA_POR_TIPO[tipo]
    with obter_conexao() as conexao:
        linha = conexao.execute(f"SELECT email FROM {tabela} WHERE id = ?", (conta_id,)).fetchone()
    return linha["email"] if linha else None


def ler_senha_confirmada(rotulo: str = "Senha") -> str | None:
    """Pede a senha duas vezes com getpass (não aparece na tela nem fica no
    histórico do terminal). Devolve None se não coincidir ou for curta."""
    senha = getpass(f"  {rotulo}: ")
    confirmacao = getpass(f"  Confirme a {rotulo.lower()}: ")
    if senha != confirmacao:
        print("  As senhas não coincidem.")
        return None
    if len(senha) < TAMANHO_MINIMO_SENHA:
        print(f"  Use uma senha com pelo menos {TAMANHO_MINIMO_SENHA} caracteres.")
        return None
    return senha


def definir_senha_interativa() -> str | None:
    """Senha temporária gerada agora (a pessoa troca no primeiro acesso) ou
    uma senha específica digitada agora. Devolve None se inválida. Usado
    pelos dois scripts de administrador (create_user.py e
    criar_funcionario.py) — mesma regra de senha nos dois, um lugar só pra
    mudar."""
    senha_temporaria = gerar_senha_temporaria()
    usar_gerada = input(
        f"  Usar senha temporária gerada agora ({senha_temporaria})? A pessoa troca no primeiro acesso. [S/n] "
    ).strip().lower()
    if usar_gerada != "n":
        return senha_temporaria
    return ler_senha_confirmada()
