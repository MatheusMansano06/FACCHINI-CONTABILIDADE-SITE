/* =============================================================
   Escolha de empresa — comportamento isolado desta tela.
   ============================================================= */
'use strict';

function iniciarSelecaoEmpresa() {
  const lista = document.querySelector('[data-lista-empresas]');
  const retorno = document.querySelector('[data-retorno-selecao]');
  if (!lista) return;

  lista.addEventListener('click', async (evento) => {
    const botao = evento.target.closest('[data-selecionar-empresa]');
    if (!botao) return;

    lista.querySelectorAll('[data-selecionar-empresa]').forEach((b) => { b.disabled = true; });
    retorno.classList.remove('esta-erro');
    retorno.textContent = 'Entrando…';

    try {
      const resposta = await fetch('/api/selecionar-empresa', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identificador: botao.dataset.identificador }),
      });

      const dados = await resposta.json().catch(() => ({}));

      if (resposta.ok) {
        window.location.href = dados.destino || 'portal-inicio.html';
        return;
      }

      retorno.textContent = dados.erro || 'Não foi possível entrar nessa empresa. Tente de novo.';
      retorno.classList.add('esta-erro');
    } catch {
      retorno.textContent = 'Falha de conexão. Verifique sua internet e tente de novo.';
      retorno.classList.add('esta-erro');
    } finally {
      lista.querySelectorAll('[data-selecionar-empresa]').forEach((b) => { b.disabled = false; });
    }
  });
}

iniciarSelecaoEmpresa();
