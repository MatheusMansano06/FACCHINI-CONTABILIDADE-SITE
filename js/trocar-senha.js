/* =============================================================
   Troca obrigatória da senha provisória, logo depois do login.
   ?equipe na URL = conta da equipe (outro endpoint e outro logout).
   O servidor bloqueia o portal/painel até a troca acontecer.
   ============================================================= */
'use strict';

const TAMANHO_MINIMO = 8;
const DA_EQUIPE = new URLSearchParams(window.location.search).has('equipe');
const ENDPOINT = DA_EQUIPE ? '/api/equipe/trocar-senha' : '/api/trocar-senha';
const LOGIN = 'login.html';
const DESTINOS_PERMITIDOS = DA_EQUIPE
  ? ['equipe-atendimento.html']
  : ['portal-inicio.html', 'selecionar-empresa.html'];

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

function iniciarFormulario() {
  const form = document.querySelector('[data-formulario-trocar]');
  if (!form) return;

  const retorno = form.querySelector('[data-retorno]');
  const campos = form.querySelector('[data-bloco-campos]');
  const botao = form.querySelector('.acesso__entrar');
  const sair = form.querySelector('[data-sair]');
  if (DA_EQUIPE && sair) sair.href = '/equipe/logout';

  const marcarErro = (nome, mensagem) => {
    const campo = form.elements[nome];
    const alvo = form.querySelector(`[data-erro-de="${nome}"]`);
    if (alvo) alvo.textContent = mensagem;
    campo.closest('.campo')?.classList.toggle('campo--invalido', Boolean(mensagem));
    campo.setAttribute('aria-invalid', String(Boolean(mensagem)));
  };

  const mostrar = (mensagem, ok) => {
    retorno.textContent = mensagem;
    retorno.classList.toggle('esta-ok', ok);
    retorno.classList.toggle('esta-erro', !ok);
  };

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();

    const novaSenha = form.elements.novaSenha.value;
    const confirmacao = form.elements.confirmacao.value;

    const erroTamanho = novaSenha.length < TAMANHO_MINIMO
      ? `Use uma senha com pelo menos ${TAMANHO_MINIMO} caracteres.` : '';
    const erroConfirmacao = !erroTamanho && novaSenha !== confirmacao ? 'As senhas não coincidem.' : '';
    marcarErro('novaSenha', erroTamanho);
    marcarErro('confirmacao', erroConfirmacao);
    if (erroTamanho || erroConfirmacao) return;

    mostrar('Salvando…', true);
    botao.disabled = true;

    try {
      const resposta = await fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ novaSenha, confirmacao }),
      });
      const dados = await resposta.json().catch(() => ({}));

      if (resposta.ok) {
        campos.hidden = true;
        mostrar('Senha trocada! Entrando…', true);
        const destino = DESTINOS_PERMITIDOS.includes(dados.destino) ? dados.destino : DESTINOS_PERMITIDOS[0];
        setTimeout(() => { window.location.href = destino; }, 1000);
        return;
      }

      if (resposta.status === 401) {
        window.location.href = LOGIN;
        return;
      }

      // A troca obrigatória já foi feita por outro caminho (outra aba, link
      // do e-mail): esta tela não serve mais, segue pro portal.
      if (dados.exigeSenhaAtual) {
        mostrar('Sua senha já foi trocada. Levando você ao portal…', true);
        setTimeout(() => { window.location.href = DESTINOS_PERMITIDOS[0]; }, 1200);
        return;
      }

      mostrar(dados.erro || 'Não foi possível salvar. Tente de novo.', false);
    } catch {
      mostrar('Falha de conexão. Verifique sua internet e tente de novo.', false);
    } finally {
      botao.disabled = false;
    }
  });
}

iniciarAlternarSenha();
iniciarFormulario();
