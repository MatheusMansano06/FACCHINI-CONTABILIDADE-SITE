/* =============================================================
   Solicitações — envio do formulário de nova solicitação,
   exclusivo desta página.
   ============================================================= */
'use strict';

function iniciarFormularioSolicitacao() {
  const form = document.querySelector('[data-formulario-solicitacao]');
  if (!form) return;

  const retorno = form.querySelector('[data-retorno-solicitacao]');
  const botaoEnviar = form.querySelector('button[type="submit"]');

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();

    retorno.classList.remove('esta-erro');
    retorno.textContent = 'Enviando…';
    botaoEnviar.disabled = true;

    try {
      const resposta = await fetch('/api/solicitacoes', {
        method: 'POST',
        body: new FormData(form), // multipart — o navegador define o Content-Type sozinho
      });

      const dados = await resposta.json().catch(() => ({}));

      if (resposta.ok) {
        retorno.classList.remove('esta-erro');
        retorno.textContent = 'Solicitação enviada! A equipe já foi avisada.';
        form.reset();
        return;
      }

      retorno.textContent = dados.erro || 'Não foi possível enviar. Tente de novo.';
      retorno.classList.add('esta-erro');
    } catch {
      retorno.textContent = 'Falha de conexão. Verifique sua internet e tente de novo.';
      retorno.classList.add('esta-erro');
    } finally {
      botaoEnviar.disabled = false;
    }
  });
}

iniciarFormularioSolicitacao();
