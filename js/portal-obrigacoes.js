/* =============================================================
   Obrigações — filtro por status, exclusivo desta página.
   Não mexe no DOM de nenhuma outra tela do portal.
   ============================================================= */
'use strict';

function iniciarFiltroObrigacoes() {
  const filtro = document.querySelector('[data-filtro-status]');
  const tabela = document.querySelector('[data-tabela-obrigacoes]');
  const vazio = document.querySelector('[data-obrigacoes-vazio]');
  if (!filtro || !tabela) return;

  const linhas = Array.from(tabela.querySelectorAll('tr[data-status]'));
  if (!linhas.length) return; // tabela já mostra "nenhuma obrigação", nada a filtrar

  filtro.addEventListener('change', () => {
    const escolhido = filtro.value;
    let algumaVisivel = false;

    linhas.forEach((linha) => {
      const mostrar = !escolhido || linha.dataset.status === escolhido;
      linha.hidden = !mostrar;
      if (mostrar) algumaVisivel = true;
    });

    tabela.closest('table').hidden = !algumaVisivel;
    if (vazio) vazio.hidden = algumaVisivel;
  });
}

iniciarFiltroObrigacoes();
