/* =============================================================
   Central de Atendimento — filtro por status e por prioridade,
   exclusivo desta página. Mesmo padrão de portal-obrigacoes.js,
   só com dois selects em vez de um.
   ============================================================= */
'use strict';

function iniciarFiltrosAtendimento() {
  const filtroStatus = document.querySelector('[data-filtro-status]');
  const filtroPrioridade = document.querySelector('[data-filtro-prioridade]');
  const tabela = document.querySelector('[data-tabela-atendimentos]');
  const vazio = document.querySelector('[data-atendimentos-vazio]');
  if (!tabela || (!filtroStatus && !filtroPrioridade)) return;

  const linhas = Array.from(tabela.querySelectorAll('tr[data-status]'));
  if (!linhas.length) return; // tabela já mostra "nenhuma solicitação", nada a filtrar

  const aplicarFiltros = () => {
    const status = filtroStatus?.value || '';
    const prioridade = filtroPrioridade?.value || '';
    let algumaVisivel = false;

    linhas.forEach((linha) => {
      const mostrar = (!status || linha.dataset.status === status)
        && (!prioridade || linha.dataset.prioridade === prioridade);
      linha.hidden = !mostrar;
      if (mostrar) algumaVisivel = true;
    });

    tabela.closest('table').hidden = !algumaVisivel;
    if (vazio) vazio.hidden = algumaVisivel;
  };

  filtroStatus?.addEventListener('change', aplicarFiltros);
  filtroPrioridade?.addEventListener('change', aplicarFiltros);
}

iniciarFiltrosAtendimento();
