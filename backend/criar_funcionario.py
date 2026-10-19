#!/usr/bin/env python3
"""Cria ou atualiza a senha de um funcionário do painel interno
(atendimento) — separado do login do cliente. Só o administrador roda
isso, direto no servidor.

Uso:
    cd backend
    python3 criar_funcionario.py
"""
import asyncio

from dotenv import load_dotenv

load_dotenv()

import acessorias  # noqa: E402
from auth import definir_senha_interativa, gerar_hash  # noqa: E402
from database import inicializar_schema, obter_conexao  # noqa: E402


async def escolher_funcionario() -> dict | None:
    """Lista os usuários cadastrados na Acessórias e deixa o admin
    escolher um, pra puxar nome/e-mail prontos — mesmo padrão de
    create_user.py com contatos de cliente."""
    usuarios = await acessorias.listar_usuarios_escritorio()
    ativos = [u for u in usuarios if u.get("status") == "Ativo"]
    if not ativos:
        print("Nenhum usuário ativo encontrado na Acessórias — informe os dados na mão.")
        return None

    print("Usuários ativos na Acessórias:")
    for indice, usuario in enumerate(ativos, start=1):
        print(f"  {indice}. {usuario.get('nome')} <{usuario.get('email')}>")
    print("  0. Nenhum destes — informar na mão")

    escolha = input(f"Escolha [1-{len(ativos)}] (padrão 1): ").strip()
    if escolha == "0":
        return None
    try:
        indice = int(escolha) - 1 if escolha else 0
        return ativos[indice]
    except (ValueError, IndexError):
        print("Opção inválida, tente de novo.")
        return await escolher_funcionario()


def perguntar_com_padrao(prompt: str, padrao: str) -> str:
    valor = input(f"{prompt} [{padrao}]: ").strip()
    return valor or padrao


async def main() -> None:
    inicializar_schema()

    funcionario = await escolher_funcionario()
    if funcionario:
        email = perguntar_com_padrao("E-mail", funcionario.get("email", "")).strip().lower()
        nome = perguntar_com_padrao("Nome", funcionario.get("nome", "")).strip()
    else:
        email = input("E-mail: ").strip().lower()
        nome = input("Nome: ").strip()

    if not email or not nome:
        print("Todos os campos são obrigatórios.")
        return

    senha = definir_senha_interativa()
    if not senha:
        return

    senha_hash = gerar_hash(senha)

    with obter_conexao() as conexao:
        existente = conexao.execute("SELECT id FROM funcionarios WHERE email = ?", (email,)).fetchone()
        if existente:
            conexao.execute(
                "UPDATE funcionarios SET senha_hash = ?, nome = ?, deve_trocar_senha = 1 WHERE id = ?",
                (senha_hash, nome, existente["id"]),
            )
            print(f"Senha atualizada para {email}.")
        else:
            conexao.execute(
                "INSERT INTO funcionarios (email, senha_hash, nome) VALUES (?, ?, ?)",
                (email, senha_hash, nome),
            )
            print(f"Funcionário {email} criado.")


if __name__ == "__main__":
    asyncio.run(main())
