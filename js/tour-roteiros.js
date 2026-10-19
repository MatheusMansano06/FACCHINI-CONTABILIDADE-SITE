/* =============================================================
   Roteiros do tour guiado do Henrique (motor em js/tour.js).
   Primeiro e último passo (sem "alvo") = cena em tela cheia.
   Passos do meio = balão apontando o elemento do seletor "alvo";
   se o elemento não existir ou estiver escondido, o passo é pulado.
   "\n" separa parágrafos na fala da cena. Texto simples, sem HTML.
   ============================================================= */
'use strict';

(() => {
const secao = (id) => `section[aria-labelledby="${id}"]`;
const MENU_PORTAL = '.portal__sidebar .portal__nav';
const MENU_USUARIO = '.portal__usuario';

window.TOUR_ROTEIROS = {
  /* ------------------------------------------------ cliente */
  inicio: [
    {
      titulo: 'Oi! Eu sou o Henrique, da Facchini 👋',
      texto:
        'Seja muito bem-vindo ao portal do cliente. Aqui você acompanha a contabilidade da sua empresa sem precisar mandar mensagem pra ninguém.\n' +
        'Documentos, obrigações, boletos, avisos do escritório e pedidos pra nossa equipe — tudo num lugar só.\n' +
        'Vou te mostrar cada parte desta tela em menos de um minuto.',
    },
    { alvo: MENU_PORTAL, titulo: 'O menu do portal', texto: 'Por aqui você navega entre as áreas: Documentos, Obrigações, Calendário, Solicitações, Financeiro, Comunicados e o Perfil da empresa. Na primeira vez que abrir cada uma, eu apareço pra explicar.' },
    { alvo: secao('titulo-acesso-rapido'), titulo: 'Acesso rápido', texto: 'Os atalhos do dia a dia: mandar documentos pra gente, ver obrigações, abrir uma solicitação, conferir boletos, ler comunicados ou falar com a equipe no WhatsApp.' },
    { alvo: secao('titulo-novidades'), titulo: 'Novidades da contabilidade', texto: 'Os avisos mais recentes do escritório — mudanças de prazo, lembretes, informações importantes pra sua empresa. “Ver todas” abre a lista completa.' },
    { alvo: secao('titulo-documentos'), titulo: 'Documentos disponíveis', texto: 'O que entregamos pra você nos últimos 30 dias: guias, balancetes, folhas de pagamento. É só clicar pra baixar, sem esperar e-mail.' },
    { alvo: secao('titulo-vencimentos'), titulo: 'Próximos vencimentos', texto: 'O que vence nos próximos dias. Fica de olho aqui pra nada passar do prazo.' },
    { alvo: secao('titulo-atendimentos'), titulo: 'Últimas solicitações', texto: 'Os pedidos que você abriu com a nossa equipe e em que pé cada um está.' },
    { alvo: MENU_USUARIO, titulo: 'Seu menu', texto: 'Aqui você vê o perfil da empresa, troca de empresa (se tiver mais de uma com a gente), sai do portal e pode rever este tour quando quiser.' },
    {
      titulo: 'Pronto, você já conhece o portal! 🎉',
      texto:
        'Qualquer dúvida, abre uma solicitação ou chama a gente no WhatsApp — a equipe responde rapidinho.\n' +
        'Conta com a Facchini. Seja bem-vindo!',
    },
  ],

  documentos: [
    {
      titulo: 'Seus documentos',
      texto:
        'Aqui fica tudo o que a Facchini entregou pra sua empresa nos últimos 12 meses: guias, balancetes, folhas de pagamento e afins.\n' +
        'Chega de procurar no e-mail — está tudo organizado aqui.',
    },
    { alvo: secao('titulo-documentos'), titulo: 'A lista de documentos', texto: 'Cada linha mostra o nome, o mês de referência, o tipo e quando enviamos. Em “Ações” você baixa o arquivo na hora.' },
    { titulo: 'É isso! 🎉', texto: 'Dica: se precisar de algum documento que não está aqui, abre uma solicitação que a gente providencia.' },
  ],

  obrigacoes: [
    {
      titulo: 'Obrigações da sua empresa',
      texto:
        'DAS, GPS, DCTFWeb e as demais obrigações fiscais — as que estão no prazo, as atrasadas e as já entregues.\n' +
        'Mostro os últimos e os próximos 90 dias.',
    },
    { alvo: '.filtro-status[data-filtro-status]', titulo: 'Filtrar por status', texto: 'Quer ver só o que está pendente ou atrasado? Escolha aqui e a lista filtra na hora.' },
    { alvo: secao('titulo-obrigacoes') + ' .tabela-documentos', titulo: 'A lista', texto: 'Cada obrigação com a competência, o prazo, o setor responsável aqui na Facchini e o status.' },
    { titulo: 'Fácil, né? 🎉', texto: 'Dica: o Calendário mostra essas mesmas obrigações organizadas por dia do mês.' },
  ],

  calendario: [
    {
      titulo: 'Calendário de obrigações',
      texto: 'As obrigações da sua empresa, só que organizadas por dia — pra você enxergar o mês inteiro de uma vez.',
    },
    { alvo: '.calendario__nav', titulo: 'Troque de mês', texto: 'Use as setas pra ver o mês anterior ou o próximo.' },
    { alvo: '.calendario', titulo: 'Os dias do mês', texto: 'Cada dia mostra o que vence nele. As cores indicam se está em dia, em andamento ou atrasado.' },
    { titulo: 'Prontinho! 🎉', texto: 'Dica: quer a lista com filtros? Ela fica em Obrigações, no menu.' },
  ],

  solicitacoes: [
    {
      titulo: 'Solicitações',
      texto:
        'Precisa de algo da Facchini? Aqui você abre um pedido que chega direto no setor certo.\n' +
        'Vira um ticket de verdade: você acompanha cada resposta por aqui mesmo.',
    },
    { alvo: '[data-formulario-solicitacao]', titulo: 'Abrir uma solicitação', texto: 'Escreva o assunto, escolha o setor (fiscal, pessoal, contábil...), a prioridade, descreva o que precisa e, se quiser, anexe um arquivo de até 30 MB. Depois é só enviar.' },
    { alvo: secao('titulo-solicitacoes'), titulo: 'Acompanhe aqui', texto: 'Todos os pedidos que você abriu, os mais recentes primeiro, com o status de cada um.' },
    { titulo: 'É com a gente! 🎉', texto: 'Dica: quanto mais detalhe na descrição, mais rápido a equipe resolve.' },
  ],

  financeiro: [
    {
      titulo: 'Financeiro',
      texto: 'Os boletos de honorários e guias com vencimento — pendentes, quitados ou cancelados — dos últimos 90 dias e dos próximos 30.',
    },
    { alvo: secao('titulo-financeiro') + ' .tabela-documentos', titulo: 'Seus boletos', texto: 'Competência, vencimento, valor e status de cada boleto, num lugar só.' },
    { alvo: '.botao-pago', titulo: 'Marcar como pago', texto: 'Já pagou? Marque aqui pra controlar o que falta. É só um controle seu — o pagamento em si é confirmado pelo banco.' },
    { titulo: 'Tudo sob controle! 🎉', texto: 'Dica: confira os próximos vencimentos também no Início.' },
  ],

  comunicados: [
    {
      titulo: 'Comunicados da Facchini',
      texto:
        'Aqui ficam os avisos que o escritório manda pra você: mudanças na legislação, lembretes de prazo, recados importantes.\n' +
        'Os mais recentes aparecem também no Início.',
    },
    { alvo: secao('titulo-comunicados'), titulo: 'Os avisos', texto: 'Mais recentes primeiro. Os marcados como “Só para sua empresa” foram enviados especialmente pra você.' },
    { alvo: '.ajuda-comunicados', titulo: 'Ficou com dúvida?', texto: 'Abra uma solicitação pro setor responsável ou fale com a gente direto pelo WhatsApp.' },
    { titulo: 'Fica ligado aqui! 🎉', texto: 'Sempre que tiver algo importante, eu aviso por esta tela.' },
  ],

  perfil: [
    {
      titulo: 'Perfil da empresa',
      texto: 'Como a sua empresa está cadastrada na Facchini, quem tem acesso a ela e quando o portal foi acessado.',
    },
    { alvo: secao('titulo-dados-empresa'), titulo: 'Dados da empresa', texto: 'Razão social, CNPJ, regime tributário e os demais dados do cadastro. Viu algo desatualizado? Abra uma solicitação que a gente corrige.' },
    { alvo: secao('titulo-contatos'), titulo: 'Contatos cadastrados', texto: 'As pessoas que recebem avisos e têm acesso ao portal desta empresa.' },
    { alvo: secao('titulo-acessos'), titulo: 'Últimos acessos', texto: 'Quando esta conta entrou no portal. Se aparecer um acesso que não foi seu, troque a senha e avise a gente.' },
    { titulo: 'Pronto! 🎉', texto: 'Seus dados em dia deixam a nossa comunicação mais rápida.' },
  ],

  /* ------------------------------------------------ equipe */
  'equipe-atendimento': [
    {
      titulo: 'Fala, equipe! Aqui é o Henrique 👋',
      texto:
        'Esta é a Central de Atendimento: todas as solicitações que os clientes abrem pelo portal caem aqui, de todas as empresas.\n' +
        'Daqui vocês respondem, mudam o status e finalizam — e tudo grava direto na Acessórias.',
    },
    { alvo: MENU_PORTAL, titulo: 'O painel da equipe', texto: 'Atendimento é esta fila. Em Comunicados vocês publicam avisos pros clientes e em Leads do site estão os pedidos de contato que chegam pelo formulário.' },
    { alvo: '[data-formulario-filtro]', titulo: 'Filtros', texto: 'Filtre por prioridade e por status pra focar no que é mais urgente.' },
    { alvo: secao('titulo-atendimento') + ' .tabela-documentos', titulo: 'A fila', texto: 'Ordenada por prioridade e tempo de espera: empresa, assunto, há quantos dias está aberta e o status.' },
    { alvo: '.atendimento-abrir', titulo: 'Abrir e responder', texto: 'Mostra o histórico completo e o formulário de resposta: escreva o comentário, escolha o novo status (Resolvendo, Com o cliente ou Finalizada) e, se precisar, um novo prazo. Dá pra marcar como comentário interno.' },
    { alvo: '.atendimento-paginacao', titulo: 'Mais solicitações', texto: 'A fila é dividida em páginas. Use Anterior e Próxima pra navegar.' },
    { titulo: 'Bora atender! 🎉', texto: 'Cliente bem atendido é cliente que fica. Contem comigo.' },
  ],

  'equipe-comunicados': [
    {
      titulo: 'Comunicados pros clientes',
      texto: 'Aqui vocês publicam avisos que aparecem na hora no portal dos clientes — na tela de Comunicados e no Início.',
    },
    { alvo: '[data-formulario-comunicado]', titulo: 'Publicar um comunicado', texto: 'Título, categoria e o texto. Em “Para quem”, escolham todos os clientes ou uma empresa específica pelo CNPJ/CPF.' },
    { alvo: secao('titulo-publicados'), titulo: 'Publicados', texto: 'Tudo que está no ar agora, os mais recentes primeiro.' },
    { alvo: '.botao-remover', titulo: 'Remover', texto: 'Tira o comunicado do portal na hora. Fica registrado quem publicou o quê.' },
    { titulo: 'É isso! 🎉', texto: 'Dica: avisos curtos e objetivos são os mais lidos.' },
  ],

  'equipe-leads': [
    {
      titulo: 'Leads do site',
      texto:
        'Toda vez que alguém preenche o formulário “Falar com especialista” no site, o pedido cai aqui.\n' +
        'É cliente novo batendo na porta — quanto mais rápido o retorno, maior a chance de fechar.',
    },
    { alvo: secao('titulo-leads') + ' .tabela-documentos', titulo: 'Os pedidos de contato', texto: 'Nome, contato, empresa, segmento e a mensagem. Os botões abrem e-mail ou WhatsApp direto com a pessoa.' },
    { alvo: '[data-marcar-contatado]', titulo: 'Marcar como contatado', texto: 'Depois de retornar, marquem aqui. Assim ninguém liga duas vezes pra mesma pessoa e fica registrado quem atendeu.' },
    { alvo: '.leads__paginacao', titulo: 'Mais pedidos', texto: 'Os pedidos ficam em páginas — dos mais recentes pros mais antigos.' },
    { titulo: 'Vamos vender! 🎉', texto: 'Meta: responder todo lead no mesmo dia.' },
  ],
};
})();
