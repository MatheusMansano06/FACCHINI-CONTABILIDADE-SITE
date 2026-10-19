/* =============================================================
   "Esqueceu sua senha?" — pede o link de redefinição por e-mail.
   Serve para cliente e equipe: ?equipe na URL manda tipo "equipe"
   e o "voltar" aponta pro login da equipe.
   ============================================================= */
'use strict';

const MENSAGEM_NEUTRA =
  'Se este e-mail estiver cadastrado no portal, você vai receber em instantes um link ' +
  'para definir uma nova senha. Confira também a caixa de spam.';

function iniciarFormulario() {
  const form = document.querySelector('[data-formulario-esqueci]');
  if (!form) return;

  const ehEquipe = new URLSearchParams(window.location.search).has('equipe');
  if (ehEquipe) {
    const voltar = form.querySelector('[data-voltar-login]');
    if (voltar) voltar.href = 'equipe-login.html';
  }

  const campo = form.elements.email;
  const retorno = form.querySelector('[data-retorno]');
  const botao = form.querySelector('.acesso__entrar');
  const blocoCampo = form.querySelector('[data-bloco-campos]');
  const alvoErro = form.querySelector('[data-erro-de="email"]');

  const validar = () => {
    const valor = campo.value.trim();
    const ok = valor.length > 0 && valor.includes('@');
    alvoErro.textContent = ok ? '' : 'Informe o e-mail cadastrado.';
    campo.closest('.campo')?.classList.toggle('campo--invalido', !ok);
    campo.setAttribute('aria-invalid', String(!ok));
    return ok;
  };

  campo.addEventListener('blur', validar);

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    if (!validar()) return;

    retorno.classList.remove('esta-erro', 'esta-ok');
    retorno.textContent = 'Enviando…';
    botao.disabled = true;

    try {
      const resposta = await fetch('/api/esqueci-senha', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: campo.value.trim(), tipo: ehEquipe ? 'equipe' : 'cliente' }),
      });
      const dados = await resposta.json().catch(() => ({}));

      if (resposta.ok) {
        // Mesma mensagem sempre — a tela nunca diz se o e-mail existe.
        blocoCampo.hidden = true;
        botao.hidden = true;
        retorno.textContent = MENSAGEM_NEUTRA;
        retorno.classList.add('esta-ok');
        return;
      }

      retorno.textContent = dados.erro || 'Não foi possível enviar agora. Tente de novo.';
      retorno.classList.add('esta-erro');
    } catch {
      retorno.textContent = 'Falha de conexão. Verifique sua internet e tente de novo.';
      retorno.classList.add('esta-erro');
    } finally {
      botao.disabled = false;
    }
  });
}

iniciarFormulario();
