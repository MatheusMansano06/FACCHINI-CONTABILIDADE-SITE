#!/usr/bin/env python3
"""Cria ou atualiza a senha de um cliente do portal.

Não existe autocadastro — decisão de produto já tomada (ver README.md):
só o administrador roda este script, direto no servidor, para dar ou
trocar o acesso de um cliente. Nome e e-mail vêm, sempre que possível,
direto do cadastro de contatos da Acessórias — não precisa redigitar o
que já está lá.

Uso:
    cd backend
    python3 create_user.py
"""
import asyncio

from dotenv import load_dotenv

load_dotenv()

import acessorias  # noqa: E402
from auth import definir_senha_interativa, gerar_hash  # noqa: E402
from database import inicializar_schema, obter_conexao  # noqa: E402


async def pedir_empresa(empresas_ja_ligadas: set[str]) -> tuple[str, dict | None] | None:
    """Pede um CNPJ/CPF e valida contra a Acessórias. Devolve (identificador,
    dados_da_empresa) — dados_da_empresa é None se a Acessórias não
    reconheceu (admin confirmou mesmo assim) ou a integração está fora."""
    identificador = input("  CNPJ/CPF na Acessórias (em branco pra parar): ").strip()
    if not identificador:
        return None
    if identificador in empresas_ja_ligadas:
        print("  Essa empresa já está vinculada a este cliente.")
        return await pedir_empresa(empresas_ja_ligadas)

    empresa = await acessorias.buscar_empresa(identificador)
    if not empresa:
        confirmar = input(
            "  AVISO: a Acessórias não reconheceu esse CNPJ/CPF (ou a integração "
            "está indisponível agora). Confirme o valor — digitou certo? "
            "Continuar mesmo assim? [s/N] "
        ).strip().lower()
        if confirmar != "s":
            print("  Empresa descartada, digite de novo.")
            return await pedir_empresa(empresas_ja_ligadas)
        return identificador, None

    print(f"  Empresa encontrada: {empresa.get('Fantasia') or empresa.get('Razao')}")
    return identificador, empresa


async def escolher_contato(identificador: str) -> dict | None:
    """Lista os contatos já cadastrados na Acessórias pra essa empresa e
    deixa o admin escolher um, pra puxar nome/e-mail prontos. Devolve None
    se não houver contato ou o admin preferir digitar na mão."""
    contatos = await acessorias.listar_contatos(identificador)
    if not contatos:
        print("  Nenhum contato cadastrado nessa empresa na Acessórias — informe os dados na mão.")
        return None

    print("  Contatos cadastrados nessa empresa na Acessórias:")
    for indice, contato in enumerate(contatos, start=1):
        nome = contato.get("Nome", "")
        email = contato.get("E-mail", "")
        print(f"    {indice}. {nome} <{email}>")
    print("    0. Nenhum destes — informar na mão")

    escolha = input(f"  Escolha [1-{len(contatos)}] (padrão 1): ").strip()
    if escolha == "0":
        return None
    try:
        indice = int(escolha) - 1 if escolha else 0
        return contatos[indice]
    except (ValueError, IndexError):
        print("  Opção inválida, tente de novo.")
        return await escolher_contato(identificador)


def perguntar_com_padrao(prompt: str, padrao: str) -> str:
    valor = input(f"{prompt} [{padrao}]: ").strip()
    return valor or padrao


def buscar_empresas_no_indice(email: str) -> list[tuple[str, str]]:
    """Consulta o índice local (backend/indexar_contatos.py) por todas as
    empresas onde esse e-mail aparece como contato na Acessórias. A API
    não tem essa busca pronta — sem o índice, o administrador só descobre
    empresa por empresa, na mão."""
    with obter_conexao() as conexao:
        linhas = conexao.execute(
            "SELECT DISTINCT identificador_acessorias, nome_contato FROM contatos_acessorias WHERE email = ?",
            (email,),
        ).fetchall()
    return [(linha["identificador_acessorias"], linha["nome_contato"]) for linha in linhas]


async def main() -> None:
    inicializar_schema()

    print("Empresa do cliente (a primeira decide de qual contato puxamos nome/e-mail):")
    ja_ligadas: set[str] = set()
    primeira = await pedir_empresa(ja_ligadas)
    if not primeira:
        print("Informe ao menos uma empresa.")
        return
    identificador_principal, empresa_principal = primeira
    ja_ligadas.add(identificador_principal)

    contato = await escolher_contato(identificador_principal) if empresa_principal else None

    if contato:
        email = perguntar_com_padrao("E-mail do cliente", contato.get("E-mail", "")).strip().lower()
        nome = perguntar_com_padrao("Nome do cliente", contato.get("Nome", "")).strip()
    else:
        email = input("E-mail do cliente: ").strip().lower()
        nome = input("Nome do cliente: ").strip()

    if not email or not nome:
        print("Todos os campos são obrigatórios.")
        return

    senha = definir_senha_interativa()
    if not senha:
        return

    identificadores = [identificador_principal]

    encontradas_no_indice = [
        (identificador, nome_contato)
        for identificador, nome_contato in buscar_empresas_no_indice(email)
        if identificador not in ja_ligadas
    ]
    if encontradas_no_indice:
        print(f"\nEsse e-mail também aparece como contato em outra(s) {len(encontradas_no_indice)} "
              "empresa(s) no índice local (backend/indexar_contatos.py):")
        for identificador, nome_contato in encontradas_no_indice:
            print(f"  - {identificador} (contato: {nome_contato})")
        usar = input("Vincular todas essas automaticamente? [S/n] ").strip().lower()
        if usar != "n":
            for identificador, _ in encontradas_no_indice:
                identificadores.append(identificador)
                ja_ligadas.add(identificador)
    else:
        print("\n(Nenhuma outra empresa encontrada para esse e-mail no índice local — "
              "rode backend/indexar_contatos.py se ele nunca foi gerado ou está desatualizado.)")

    print("Vincular mais alguma empresa a este mesmo login? (em branco pra parar)")
    while True:
        outra = await pedir_empresa(ja_ligadas)
        if not outra:
            break
        identificadores.append(outra[0])
        ja_ligadas.add(outra[0])

    senha_hash = gerar_hash(senha)

    with obter_conexao() as conexao:
        existente = conexao.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
        if existente:
            usuario_id = existente["id"]
            # Toda vez que o administrador define a senha (aqui, não pelo
            # cliente trocando sozinho), a conta volta a exigir troca no
            # próximo acesso — é sempre uma senha que outra pessoa sabe.
            conexao.execute(
                "UPDATE usuarios SET senha_hash = ?, nome = ?, deve_trocar_senha = 1 WHERE id = ?",
                (senha_hash, nome, usuario_id),
            )
            print(f"Senha atualizada para {email}.")
        else:
            cursor = conexao.execute(
                "INSERT INTO usuarios (email, senha_hash, nome) VALUES (?, ?, ?)",
                (email, senha_hash, nome),
            )
            usuario_id = cursor.lastrowid
            print(f"Usuário {email} criado.")

        for identificador in identificadores:
            conexao.execute(
                """INSERT INTO usuario_empresas (usuario_id, identificador_acessorias)
                   VALUES (?, ?)
                   ON CONFLICT (usuario_id, identificador_acessorias) DO NOTHING""",
                (usuario_id, identificador),
            )
        print(f"{len(identificadores)} empresa(s) vinculada(s).")


if __name__ == "__main__":
    asyncio.run(main())
