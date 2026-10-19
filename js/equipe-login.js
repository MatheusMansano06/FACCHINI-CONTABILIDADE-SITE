/* =============================================================
   Tela de acesso da equipe — cópia do comportamento de login.js,
   só troca o endpoint e o destino padrão. Arquivo próprio (não
   login.js) porque as duas telas podem evoluir sem risco de uma
   quebrar a outra.
   ============================================================= */
'use strict';

/* ------------------------------------------- mostrar/ocultar senha */
function iniciarAlternarSenha() {
  const botao = document.querySelector('[data-alternar-senha]');
  const campo = document.querySelector('[data-campo-senha]');
  if (!botao || !campo) return;

  botao.addEventListener('click', () => {
    const oculta = campo.type === 'password';
    campo.type = oculta ? 'text' : 'password';
    botao.setAttribute('aria-pressed', String(oculta));
    botao.setAttribute('aria-label', oculta ? 'Ocultar senha' : 'Mostrar senha');
    botao.querySelector('use').setAttribute('href', oculta ? '#i-olho' : '#i-olho-fechado');
  });
}

/* -------------------------------------------------- formulário */
function iniciarFormulario() {
  const form = document.querySelector('[data-formulario-login]');
  if (!form) return;

  const retorno = form.querySelector('[data-retorno-login]');
  const botaoEntrar = form.querySelector('.acesso__entrar');

  const validar = (campo, mensagemVazio) => {
    const ok = campo.value.trim().length > 0;
    const alvoErro = document.querySelector(`[data-erro-de="${campo.name}"]`);
    if (alvoErro) alvoErro.textContent = ok ? '' : mensagemVazio;
    campo.closest('.campo')?.classList.toggle('campo--invalido', !ok);
    campo.setAttribute('aria-invalid', String(!ok));
    return ok;
  };

  form.elements.usuario.addEventListener('blur', () => validar(form.elements.usuario, 'Informe seu usuário.'));
  form.elements.senha.addEventListener('blur', () => validar(form.elements.senha, 'Informe sua senha.'));

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();

    const usuarioOk = validar(form.elements.usuario, 'Informe seu usuário.');
    const senhaOk = validar(form.elements.senha, 'Informe sua senha.');
    if (!usuarioOk || !senhaOk) return;

    retorno.classList.remove('esta-erro');
    retorno.textContent = 'Entrando…';
    botaoEntrar.disabled = true;

    try {
      const resposta = await fetch('/api/equipe/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          usuario: form.elements.usuario.value.trim(),
          senha: form.elements.senha.value,
        }),
      });

      const dados = await resposta.json().catch(() => ({}));

      if (resposta.ok) {
        window.location.href = dados.destino || 'equipe-atendimento.html';
        return;
      }

      retorno.textContent = dados.erro || 'Não foi possível entrar. Tente de novo.';
      retorno.classList.add('esta-erro');
    } catch {
      retorno.textContent = 'Falha de conexão. Verifique sua internet e tente de novo.';
      retorno.classList.add('esta-erro');
    } finally {
      botaoEntrar.disabled = false;
    }
  });
}

iniciarAlternarSenha();
iniciarFormulario();
