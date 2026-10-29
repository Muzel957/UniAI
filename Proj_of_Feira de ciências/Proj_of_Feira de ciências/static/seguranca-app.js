/* =========================================================
   APP DO CELULAR (página Segurança)
   Funcionalidades do chatbot do grupo (verificação, câmeras, casa, avisos da IA,
   modo apresentação) + histórico, assistente virtual guiado com comandos e problema a cada 30 s.
========================================================= */
const $ = id => document.getElementById(id);
const dormir = ms => new Promise(r => setTimeout(r, ms));
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt) e.textContent = txt; return e; };
const post = (u, b) => fetch(u, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {})
}).then(r => r.json());

const CAMS = { cam1: 'ENTRADA', cam2: 'SALA', cam3: 'COZINHA', cam4: 'GARAGEM', cam5: 'QUINTAL' };
const COMODOS = { entrada: 'ENTRADA', sala: 'SALA', cozinha: 'COZINHA', garagem: 'GARAGEM', quintal: 'QUINTAL' };
const CAM_COMODO = { cam1: 'entrada', cam2: 'sala', cam3: 'cozinha', cam4: 'garagem', cam5: 'quintal' };
const TIPOS = { luz: 'Luz', ar: 'Ar-condicionado', outro: 'Dispositivo' };
const DEFEITO = { sem_sinal: 'SEM SINAL', lente_suja: 'IMAGEM BORRADA', escuro: 'SEM LUZ', congelada: 'IMAGEM TRAVADA' };
const TITULOS = { inicio: 'Painel Principal', cameras: 'Câmeras', casa: 'Controle da Casa', chat: 'Assistente virtual guiado', historico: 'Histórico de Eventos' };

let painelAtual = 'inicio';
let ocupado = false, verificado = false, problemaAtivo = false, surgiu = false, proximoEm = 0;
let camAberta = false, camAtual = 'cam1', camEstados = {}, camLuzes = {}, camAr = {};
let invAtual = null, animando = false, trocando = false, camFrame = 0;
let dispositivos = [], chatIniciado = false, alertaForcado = null;

/* ================= NAVEGAÇÃO ================= */
function ir(p) {
    painelAtual = p;
    camAberta = p === 'cameras';
    document.querySelectorAll('.painel').forEach(s => s.classList.toggle('ativo', s.id === 'p-' + p));
    document.querySelectorAll('#nav-app button').forEach(b => b.classList.toggle('ativo', b.dataset.p === p));
    $('app-titulo').textContent = TITULOS[p];
    if (p === 'cameras') { pedirPermissao(); fecharToast(); atualizarPainelCam(); atualizarImagem(); desenharControlesCam(); }
    if (p === 'casa') carregarCasa();
    if (p === 'historico') carregarHistorico();
    if (p === 'chat') abrirChat();
    atualizarBadges();
}

function pedirPermissao() {
    if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission();
}

function atualizarBadges() {
    $('b-inicio').classList.toggle('hidden', !(problemaAtivo || surgiu) || painelAtual === 'inicio');
    const defVisivel = Object.values(camEstados).some(Boolean);
    $('b-cameras').classList.toggle('hidden', !(invAtual || defVisivel) || painelAtual === 'cameras');
}

/* ================= STATUS ================= */
function atualizarStatus() {
    let txt = 'AGUARDANDO VERIFICAÇÃO', cls = '', ico = '🛡️', dica = '';
    if (invAtual) { txt = 'PESSOA ESTRANHA NA PROPRIEDADE'; cls = 'erro pisca'; ico = '🚨'; dica = 'Abra as câmeras, ache onde ela está e chame a polícia.'; }
    else if (problemaAtivo) { txt = 'PROBLEMA DETECTADO'; cls = 'erro'; ico = '⚠️'; dica = 'Toque em Corrigir problema para resolver.'; }
    else if (surgiu) { txt = 'ANOMALIA DETECTADA'; cls = 'erro pisca'; ico = '⚠️'; dica = 'O sistema percebeu algo estranho. Toque em Verificar sistema para descobrir o que é.'; }
    else if (verificado) { txt = 'SEGURO'; cls = 'ok'; ico = '✅'; dica = proximoEm ? 'Próximo evento simulado em ' + proximoEm + ' s.' : ''; }
    else { dica = proximoEm ? 'Monitoramento ativo. Próximo evento simulado em ' + proximoEm + ' s.' : 'Monitoramento ativo.'; }
    if (!ocupado) {
        $('sys-status').textContent = txt;
        $('sys-status').className = 'status-pill ' + cls;
        $('status-ico').textContent = ico;
        $('status-dica').textContent = dica;
    }
    $('btn-corrigir').classList.toggle('hidden', !(problemaAtivo && verificado && !ocupado));
    atualizarBadges();
}

/* ================= VERIFICAR E CORRIGIR ================= */
function linha(txt, cls) {
    const p = el('p', cls, txt), s = $('console-saida');
    s.appendChild(p);
    s.scrollTop = s.scrollHeight;
    return p;
}

function resultado(p, rotulo, cls, detalhe) {
    p.appendChild(el('span', cls, ' ' + rotulo));
    if (detalhe) p.appendChild(document.createTextNode(' ' + detalhe));
    $('console-saida').scrollTop = 1e6;
}

function travar(v) { ocupado = v; $('btn-verificar').disabled = v; atualizarStatus(); }

async function mostrarAlertaForcado() {
    const a = alertaForcado;
    alertaForcado = null;
    const p = linha('  ' + a.titulo + ' ...');
    await dormir(700);
    resultado(p, 'ALERTA', 'alerta', a.resultado);
}

async function verificarSistema() {
    if (ocupado) return;
    ir('inicio');
    travar(true); pedirPermissao(); fecharToast();
    $('painel-console').classList.remove('hidden');
    $('console-saida').innerHTML = '';
    $('scan-fill').style.width = '0%';
    $('sys-status').textContent = 'VERIFICANDO'; $('sys-status').className = 'status-pill';
    $('status-ico').textContent = '🔍'; $('status-dica').textContent = 'Aguarde o fim da verificação.';
    alertaForcado = null;
    const r = await post('/api/varredura');
    if (!r.sucesso) { travar(false); return; }

    linha('Iniciando varredura completa do sistema de segurança...', 'dim'); await dormir(800);
    linha('Carregando módulos: rede, acessos, sensores, alarme, câmeras e firmware', 'dim'); await dormir(1000);

    let total = 0, falhas = 0;
    for (let i = 0; i < r.linhas.length; i++) {
        const [acao, res, nivel] = r.linhas[i];
        $('scan-fill').style.width = ((i + 1) / r.linhas.length * 100) + '%';
        if (nivel === 'titulo') { linha(''); linha(acao, 'titulo'); await dormir(600); continue; }
        if (alertaForcado) {
            if (falhas === 0) { await mostrarAlertaForcado(); falhas++; total++; } else alertaForcado = null;
        }
        const p = linha('  ' + acao + ' ...');
        await dormir(400 + Math.random() * 700);
        total++;
        if (nivel === 'alerta') { falhas++; resultado(p, 'ALERTA', 'alerta', res); }
        else resultado(p, 'OK', 'ok', res === 'OK' ? '' : res);
    }
    if (alertaForcado && falhas === 0) { await mostrarAlertaForcado(); falhas++; total++; }

    linha(''); linha('RESULTADO', 'titulo'); await dormir(500);
    const c = await post('/api/varredura/concluir');
    if (c.problema && falhas === 0) falhas = 1;
    linha('Verificações realizadas: ' + total);
    linha('Falhas encontradas: ' + falhas);
    await dormir(500);
    if (c.problema) {
        linha('Problema encontrado: ' + c.titulo + '.', 'alerta');
        linha('Use o botão Corrigir problema logo abaixo.', 'dim');
        chatLog('🔍 Verificação concluída: ' + c.titulo + '. Quer que eu corrija?', 'bot-alerta', ['Corrigir o problema', 'Status']);
    } else {
        linha('Nenhuma falha encontrada. O sistema de segurança está de acordo.', 'ok');
        chatLog('🔍 Verificação concluída: nenhuma falha encontrada. ✅', 'bot-sucesso', ['Status', 'Ver câmeras']);
    }
    verificado = true; problemaAtivo = !!c.problema; surgiu = false;
    travar(false);
    if (problemaAtivo) $('btn-corrigir').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    poll();
}

async function corrigirProblema() {
    if (ocupado) return;
    ir('inicio');
    travar(true);
    $('painel-console').classList.remove('hidden');
    if (!$('console-saida').children.length) $('scan-fill').style.width = '0%';
    $('sys-status').textContent = 'CORRIGINDO'; $('sys-status').className = 'status-pill';
    $('status-ico').textContent = '🛠️'; $('status-dica').textContent = 'Aplicando a correção.';
    linha(''); linha('Executando a correção do problema...', 'dim');
    await dormir(700);
    const r = await post('/api/resolver');
    if (!r.sucesso) { linha(r.mensagem, 'aviso'); travar(false); return; }

    for (let i = 0; i < r.passos.length; i++) {
        $('scan-fill').style.width = ((i + 1) / r.passos.length * 100) + '%';
        const p = linha('  ' + r.passos[i] + ' ...');
        await dormir(1000 + Math.random() * 800);
        resultado(p, 'OK', 'ok');
    }
    await dormir(500);
    linha(r.mensagem, 'ok');
    linha('Problema resolvido. Execute a verificação para confirmar.', 'dim');
    chatLog('🛠️ ' + r.mensagem + ' Problema resolvido!', 'bot-sucesso', ['Verificar o sistema', 'Status']);
    problemaAtivo = false; surgiu = false; verificado = true;
    travar(false); poll();
}

/* ================= CÂMERAS ================= */
function montarSeletor() {
    Object.keys(CAMS).forEach(id => {
        const b = el('button', '', id.replace('cam', 'CAM '));
        b.id = 'sel-' + id; b.type = 'button';
        b.onclick = () => trocarCam(id);
        $('cam-seletor').appendChild(b);
    });
}

function trocarCam(id) {
    camAtual = id; trocando = true;
    atualizarPainelCam(); atualizarImagem(); desenharControlesCam();
    setTimeout(() => { trocando = false; atualizarImagem(); }, 350);  // chiado ao trocar de câmera
}

function atualizarPainelCam() {
    Object.keys(CAMS).forEach(id => {
        $('sel-' + id).classList.toggle('sel', id === camAtual);
        $('sel-' + id).classList.toggle('defeito', !!camEstados[id]);  // câmera com defeito aparece marcada
    });
    $('cam-nome').textContent = 'CAM ' + camAtual.slice(3) + ' ' + CAMS[camAtual];
    if (animando) return;
    const def = camEstados[camAtual];
    const vendo = invAtual && invAtual.cam === camAtual && !def;
    const noturna = camLuzes[camAtual] === false;
    $('cam-aviso').textContent = def ? DEFEITO[def] : (noturna ? 'VISÃO NOTURNA' : '');
    $('btn-policia').classList.toggle('hidden', !vendo);
    $('cam-legenda').textContent = vendo ? 'PESSOA ESTRANHA IDENTIFICADA NESTA CÂMERA. Chame a polícia agora.'
        : def ? 'Esta câmera está com defeito. Na aba Início, toque em Verificar sistema e depois em Corrigir problema.'
        : invAtual ? 'Há uma pessoa estranha na propriedade. Procure nas outras câmeras.'
        : noturna ? 'Nenhuma atividade suspeita. A luz está apagada: a câmera usa a visão noturna (infravermelho).'
        : 'Nenhuma atividade suspeita.';
}

function atualizarImagem() {
    if (!camAberta || animando) return;
    const est = trocando ? 'sem_sinal' : (camEstados[camAtual] || (invAtual && invAtual.cam === camAtual ? 'invasor' : 'ok'));
    if (est !== 'congelada') {
        camFrame++;
        $('cam-hora').textContent = new Date().toLocaleTimeString('pt-BR');
    }
    const luz = camLuzes[camAtual] === false ? 0 : 1;
    $('cam-img').src = '/api/camera/' + camAtual + '.png?estado=' + est + '&luz=' + luz + '&ar=' + (camAr[camAtual] || 0) + '&f=' + camFrame;
}
setInterval(atualizarImagem, 450);

async function chamarPolicia() {
    const r = await post('/api/invasor/policia', { cam: camAtual });
    if (!r.sucesso) { $('cam-legenda').textContent = r.mensagem; return; }
    animando = true; invAtual = null; fecharToast();
    $('btn-policia').classList.add('hidden');
    $('cam-nome').textContent = 'VISÃO GERAL DA CASA'; $('cam-aviso').textContent = '';
    $('cam-legenda').textContent = 'Chamando a polícia...';
    const urls = [...Array(r.frames).keys()].map(f => '/api/policia/' + r.comodo + '/' + f + '.png');
    await Promise.all(urls.map(u => new Promise(res => { const im = new Image(); im.onload = im.onerror = res; im.src = u; })));
    for (let f = 0; f < urls.length; f++) {
        $('cam-img').src = urls[f];
        $('cam-legenda').textContent = r.fases.filter(x => x[0] <= f).pop()[1];
        await dormir(150);
    }
    await dormir(3000);
    animando = false;
    chatLog('🚓 A polícia chegou e levou a pessoa estranha. A propriedade está segura.', 'bot-sucesso', ['Status']);
    atualizarStatus(); atualizarPainelCam(); atualizarImagem();
}

/* ================= CASA ================= */
async function carregarCasa() {
    const r = await fetch('/api/casa').then(x => x.json()).catch(() => ({}));
    if (r.sucesso) { dispositivos = r.dispositivos; redesenhar(); }
}

function redesenhar() {
    Object.entries(CAM_COMODO).forEach(([cam, c]) => {  // a luz do cômodo muda a imagem da câmera
        camLuzes[cam] = dispositivos.some(d => d.comodo === c && d.tipo === 'luz' && d.ligado);
        const ars = dispositivos.filter(d => d.comodo === c && d.tipo === 'ar');
        camAr[cam] = !ars.length ? 0 : ars.some(d => d.ligado) ? 2 : 1;
    });
    desenharCasa();
    desenharControlesCam();
    const luzes = dispositivos.filter(d => d.tipo === 'luz');
    $('ui-luzes').textContent = 'Luzes: ' + luzes.filter(d => d.ligado).length + '/' + luzes.length;
    if (camAberta) atualizarPainelCam();
}

async function acaoDispositivo(rota, id) {
    const r = await post(rota, { id });
    if (r.sucesso) { dispositivos = r.dispositivos; redesenhar(); poll(); }
}

function linhaDispositivo(d, comRemover) {
    const row = el('div', 'disp' + (d.ligado ? ' on' : ''));
    row.appendChild(el('span', 'ico ' + d.tipo + (d.ligado ? ' on' : '')));
    const nome = el('span', 'disp-nome', d.nome);
    nome.appendChild(el('small', '', TIPOS[d.tipo]));
    row.appendChild(nome);
    const t = el('button', 'toggle' + (d.ligado ? ' on' : ''));  // chave liga/desliga: cor e texto mostram o estado
    t.type = 'button';
    t.setAttribute('role', 'switch');
    t.setAttribute('aria-checked', d.ligado ? 'true' : 'false');
    t.title = d.ligado ? 'Toque para desligar' : 'Toque para ligar';
    t.appendChild(el('span', 'toggle-txt', d.ligado ? 'LIGADO' : 'DESLIGADO'));
    t.appendChild(el('span', 'knob'));
    t.onclick = () => acaoDispositivo('/api/casa/alternar', d.id);
    row.appendChild(t);
    if (comRemover) {
        const x = el('button', 'disp-rem', '✕');
        x.type = 'button'; x.title = 'Remover dispositivo'; x.setAttribute('aria-label', 'Remover ' + d.nome);
        x.onclick = () => acaoDispositivo('/api/casa/remover', d.id);
        row.appendChild(x);
    }
    return row;
}

function desenharCasa() {
    const box = $('casa-lista');
    box.innerHTML = '';
    Object.entries(COMODOS).forEach(([c, nome]) => {
        box.appendChild(el('p', 'titulo', nome));
        const ds = dispositivos.filter(d => d.comodo === c);
        if (!ds.length) box.appendChild(el('p', 'dim', '  Nenhum dispositivo neste cômodo.'));
        ds.forEach(d => box.appendChild(linhaDispositivo(d, true)));
    });
}

function desenharControlesCam() {  // controles do cômodo, logo abaixo da câmera
    const box = $('cam-controles');
    box.innerHTML = '';
    box.appendChild(el('p', 'titulo', 'CONTROLE DA CASA: ' + CAMS[camAtual]));
    const ds = dispositivos.filter(d => d.comodo === CAM_COMODO[camAtual]);
    if (!ds.length) box.appendChild(el('p', 'dim', 'Nenhum dispositivo neste cômodo. Adicione um na aba Casa.'));
    ds.forEach(d => box.appendChild(linhaDispositivo(d, false)));
}

async function adicionarDispositivo(e) {
    e.preventDefault();
    const r = await post('/api/casa/adicionar', {
        nome: $('disp-nome').value, comodo: $('disp-comodo').value, tipo: $('disp-tipo').value
    });
    $('casa-msg').textContent = r.mensagem;
    $('casa-msg').className = 'msg-box ' + (r.sucesso ? 'success' : 'error');
    if (r.sucesso) { $('disp-nome').value = ''; dispositivos = r.dispositivos; redesenhar(); poll(); }
}

/* ================= CÂMERAS NA TELA INICIAL ================= */
function desenharListaCams() {
    const box = $('lista-cams');
    box.innerHTML = '';
    let online = 0;
    Object.entries(CAMS).forEach(([id, nome]) => {
        const def = camEstados[id];
        if (!def) online++;
        const card = el('div', 'card-mobile clicavel' + (def ? ' alerta' : ''));
        card.appendChild(el('h4', '', '📷 CAM ' + id.slice(3) + ' · ' + nome));
        card.appendChild(el('p', 'status-texto', def ? '⚠ ' + DEFEITO[def] : '✅ Online'));
        card.onclick = () => { ir('cameras'); trocarCam(id); };
        box.appendChild(card);
    });
    $('ui-cams').textContent = 'Câmeras: ' + online + '/5';
}

/* ================= HISTÓRICO ================= */
const COR_HIST = { ok: 'ok', alerta: 'alerta', ia: 'aviso', info: 'dim' };

async function carregarHistorico() {
    const r = await fetch('/api/historico').then(x => x.json()).catch(() => ({}));
    if (!r.sucesso) return;
    const box = $('hist-lista');
    box.innerHTML = '';
    if (!r.eventos.length) box.appendChild(el('p', 'dim', 'Nenhum evento ainda.'));
    r.eventos.forEach(e => box.appendChild(el('p', COR_HIST[e.tipo] || 'dim', '[' + e.hora + '] ' + e.texto)));
    $('ui-eventos').textContent = r.eventos.length + ' eventos';
}

/* ================= IA MAKER (CHAT) ================= */
const chatBox = () => $('chat-mensagens');

function adicionarMensagemChat(texto, tipo) {
    const msg = el('div', 'msg ' + tipo, texto);
    chatBox().appendChild(msg);
    chatBox().scrollTop = chatBox().scrollHeight;
    return msg;
}

function mostrarChips(lista) {
    const box = $('chat-chips');
    box.innerHTML = '';
    (lista || []).slice(0, 5).forEach(t => {
        const b = el('button', 'chip', t);
        b.type = 'button';
        b.onclick = () => enviarTexto(t);
        box.appendChild(b);
    });
}

function chatLog(texto, tipo, chips) {  // mensagem da IA vinda de outras partes do app
    adicionarMensagemChat(texto, tipo);
    if (chips) mostrarChips(chips);
}

function abrirChat() {
    if (!chatIniciado) {
        chatIniciado = true;
        const nome = $('nome-usuario').textContent.split(' ')[0];
        adicionarMensagemChat('Olá, ' + nome + '! Sou o assistente virtual guiado. Posso verificar o sistema, mostrar as câmeras e controlar a casa. Escreva um comando ou toque numa sugestão.', 'bot');
        mostrarChips(['Verificar o sistema', 'Ligar a luz da sala', 'Ver a câmera da cozinha', 'Status', 'Ajuda']);
    }
    $('input-texto-ia').focus({ preventScroll: true });
}

function verificarEnter(e) { if (e.key === 'Enter') enviarTextoLivre(); }

function enviarTextoLivre() {
    const campo = $('input-texto-ia');
    const texto = campo.value.trim();
    if (!texto) return;
    campo.value = '';
    enviarTexto(texto);
}

async function enviarTexto(texto) {
    adicionarMensagemChat(texto, 'user');
    const dig = adicionarMensagemChat('•••', 'bot digitando');
    let r;
    try { r = await post('/api/chatbot', { texto }); } catch (_) { r = { mensagem: 'Não consegui falar com o servidor.', tipo_css: 'bot-erro' }; }
    await dormir(300);
    dig.remove();
    adicionarMensagemChat(r.mensagem, r.tipo_css || 'bot');
    if (r.sugestoes) mostrarChips(r.sugestoes);
    if (r.acao) executarAcao(r.acao);
}

function executarAcao(a) {
    if (a.tipo === 'verificar') verificarSistema();
    else if (a.tipo === 'corrigir') corrigirProblema();
    else if (a.tipo === 'camera') { ir('cameras'); trocarCam(a.cam); }
    else if (a.tipo === 'tela') ir(a.tela);
    else if (a.tipo === 'atualizar') { carregarCasa(); poll(); }
}

/* ================= AVISOS: TOAST E IA ================= */
function mostrarToast(titulo, texto, botoes, amarelo) {
    const t = $('toast');
    t.innerHTML = '';
    t.className = 'toast-app' + (amarelo ? ' amarelo' : '');
    t.appendChild(el('strong', '', titulo));
    t.appendChild(el('p', '', texto));
    const linhaB = el('div', 'toast-btns');
    botoes.forEach(([rotulo, fn, cls]) => {
        const b = el('button', 'btn-app ' + (cls || ''), rotulo);
        b.type = 'button'; b.onclick = fn;
        linhaB.appendChild(b);
    });
    t.appendChild(linhaB);
}

function fecharToast() { $('toast').classList.add('hidden'); }

function notificarSistema(titulo, corpo) {
    if ('Notification' in window && Notification.permission === 'granted') new Notification(titulo, { body: corpo });
    if (navigator.vibrate) navigator.vibrate([300, 150, 300]);
}

function notificarInvasor() {
    mostrarToast('🚨 ALERTA DE SEGURANÇA', 'Uma pessoa estranha está na sua propriedade.',
        [['Abrir câmeras', () => ir('cameras'), 'perigo'], ['Fechar', fecharToast, 'sec']]);
    notificarSistema('Alerta de segurança', 'Uma pessoa estranha está na sua propriedade.');
}

function notificarProblema() {
    mostrarToast('⚠️ ALERTA AUTOMÁTICO', 'O sistema detectou uma anomalia. Faça uma verificação para descobrir o que é.',
        [['Verificar agora', () => { fecharToast(); verificarSistema(); }], ['Depois', fecharToast, 'sec']], true);
    notificarSistema('Anomalia detectada', 'Faça uma verificação do sistema.');
    chatLog('⚠️ Detectei uma anomalia no sistema. Quer que eu faça uma verificação?', 'bot-alerta', ['Verificar o sistema', 'Status']);
}

let avisoAtual = null, avisoTimer = null;

function mostrarAviso(a) {
    avisoAtual = a;
    $('aviso-resumo').textContent = 'A IA encontrou uma vulnerabilidade e já corrigiu: ' + a.titulo + '.';
    $('aviso-detalhes').innerHTML = '';
    $('aviso-detalhes').classList.add('hidden');
    $('aviso-btn').classList.remove('hidden');
    $('aviso-ia').classList.remove('hidden');
    clearTimeout(avisoTimer);
    avisoTimer = setTimeout(fecharAviso, 15000);
}

function verDetalhesAviso() {
    clearTimeout(avisoTimer);  // com os detalhes abertos, o aviso fica até você fechar
    const a = avisoAtual, d = $('aviso-detalhes');
    d.innerHTML = '';
    [['Onde', a.onde], ['Risco', a.risco], ['O que foi encontrado', a.achado]].forEach(([k, v]) => {
        const p = el('p');
        p.appendChild(el('b', '', k + ': '));
        p.appendChild(document.createTextNode(v));
        d.appendChild(p);
    });
    d.appendChild(el('p', 'titulo', 'O QUE A IA FEZ:'));
    a.passos.forEach(s => d.appendChild(el('p', 'ok', s)));
    d.appendChild(el('p', 'ok', 'Status: CORRIGIDO às ' + a.hora));
    d.classList.remove('hidden');
    $('aviso-btn').classList.add('hidden');
}

function fecharAviso() { clearTimeout(avisoTimer); $('aviso-ia').classList.add('hidden'); }

/* ================= NOME DO USUÁRIO ================= */
function editarNome() {
    ir('inicio');
    const atual = $('nome-usuario').textContent;
    $('nome-input').value = ['Morador', 'Mestre Visitante'].includes(atual) ? '' : atual;
    $('nome-msg').classList.add('hidden');
    $('nome-form').classList.remove('hidden');
    $('nome-input').focus();
}

function cancelarNome() { $('nome-form').classList.add('hidden'); }

async function salvarNome(e) {
    e.preventDefault();
    const r = await post('/api/perfil/nome', { nome: $('nome-input').value });
    if (r.sucesso) { $('nome-usuario').textContent = r.nome; cancelarNome(); }
    else { $('nome-msg').textContent = r.mensagem || 'Não foi possível salvar o nome.'; $('nome-msg').className = 'msg-box error'; }
}

/* ================= ATALHOS DE APRESENTAÇÃO ================= */
const ATALHOS = { F1: 'invasao', F2: 'aviso', F3: 'problema', F4: 'camera' };

document.addEventListener('keydown', async e => {
    if (e.key === 'F8') { e.preventDefault(); $('atalhos').classList.toggle('hidden'); return; }
    const acao = ATALHOS[e.key];
    if (!acao || e.repeat) return;
    e.preventDefault();  // evita a ajuda do navegador (F1)
    let r = {};
    try { r = await post('/api/demo/' + acao); } catch (_) { /* sem resposta */ }
    poll();  // invasão e aviso da IA aparecem na hora
    if (r.sucesso && r.problema) {  // F3 e F4: o problema aparece na verificação
        if (ocupado) alertaForcado = alertaForcado || r.problema;  // verificação rodando: o alerta entra nela
        else verificarSistema();                                    // senão, ela começa e já encontra o problema
    }
});

/* ================= ATUALIZAÇÃO CONSTANTE ================= */
async function poll() {
    const r = await fetch('/api/status').then(x => x.json()).catch(() => ({}));
    if (!r.sucesso) return;
    camEstados = r.estados; camLuzes = r.luzes; camAr = r.ar; problemaAtivo = r.problema; surgiu = r.surgiu; proximoEm = r.proximo_em;
    if (problemaAtivo) verificado = true;
    const antes = invAtual;
    if (!animando) invAtual = r.invasor;
    if (invAtual && !antes) notificarInvasor();
    if (r.novo_problema && !invAtual && painelAtual !== 'cameras') notificarProblema();
    else if (r.novo_problema && painelAtual === 'cameras') chatLog('⚠️ Detectei uma anomalia no sistema. Quer que eu faça uma verificação?', 'bot-alerta', ['Verificar o sistema', 'Status']);
    if (r.aviso && !invAtual) mostrarAviso(r.aviso);
    if (!invAtual && !r.novo_problema && !$('toast').classList.contains('amarelo')) fecharToast();
    atualizarStatus();
    desenharListaCams();
    if (camAberta) atualizarPainelCam();
    if (painelAtual === 'historico') carregarHistorico();
}

montarSeletor();
carregarCasa();
desenharListaCams();
atualizarStatus();
setInterval(poll, 2000);
setInterval(() => { if (proximoEm > 0 && !ocupado) { proximoEm--; atualizarStatus(); } }, 1000);  // contagem regressiva
poll();
