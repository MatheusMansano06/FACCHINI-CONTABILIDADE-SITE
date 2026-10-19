/* =============================================================
   Financeiro — "marcar como pago", exclusivo desta página. Só
   local (não escreve na Acessórias, que não tem esse endpoint) —
   ver POST /api/boletos/alternar-pago em backend/app.py.
   ============================================================= */
'use strict';

function iniciarMarcarPago() {
  const botoes = document.querySelectorAll('[data-marcar-pago]');
  if (!botoes.length) return;

  botoes.forEach((botao) => {
    botao.addEventListener('click', async () => {
      botao.disabled = true;
      try {
        const resposta = await fetch('/api/boletos/alternar-pago', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            vencimento: botao.dataset.vencimento,
            valor: botao.dataset.valor,
            competencia: botao.dataset.competencia,
          }),
        });
        const dados = await resposta.json().catch(() => ({}));
        if (!resposta.ok) {
          alert(dados.erro || 'Não foi possível salvar. Tente de novo.');
          return;
        }
        botao.classList.toggle('botao-pago--ativo', dados.pago);
        botao.setAttribute('aria-pressed', String(dados.pago));
        botao.querySelector('span').textContent = dados.pago ? 'Pago (você marcou)' : 'Marcar como pago';
      } catch {
        alert('Falha de conexão. Verifique sua internet e tente de novo.');
      } finally {
        botao.disabled = false;
      }
    });
  });
}

iniciarMarcarPago();
