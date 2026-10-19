/* =============================================================
   Definir nova senha a partir do link do e-mail.
   O token vem no fragmento (#token=...) — o navegador nunca manda o
   que vem depois do # pro servidor, então ele não aparece em log de
   acesso. Assim que a página abre, o token sai da barra de endereço
   (e do histórico); fica só nesta aba (sessionStorage) pra sobreviver
   a um recarregar, e é apagado assim que a senha é salva.
   ============================================================= */
'use strict';

const CHAVE_TOKEN = 'facchini_token_redefinicao';
const TAMANHO_MINIMO = 8;
const DESTINOS_PERMITIDOS = ['login.html'];

function lerToken() {
  const doLink = new URLSearchParams(window.location.hash.slice(1)).get('token');
  if (doLink) {
    try { sessionStorage.setItem(CHAVE_TOKEN, doLink); } catch { /* sem storage: segue só em memória */ }
    history.replaceState(null, '', window.location.pathname);
    return doLink;
  }
  try { return sessionStorage.getItem(CHAVE_TOKEN) || ''; } catch { return ''; }
}

function esquecerToken() {
  try { sessionStorage.removeItem(CHAVE_TOKEN); } catch { /* nada a fazer */ }
}

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

async function iniciarFormulario() {
  const form = document.querySelector('[data-formulario-redefinir]');
  if (!form) return;

  const retorno = form.querySelector('[data-retorno]');
  const campos = form.querySelector('[data-bloco-campos]');
  const pedirNovo = form.querySelector('[data-pedir-novo]');
  const botao = form.querySelector('.acesso__entrar');

  const mostrarLinkInvalido = (mensagem) => {
    esquecerToken();
    campos.hidden = true;
    pedirNovo.hidden = false;
    retorno.classList.remove('esta-ok');
    retorno.classList.add('esta-erro');
    retorno.textContent = mensagem ||
      'Este link é inválido, já foi usado ou expirou. Peça um novo para continuar.';
  };

  const marcarErro = (nome, mensagem) => {
    const campo = form.elements[nome];
    const alvo = form.querySelector(`[data-erro-de="${nome}"]`);
    if (alvo) alvo.textContent = mensagem;
    campo.closest('.campo')?.classList.toggle('campo--invalido', Boolean(mensagem));
    campo.setAttribute('aria-invalid', String(Boolean(mensagem)));
  };

  const token = lerToken();
  if (!token) {
    mostrarLinkInvalido();
    return;
  }

  // Confere logo de cara se o link ainda vale — evita a pessoa digitar a
  // senha duas vezes pra só depois descobrir que o link expirou.
  try {
    const resposta = await fetch('/api/redefinir-senha/validar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
    const dados = await resposta.json().catch(() => ({}));
    if (resposta.ok && !dados.valido) {
      mostrarLinkInvalido();
      return;
    }
  } catch {
    // Sem conexão agora: deixa tentar mesmo assim, o envio confere de novo.
  }

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

    retorno.classList.remove('esta-erro', 'esta-ok');
    retorno.textContent = 'Salvando…';
    botao.disabled = true;

    try {
      const resposta = await fetch('/api/redefinir-senha', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, novaSenha, confirmacao }),
      });
      const dados = await resposta.json().catch(() => ({}));

      if (resposta.ok) {
        esquecerToken();
        campos.hidden = true;
        retorno.textContent = 'Senha definida! Levando você para o login…';
        retorno.classList.add('esta-ok');
        const destino = DESTINOS_PERMITIDOS.includes(dados.destino) ? dados.destino : 'login.html';
        setTimeout(() => { window.location.href = `${destino}?senha-redefinida`; }, 1800);
        return;
      }

      if (dados.linkInvalido) {
        mostrarLinkInvalido(dados.erro);
        return;
      }

      retorno.textContent = dados.erro || 'Não foi possível salvar. Tente de novo.';
      retorno.classList.add('esta-erro');
    } catch {
      retorno.textContent = 'Falha de conexão. Verifique sua internet e tente de novo.';
      retorno.classList.add('esta-erro');
    } finally {
      botao.disabled = false;
    }
  });
}

iniciarAlternarSenha();
iniciarFormulario();
