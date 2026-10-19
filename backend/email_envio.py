"""Envio de e-mail do portal (link de "Esqueceu sua senha?").

Dois caminhos, escolhidos pelo ambiente — nada fixo no código (ver
backend/.env.example):

1. RESEND_API_KEY definido: envia pela API HTTPS do Resend. É o caminho em
   produção: o Railway bloqueia SMTP de saída nos planos Free/Trial/Hobby.
   O remetente (EMAIL_REMETENTE) precisa ser de um domínio verificado lá.
2. Senão, SMTP com SSL pela caixa da Locaweb:

    SMTP_HOST         padrão email-ssl.com.br
    SMTP_PORT         padrão 465 (SSL direto)
    SMTP_USUARIO      a caixa que autentica (ex.: notificacao@...)
    SMTP_SENHA        senha dessa caixa
    EMAIL_REMETENTE   padrão notificacao@facchiniassessoria.com.br
    URL_PORTAL        padrão https://portal.facchiniassessoria.com.br

SMTP_SSL=0 é só pra desenvolvimento (servidor SMTP falso local, sem TLS e
sem login) — em produção (ENV=production) é ignorado e o SSL é sempre usado.

enviar_email() é bloqueante (rede): quem chama de dentro do FastAPI deve
rodar fora do event loop (BackgroundTasks / run_in_threadpool).
"""
import html
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import httpx

log = logging.getLogger("facchini.email")

NOME_REMETENTE = "Facchini Assessoria Contábil"


def _config() -> dict:
    producao = os.environ.get("ENV") == "production"
    return {
        "host": os.environ.get("SMTP_HOST") or "email-ssl.com.br",
        "porta": int(os.environ.get("SMTP_PORT") or 465),
        "usuario": os.environ.get("SMTP_USUARIO", ""),
        "senha": os.environ.get("SMTP_SENHA", ""),
        "remetente": os.environ.get("EMAIL_REMETENTE") or "notificacao@facchiniassessoria.com.br",
        "ssl": producao or os.environ.get("SMTP_SSL", "1") != "0",
    }


def url_portal() -> str:
    """Base dos links mandados por e-mail. Sempre do ambiente, nunca do
    cabeçalho Host da requisição — senão alguém pediria a redefinição da
    conta de outra pessoa com um Host falso e o link no e-mail dela
    apontaria pro site do atacante (host header injection)."""
    return (os.environ.get("URL_PORTAL") or "https://portal.facchiniassessoria.com.br").rstrip("/")


def _chave_resend() -> str:
    return os.environ.get("RESEND_API_KEY", "").strip()


def smtp_configurado() -> bool:
    """True se há algum jeito de enviar (API do Resend ou SMTP)."""
    cfg = _config()
    return bool(_chave_resend()) or bool(cfg["usuario"] and cfg["senha"]) or not cfg["ssl"]


def _enviar_por_resend(destinatario: str, assunto: str, texto: str, corpo_html: str | None) -> bool:
    cfg = _config()
    dados = {
        # Texto puro: a API aceita UTF-8 direto (formataddr codificaria o
        # "á" no formato de cabeçalho SMTP, que apareceria literal).
        "from": f"{NOME_REMETENTE} <{cfg['remetente']}>",
        "to": [destinatario],
        "subject": assunto,
        "text": texto,
    }
    if corpo_html:
        dados["html"] = corpo_html
    try:
        resposta = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {_chave_resend()}"},
            json=dados,
            timeout=20,
        )
    except httpx.HTTPError as erro:
        log.error("Falha ao falar com a API do Resend — %s", type(erro).__name__)
        return False
    if resposta.status_code >= 300:
        # Só o código e a mensagem de erro deles — nunca o corpo enviado.
        log.error("Resend recusou o e-mail: HTTP %s %s", resposta.status_code, resposta.text[:200])
        return False
    return True


def enviar_email(destinatario: str, assunto: str, texto: str, corpo_html: str | None = None) -> bool:
    """Devolve True se o servidor aceitou a mensagem. Nunca levanta exceção
    e nunca registra o corpo no log (ele pode conter link com token)."""
    if _chave_resend():
        return _enviar_por_resend(destinatario, assunto, texto, corpo_html)

    cfg = _config()
    if not smtp_configurado():
        log.warning("E-mail não configurado (RESEND_API_KEY ou SMTP_USUARIO/SMTP_SENHA) — não enviado.")
        return False

    mensagem = EmailMessage()
    mensagem["From"] = formataddr((NOME_REMETENTE, cfg["remetente"]))
    mensagem["To"] = destinatario
    mensagem["Subject"] = assunto
    mensagem["Date"] = formatdate(localtime=True)
    mensagem["Message-ID"] = make_msgid(domain=cfg["remetente"].split("@")[-1])
    mensagem.set_content(texto)
    if corpo_html:
        mensagem.add_alternative(corpo_html, subtype="html")

    try:
        if cfg["ssl"]:
            contexto = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["host"], cfg["porta"], context=contexto, timeout=20) as servidor:
                servidor.login(cfg["usuario"], cfg["senha"])
                servidor.send_message(mensagem)
        else:
            log.warning("SMTP_SSL=0 — enviando sem TLS (só para desenvolvimento).")
            with smtplib.SMTP(cfg["host"], cfg["porta"], timeout=20) as servidor:
                if cfg["usuario"] and cfg["senha"]:
                    servidor.login(cfg["usuario"], cfg["senha"])
                servidor.send_message(mensagem)
        return True
    except (smtplib.SMTPException, OSError) as erro:
        log.error("Falha ao enviar e-mail via %s:%s — %s", cfg["host"], cfg["porta"], type(erro).__name__)
        return False


def enviar_link_redefinicao(destinatario: str, nome: str, token: str) -> bool:
    """E-mail de "esqueceu sua senha?" / primeiro acesso. O token vai no
    fragmento (#) do link: o navegador não manda o que vem depois do # pro
    servidor, então ele não aparece em log de acesso nem em Referer."""
    link = f"{url_portal()}/pages/redefinir-senha.html#token={token}"
    primeiro_nome = (nome or "").split(" ")[0] or "cliente"

    texto = (
        f"Olá, {primeiro_nome}.\n\n"
        "Recebemos um pedido para definir uma nova senha de acesso ao portal da "
        "Facchini Assessoria Contábil. Para continuar, abra o link abaixo:\n\n"
        f"{link}\n\n"
        "O link vale por 1 hora e só pode ser usado uma vez.\n\n"
        "Se não foi você quem pediu, pode ignorar este e-mail — sua senha atual "
        "continua a mesma.\n\n"
        "Facchini Assessoria Contábil\n"
    )

    link_html = html.escape(link, quote=True)
    corpo_html = f"""\
<!DOCTYPE html>
<html lang="pt-BR">
<body style="margin:0;padding:24px;background:#F5F1EA;font-family:Arial,Helvetica,sans-serif;color:#1B2430;">
  <div style="max-width:520px;margin:0 auto;background:#FFFFFF;border-radius:8px;padding:32px;">
    <p style="margin:0 0 16px;font-size:16px;">Olá, {html.escape(primeiro_nome)}.</p>
    <p style="margin:0 0 16px;font-size:15px;line-height:1.5;">
      Recebemos um pedido para definir uma nova senha de acesso ao portal da
      Facchini Assessoria Contábil.
    </p>
    <p style="margin:24px 0;">
      <a href="{link_html}" style="display:inline-block;background:#D9A441;color:#0B1E33;
         text-decoration:none;font-weight:bold;padding:12px 24px;border-radius:999px;">Definir nova senha</a>
    </p>
    <p style="margin:0 0 16px;font-size:13px;line-height:1.5;color:#5B6573;">
      O link vale por 1 hora e só pode ser usado uma vez. Se o botão não abrir,
      copie e cole este endereço no navegador:<br>
      <span style="word-break:break-all;">{link_html}</span>
    </p>
    <p style="margin:0;font-size:13px;line-height:1.5;color:#5B6573;">
      Se não foi você quem pediu, pode ignorar este e-mail — sua senha atual continua a mesma.
    </p>
  </div>
</body>
</html>
"""
    return enviar_email(destinatario, "Defina sua senha — Portal Facchini", texto, corpo_html)
