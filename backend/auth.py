"""Hash de senha e proteção contra força bruta no login.

O contador de tentativas fica em memória (reinicia com o processo, não
é compartilhado entre workers) — suficiente para o volume de um portal
de clientes com um único processo atrás do Nginx. Compartilhado entre o
login do cliente e o da equipe (backend/app.py) — é só um dicionário por
e-mail, não importa de qual tabela.
"""
import secrets
import time
from getpass import getpass

import bcrypt

TENTATIVAS_MAXIMAS = 5
JANELA_BLOQUEIO_SEGUNDOS = 15 * 60

TAMANHO_MINIMO_SENHA = 8

_tentativas: dict[str, list[float]] = {}


def gerar_senha_temporaria() -> str:
    """Senha temporária aleatória pra conta nova, dada pelo administrador ao
    cliente — ele é obrigado a trocar no primeiro acesso (ver
    deve_trocar_senha em database.py). Gerada a cada chamada, nunca fixa no
    código: quem ler o repositório não aprende a senha de ninguém."""
    return secrets.token_urlsafe(9)


def gerar_hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_senha(senha: str, senha_hash: str) -> bool:
    return bcrypt.checkpw(senha.encode("utf-8"), senha_hash.encode("utf-8"))


def identificador_bloqueado(identificador: str) -> bool:
    agora = time.time()
    tentativas = [t for t in _tentativas.get(identificador, []) if agora - t < JANELA_BLOQUEIO_SEGUNDOS]
    _tentativas[identificador] = tentativas
    return len(tentativas) >= TENTATIVAS_MAXIMAS


def registrar_tentativa_falha(identificador: str) -> None:
    _tentativas.setdefault(identificador, []).append(time.time())


def limpar_tentativas(identificador: str) -> None:
    _tentativas.pop(identificador, None)


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

    senha = getpass("  Senha: ")
    confirmacao = getpass("  Confirme a senha: ")
    if senha != confirmacao:
        print("  As senhas não coincidem.")
        return None
    if len(senha) < TAMANHO_MINIMO_SENHA:
        print(f"  Use uma senha com pelo menos {TAMANHO_MINIMO_SENHA} caracteres.")
        return None
    return senha
