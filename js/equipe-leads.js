/* =============================================================
   Leads do site — botão "marcar como contatado", exclusivo desta
   página. Ver POST /api/equipe/leads/alternar-contatado em
   backend/app.py. Só textContent, nunca innerHTML.
   ============================================================= */
'use strict';

function iniciarMarcarContatado() {
  const botoes = document.querySelectorAll('[data-marcar-contatado]');
  const retorno = document.querySelector('[data-retorno-leads]');
  if (!botoes.length) return;

  const avisar = (texto) => {
    if (retorno) retorno.textContent = texto;
  };

  botoes.forEach((botao) => {
    botao.addEventListener('click', async () => {
      botao.disabled = true;
      avisar('');
      try {
        const resposta = await fetch('/api/equipe/leads/alternar-contatado', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: Number(botao.dataset.leadId) }),
        });
        const dados = await resposta.json().catch(() => ({}));
        if (resposta.status === 401) {
          window.location.href = 'equipe-login.html';
          return;
        }
        if (!resposta.ok) {
          avisar(dados.erro || 'Não foi possível salvar. Tente de novo.');
          return;
        }
        botao.classList.toggle('botao-pago--ativo', dados.contatado);
        botao.setAttribute('aria-pressed', String(dados.contatado));
        botao.querySelector('span').textContent = dados.contatado ? 'Contatado' : 'Marcar como contatado';
        const info = botao.closest('td')?.querySelector('[data-contatado-info]');
        if (info) info.textContent = dados.contatado ? `${dados.contatado_em} · ${dados.contatado_por}` : '';
      } catch {
        avisar('Falha de conexão. Verifique sua internet e tente de novo.');
      } finally {
        botao.disabled = false;
      }
    });
  });
}

iniciarMarcarContatado();
