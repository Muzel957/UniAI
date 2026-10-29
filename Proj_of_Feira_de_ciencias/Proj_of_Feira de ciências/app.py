from flask import Flask, render_template, request, jsonify, session
import hmac
import json
import os
import random
import re
import secrets
import threading
import time
import unicodedata
import uuid

from flask import Response
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

try:  # lê o arquivo .env (só no seu computador; no Render as variáveis vêm do painel Environment)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:  # Argon2id: o algoritmo de senhas mais recomendado hoje. Sem a biblioteca, usa scrypt (Werkzeug).
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError
    _ARGON = PasswordHasher()
except ImportError:
    _ARGON = None
from pixel import CAMERAS, COMODO_CAM, info_policia, quadro_policia, renderizar

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # os .json ficam ao lado do app.py

# ---- ambiente: tudo que é sensível vem de variáveis de ambiente (.env no seu PC, Environment no Render) ----
EM_PRODUCAO = os.environ.get("RENDER") == "true" or os.environ.get("PRODUCAO") == "1"
PERMITIR_CADASTRO = os.environ.get("PERMITIR_CADASTRO", "1") != "0"  # 0 = só convidado e conta de demonstração

# Edição fácil do site: fora do Render, o Flask relê os HTML e os arquivos de static/ a cada atualização da página
# (salvar e apertar F5). Mudanças no app.py ou no pixel.py ainda pedem reinício.
app.config["TEMPLATES_AUTO_RELOAD"] = not EM_PRODUCAO
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

_chave = os.environ.get("SECRET_KEY")
if not _chave:
    if EM_PRODUCAO:  # sem chave fixa as sessões quebram e a segurança some: melhor nem ligar
        raise RuntimeError("Defina a variável de ambiente SECRET_KEY (no Render: Environment > Add Environment Variable).")
    print("[AVISO] SECRET_KEY não definida: usando uma chave temporária (as sessões reiniciam junto com o servidor).")
app.secret_key = _chave or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,       # o JavaScript da página não consegue ler o cookie da sessão
    SESSION_COOKIE_SAMESITE="Lax",      # o cookie não vai em pedidos vindos de outros sites (protege contra CSRF)
    SESSION_COOKIE_SECURE=EM_PRODUCAO,  # no servidor, o cookie só trafega por HTTPS
    MAX_CONTENT_LENGTH=32 * 1024,       # recusa pedidos gigantes
)
if EM_PRODUCAO:  # o Render fica na frente do site: confia no IP e no HTTPS que ele informa
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

ARQUIVO_DADOS = os.path.join(BASE_DIR, "usuario.json")
TRAVA = threading.RLock()  # um pedido de cada vez mexe nos arquivos .json

SENHAS_PROIBIDAS = ["123456", "senha123", "qwerty", "admin"]
SENHA_MIN, SENHA_MAX = 8, 128


def hash_senha(senha):
    """Nunca se guarda a senha: só o hash (Argon2id; se a biblioteca faltar, scrypt do Werkzeug)."""
    if _ARGON:
        try:
            return _ARGON.hash(senha)
        except Exception:
            pass
    return generate_password_hash(senha)


def _ja_e_hash(g):
    return isinstance(g, str) and g.startswith(("$argon2", "scrypt:", "pbkdf2:"))


def verificar_senha(guardada, senha):
    """Devolve (senha_certa, precisa_atualizar_o_hash)."""
    guardada = str(guardada)
    if guardada.startswith("$argon2"):
        if not _ARGON:
            return False, False
        try:
            _ARGON.verify(guardada, senha)
            return True, _ARGON.check_needs_rehash(guardada)
        except (VerificationError, InvalidHashError):
            return False, False
    if guardada.startswith(("scrypt:", "pbkdf2:")):
        ok = check_password_hash(guardada, senha)
        return ok, ok and _ARGON is not None  # sobe para Argon2 quando disponível
    ok = hmac.compare_digest(guardada.encode(), senha.encode())  # conta antiga, em texto puro
    return ok, ok


HASH_FALSO = hash_senha("senha-falsa")  # gasta o mesmo tempo quando o e-mail não existe


def carregar_dados():
    """Carrega todos os utilizadores guardados no ficheiro JSON."""
    if os.path.exists(ARQUIVO_DADOS):
        try:
            with open(ARQUIVO_DADOS, "r", encoding="utf-8") as f:
                dados = json.load(f)
                # Suporte para formato antigo (objeto único) e novo (dicionário de contas)
                if isinstance(dados, dict) and "email" in dados and "senha" in dados:
                    return {dados["email"]: dados["senha"]}
                elif isinstance(dados, dict):
                    return dados
        except Exception:
            return {}
    return {}


def gravar_json(caminho, dados, **opcoes):
    """Grava o arquivo inteiro de uma vez (arquivo temporário + troca), para nunca ficar pela metade."""
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, **opcoes)
    os.replace(tmp, caminho)
    try:
        os.chmod(caminho, 0o600)  # só o dono do arquivo lê (no Windows é ignorado)
    except OSError:
        pass


def salvar_usuario(email, hash_ou_senha):
    """Guarda ou atualiza uma conta no JSON sem apagar as existentes (o valor deve ser um hash)."""
    with TRAVA:
        dados = carregar_dados()
        dados[email] = hash_ou_senha
        gravar_json(ARQUIVO_DADOS, dados, indent=4)


def migrar_senhas_antigas():
    """Ao ligar o servidor, troca qualquer senha ainda em texto puro por hash, sem esperar o login da pessoa."""
    with TRAVA:
        dados = carregar_dados()
        trocadas = 0
        for email, g in list(dados.items()):
            if isinstance(g, str) and g and not _ja_e_hash(g):
                dados[email] = hash_senha(g)
                trocadas += 1
        if trocadas:
            gravar_json(ARQUIVO_DADOS, dados, indent=4)
            print(f"[SEGURANÇA] {trocadas} senha(s) em texto puro foram convertidas em hash.")


def garantir_conta_demo():
    """Conta de demonstração opcional, vinda das variáveis CONTA_DEMO_EMAIL e CONTA_DEMO_SENHA.
    No Render grátis os arquivos somem a cada reinício; esta conta é recriada sozinha, sem ir para o GitHub."""
    email, senha = os.environ.get("CONTA_DEMO_EMAIL", "").strip(), os.environ.get("CONTA_DEMO_SENHA", "")
    if not email or not senha:
        return
    with TRAVA:
        atual = carregar_dados().get(email)
        if not atual or not verificar_senha(atual, senha)[0]:
            salvar_usuario(email, hash_senha(senha))
            print("[INFO] Conta de demonstração criada a partir das variáveis de ambiente.")


migrar_senhas_antigas()
garantir_conta_demo()


# ============ PROTEÇÕES: tentativas de login e cabeçalhos de segurança ============
JANELA_FALHAS = 600    # 10 minutos
MAX_FALHAS_CONTA = 5   # senhas erradas por (IP + e-mail)
MAX_FALHAS_IP = 25     # senhas erradas por IP
MAX_CADASTROS_IP = 10  # contas novas por IP, por hora
_FALHAS, _CADASTROS = {}, {}


def _recentes(tabela, chave, janela):
    agora = time.time()
    lista = [t for t in tabela.get(chave, []) if agora - t < janela]
    if lista:
        tabela[chave] = lista
    else:
        tabela.pop(chave, None)
    if len(tabela) > 5000:  # não deixa a memória crescer sem limite
        for k in list(tabela)[:1000]:
            tabela.pop(k, None)
    return lista


def espera_login(email):
    """Segundos até poder tentar de novo (0 = liberado)."""
    ip, agora = request.remote_addr or "?", time.time()
    a = _recentes(_FALHAS, ("c", ip, email.lower()), JANELA_FALHAS)
    b = _recentes(_FALHAS, ("i", ip), JANELA_FALHAS)
    esperas = [0]
    if len(a) >= MAX_FALHAS_CONTA:
        esperas.append(JANELA_FALHAS - (agora - a[len(a) - MAX_FALHAS_CONTA]))
    if len(b) >= MAX_FALHAS_IP:
        esperas.append(JANELA_FALHAS - (agora - b[len(b) - MAX_FALHAS_IP]))
    return int(max(esperas)) + 1 if max(esperas) > 0 else 0


def registrar_falha_login(email):
    ip = request.remote_addr or "?"
    for chave in (("c", ip, email.lower()), ("i", ip)):
        _FALHAS.setdefault(chave, []).append(time.time())


def limpar_falhas_login(email):
    _FALHAS.pop(("c", request.remote_addr or "?", email.lower()), None)


@app.after_request
def cabecalhos_de_seguranca(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")  # o jogo é do mesmo site; outros sites não podem embutir
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if resp.mimetype == "application/json":
        resp.headers["Cache-Control"] = "no-store"  # respostas da API não ficam guardadas no navegador
    if EM_PRODUCAO:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


# ============ PÁGINAS DO SITE ============
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/seguranca.html")
def seguranca():
    user_logged = session.get("user")
    return render_template("seguranca.html", user=bool(user_logged), nome=nome_de(user_logged),
                           cadastro_aberto=PERMITIR_CADASTRO)


@app.route("/jogo.html")
def jogo():
    return render_template("jogo.html")


@app.route("/api/cadastrar", methods=["POST"])
def cadastrar():
    if not PERMITIR_CADASTRO:
        return jsonify({"sucesso": False, "mensagem": "O cadastro está desativado. Use o Acesso Mestre ou entre com uma conta existente."}), 403
    if len(_recentes(_CADASTROS, request.remote_addr or "?", 3600)) >= MAX_CADASTROS_IP:
        return jsonify({"sucesso": False, "mensagem": "Muitos cadastros deste aparelho. Tente de novo mais tarde."}), 429
    data = request.json or {}
    email = str(data.get("email", "")).strip()
    senha = str(data.get("senha", ""))

    # Validações do E-mail (Lógica do script original)
    if len(email) < 11:
        return jsonify({"sucesso": False, "mensagem": "E-mail muito curto. Use no mínimo 11 caracteres."}), 400
    if "@" not in email or "." not in email:
        return jsonify({"sucesso": False, "mensagem": "E-mail inválido! Falta '@' ou '.'."}), 400

    # Validações da Senha (Lógica do script original)
    if len(email) > 120:
        return jsonify({"sucesso": False, "mensagem": "E-mail muito longo."}), 400
    if len(senha) < SENHA_MIN:
        return jsonify({"sucesso": False, "mensagem": f"Senha curta! Digite pelo menos {SENHA_MIN} caracteres."}), 400
    if len(senha) > SENHA_MAX:
        return jsonify({"sucesso": False, "mensagem": f"Senha longa demais (máximo {SENHA_MAX} caracteres)."}), 400
    if senha.lower() in SENHAS_PROIBIDAS:
        return jsonify({"sucesso": False, "mensagem": "Essa senha é muito comum, use uma mais forte!"}), 400

    maiuscula = any(c.isupper() for c in senha)
    minuscula = any(c.islower() for c in senha)

    if not maiuscula and not minuscula:
        return jsonify({"sucesso": False, "mensagem": "Falta pelo menos uma letra maiúscula E uma minúscula."}), 400
    elif not maiuscula:
        return jsonify({"sucesso": False, "mensagem": "Falta pelo menos uma letra maiúscula."}), 400
    elif not minuscula:
        return jsonify({"sucesso": False, "mensagem": "Falta pelo menos uma letra minúscula."}), 400

    if email in carregar_dados():  # impede trocar a senha de uma conta que já existe
        return jsonify({"sucesso": False, "mensagem": "Este e-mail já está cadastrado. Use a aba Entrar."}), 400

    salvar_usuario(email, hash_senha(senha))
    _CADASTROS.setdefault(request.remote_addr or "?", []).append(time.time())
    iniciar_sessao(email, "Conta criada")
    return jsonify({"sucesso": True, "mensagem": "Conta criada e guardada com sucesso!"})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    email = str(data.get("email", "")).strip()
    senha = str(data.get("senha", ""))

    espera = espera_login(email)
    if espera:  # muitas senhas erradas seguidas: segura a pessoa (e quem tenta adivinhar) por um tempo
        return jsonify({"sucesso": False, "mensagem": f"Muitas tentativas erradas. Tente de novo em {max(1, espera // 60)} min."}), 429

    guardada = carregar_dados().get(email, "")
    ok = False
    if len(email) > 120 or len(senha) > SENHA_MAX:
        pass  # tamanho absurdo: nem gasta tempo calculando
    elif guardada:
        ok, atualizar = verificar_senha(guardada, senha)
        if ok and atualizar:
            salvar_usuario(email, hash_senha(senha))  # troca um hash antigo (ou texto puro) por um novo
    else:
        verificar_senha(HASH_FALSO, senha)  # mesmo tempo de resposta: não revela se o e-mail existe

    if not ok:
        registrar_falha_login(email)
        return jsonify({"sucesso": False, "mensagem": "E-mail ou senha incorretos."}), 400

    limpar_falhas_login(email)
    iniciar_sessao(email, "Sessão iniciada")
    return jsonify({"sucesso": True, "mensagem": "Login realizado com sucesso!"})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"sucesso": True})


@app.route("/api/login_mestre", methods=["POST"])
def login_mestre():
    """Acesso de convidado: cada visitante tem a sua própria casa, guardada só na memória do servidor."""
    session.clear()
    session["gid"] = secrets.token_hex(4)
    iniciar_sessao(MESTRE, "Acesso Mestre (convidado)")
    return jsonify({"sucesso": True, "mensagem": "Acesso Mestre concedido!"})


# ============ SESSÃO, HISTÓRICO E PROBLEMAS AUTOMÁTICOS ============
MESTRE = "Mestre Visitante"
INTERVALO_PROBLEMA = 30  # a cada 30 s surge um problema fictício para o usuário resolver
HISTORICO = {}           # dono -> eventos, do mais novo para o mais antigo (só na memória do servidor)
CASA_VISITANTES = {}     # casa de cada convidado (não vai para o casa.json)


def dono():
    """Chave de armazenamento do usuário: o e-mail, ou um código próprio para cada convidado."""
    u = session.get("user")
    return f"visitante:{session.get('gid', '0')}" if u == MESTRE else u


def registrar(tipo, texto):
    """tipo: ok, alerta, ia ou info (define a cor na tela)."""
    if not session.get("user"):
        return
    h = HISTORICO.setdefault(dono(), [])
    h.insert(0, {"hora": time.strftime("%H:%M:%S"), "tipo": tipo, "texto": texto})
    del h[60:]


def iniciar_sessao(email, motivo):
    session["user"] = email
    for k in ("problema", "oculto", "pendente", "demo_scan", "invasor", "escaneando_ate"):
        session.pop(k, None)
    session["prox_problema"] = time.time() + INTERVALO_PROBLEMA
    registrar("info", f"{motivo}. Monitoramento ativo.")


def sortear_problema():
    ultimo = session.get("ultimo_problema")
    idx = random.choice([i for i in range(len(PROBLEMAS)) if i != ultimo])
    session["ultimo_problema"] = idx
    return idx


# ============ CASA INTELIGENTE ============
ARQUIVO_CASA = os.path.join(BASE_DIR, "casa.json")
TIPOS = ("luz", "ar", "outro")
PADRAO = [
    {"nome": "Luz da entrada", "comodo": "entrada", "tipo": "luz", "ligado": True},
    {"nome": "Luz da sala", "comodo": "sala", "tipo": "luz", "ligado": True},
    {"nome": "Ar-condicionado", "comodo": "sala", "tipo": "ar", "ligado": False},
    {"nome": "Luz da cozinha", "comodo": "cozinha", "tipo": "luz", "ligado": False},
    {"nome": "Luz da garagem", "comodo": "garagem", "tipo": "luz", "ligado": False},
    {"nome": "Luz do quintal", "comodo": "quintal", "tipo": "luz", "ligado": False},
]

# (chave da verificação, resultado no relatório, título, passos da correção, resultado final, câmera, defeito)
PROBLEMAS = [
    ("fechadura", "DESTRANCADA há 22 min", "Fechadura da porta da frente destrancada",
     ["Enviando comando LOCK para 192.168.0.21", "Aguardando confirmação do sensor de tranca",
      "Renovando a chave digital do aplicativo", "Registrando o evento no log de segurança"],
     "Fechadura trancada e chave digital renovada.", None, None),
    ("janela", "JANELA DO QUARTO ABERTA", "Janela do quarto aberta com o alarme armado",
     ["Notificando os moradores", "Reiniciando o sensor magnético da janela",
      "Recalibrando a zona do quarto", "Rearmando o alarme"],
     "Janela monitorada e alarme rearmado.", None, None),
    ("wifi", "1 NÃO AUTORIZADO: 192.168.0.87, MAC 3C:71:BF:2A:90:11", "Aparelho desconhecido conectado ao Wi-Fi",
     ["Isolando 192.168.0.87 na rede de convidados", "Bloqueando o MAC 3C:71:BF:2A:90:11",
      "Trocando a senha do Wi-Fi", "Reconectando os aparelhos autorizados"],
     "Aparelho removido e rede protegida.", None, None),
    ("login", "37 FALHAS vindas de 203.0.113.45", "Tentativas de login suspeitas no sistema",
     ["Bloqueando o IP 203.0.113.45", "Exigindo confirmação em duas etapas",
      "Encerrando sessões antigas", "Gerando relatório do incidente"],
     "Acesso protegido com confirmação em duas etapas.", None, None),
    ("campainha", "DESATUALIZADA, v1.9.4 tem vulnerabilidade conhecida", "Campainha inteligente com firmware vulnerável",
     ["Baixando a atualização oficial v2.1.0", "Conferindo a assinatura do arquivo",
      "Instalando a atualização", "Reiniciando a campainha"],
     "Campainha atualizada para v2.1.0.", None, None),
    ("sirene", "BATERIA EM 8%", "Bateria da sirene quase no fim",
     ["Ativando o modo de economia", "Passando a sirene para a energia da tomada",
      "Agendando a troca da bateria", "Testando a sirene"],
     "Sirene funcionando e troca de bateria agendada.", None, None),
    ("cam3", "SEM SINAL, tempo esgotado em 5000 ms", "Câmera 3 da cozinha sem sinal",
     ["Reiniciando o stream da CAM 3", "Reconectando a câmera ao Wi-Fi",
      "Renegociando o sinal de vídeo", "Testando a imagem"],
     "CAM 3 online novamente.", "cam3", "sem_sinal"),
    ("cam4", "IMAGEM DEGRADADA, nitidez de 12%", "Câmera 4 da garagem com a lente suja",
     ["Ligando o desembaçador da lente", "Recalibrando o foco automático",
      "Ajustando o contraste", "Testando a imagem"],
     "CAM 4 com imagem nítida.", "cam4", "lente_suja"),
    ("cam5", "SEM ILUMINAÇÃO, luminosidade de 2%", "Câmera 5 do quintal sem luz suficiente",
     ["Ligando a luz do jardim", "Ativando o infravermelho da CAM 5",
      "Ajustando a exposição", "Testando a imagem"],
     "CAM 5 enxergando bem no escuro.", "cam5", "escuro"),
    ("cam1", "QUADRO CONGELADO, último quadro há 94 s", "Câmera 1 da entrada travada",
     ["Enviando comando de reinício para a CAM 1", "Aguardando o firmware iniciar",
      "Reabrindo o stream de vídeo", "Testando a imagem"],
     "CAM 1 funcionando normalmente.", "cam1", "congelada"),
]
# avisos periódicos: a IA encontra e corrige vulnerabilidades sozinha
# (título, onde, risco, o que foi encontrado, o que a IA fez)
VULNERABILIDADES = [
    ("Porta aberta no roteador", "Roteador", "ALTO",
     "A porta 23, usada pelo Telnet, estava aberta para a internet e permitia tentativas de acesso remoto.",
     ["Fechou a porta 23 no firewall", "Desativou o serviço Telnet", "Rodou uma nova varredura no roteador"]),
    ("Senha de fábrica na câmera", "CAM 2 da sala", "ALTO",
     "A câmera ainda usava a senha padrão do fabricante, conhecida por invasores.",
     ["Gerou uma senha forte e única", "Aplicou a senha na câmera e no aplicativo", "Guardou a senha em cofre criptografado"]),
    ("Firmware desatualizado", "Hub central", "MÉDIO",
     "O hub estava na versão 3.2.0, que tem uma falha de segurança conhecida.",
     ["Baixou a versão 3.2.1 do site oficial", "Conferiu a assinatura do arquivo", "Instalou e reiniciou o hub"]),
    ("Conexão sem criptografia", "Fechadura da porta dos fundos", "MÉDIO",
     "A fechadura enviava comandos sem criptografia, e alguém na rede poderia ler esses dados.",
     ["Ativou a criptografia TLS", "Renovou as chaves de comunicação", "Testou a abertura e o travamento"]),
    ("Sessão antiga ativa", "Aplicativo da casa", "BAIXO",
     "Um celular sem uso há 40 dias continuava conectado à sua conta.",
     ["Encerrou a sessão do aparelho antigo", "Pediu novo login nos demais aparelhos", "Registrou o evento no histórico"]),
    ("Certificado de segurança vencendo", "Servidor de vídeo", "BAIXO",
     "O certificado que protege o vídeo das câmeras venceria em 3 dias.",
     ["Emitiu um novo certificado", "Instalou no servidor de vídeo", "Confirmou a conexão segura das 5 câmeras"]),
]
VIZINHOS = {"quintal": ["garagem", "sala"], "garagem": ["quintal", "cozinha"], "cozinha": ["garagem", "sala"],
            "sala": ["quintal", "cozinha", "entrada"], "entrada": ["sala"]}


def logado():
    return bool(session.get("user"))


# ---------- perfil: o nome aparece na tela no lugar do e-mail ----------
ARQUIVO_PERFIL = os.path.join(BASE_DIR, "perfil.json")
NOME_PADRAO = "Morador"
NOME_VALIDO = re.compile(r"^[\w .'-]{1,24}$")  # letras, números, espaço, ponto, apóstrofo e hífen (sem @)


def perfil_todos():
    if os.path.exists(ARQUIVO_PERFIL):
        try:
            with open(ARQUIVO_PERFIL, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def nome_de(email):
    if email == MESTRE:
        return session.get("nome_visitante") or MESTRE
    return perfil_todos().get(email) or NOME_PADRAO


@app.route("/api/perfil/nome", methods=["POST"])
def perfil_nome():
    if not logado():
        return jsonify({"sucesso": False}), 401
    nome = " ".join(str((request.json or {}).get("nome", "")).split())
    if not NOME_VALIDO.match(nome):
        return jsonify({"sucesso": False, "mensagem": "Use de 1 a 24 letras, números ou espaços. Não coloque e-mail."}), 400
    if session["user"] == MESTRE:
        session["nome_visitante"] = nome
        return jsonify({"sucesso": True, "nome": nome})
    with TRAVA:
        todos = perfil_todos()
        todos[session["user"]] = nome
        gravar_json(ARQUIVO_PERFIL, todos, indent=2, ensure_ascii=False)
    return jsonify({"sucesso": True, "nome": nome})


# ---------- dispositivos da casa (guardados por usuário) ----------
def casa_todos():
    if os.path.exists(ARQUIVO_CASA):
        try:
            with open(ARQUIVO_CASA, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def casa_do_usuario(email):
    if email.startswith("visitante:"):
        if email not in CASA_VISITANTES:
            CASA_VISITANTES[email] = [dict(d, id=f"d{i}") for i, d in enumerate(PADRAO, 1)]
        return CASA_VISITANTES[email]
    todos = casa_todos()
    if email in todos:
        return todos[email]
    return [dict(d, id=f"d{i}") for i, d in enumerate(PADRAO, 1)]


def casa_salvar(email, lista):
    if email.startswith("visitante:"):
        CASA_VISITANTES[email] = lista
        return
    with TRAVA:
        todos = casa_todos()
        todos[email] = lista
        gravar_json(ARQUIVO_CASA, todos, indent=2, ensure_ascii=False)


def luzes(email):
    """Cada câmera sabe se a luz do cômodo está ligada."""
    lista = casa_do_usuario(email)
    return {cam: any(d["ligado"] for d in lista if d["comodo"] == c and d["tipo"] == "luz")
            for c, cam in COMODO_CAM.items()}


def ar_estados(email):
    """Por câmera: 0 = sem ar-condicionado no cômodo, 1 = desligado, 2 = ligado."""
    lista = casa_do_usuario(email)
    res = {}
    for c, cam in COMODO_CAM.items():
        ars = [d for d in lista if d["comodo"] == c and d["tipo"] == "ar"]
        res[cam] = 0 if not ars else (2 if any(d["ligado"] for d in ars) else 1)
    return res


@app.route("/api/casa")
def casa_listar():
    if not logado():
        return jsonify({"sucesso": False}), 401
    return jsonify({"sucesso": True, "dispositivos": casa_do_usuario(dono())})


@app.route("/api/casa/alternar", methods=["POST"])
def casa_alternar():
    if not logado():
        return jsonify({"sucesso": False}), 401
    lista = casa_do_usuario(dono())
    for d in lista:
        if d["id"] == (request.json or {}).get("id"):
            d["ligado"] = not d["ligado"]
            casa_salvar(dono(), lista)
            registrar("info", f"{d['nome']} ({d['comodo']}): {'ligado' if d['ligado'] else 'desligado'}")
            return jsonify({"sucesso": True, "dispositivos": lista})
    return jsonify({"sucesso": False, "mensagem": "Dispositivo não encontrado."}), 404


@app.route("/api/casa/adicionar", methods=["POST"])
def casa_adicionar():
    if not logado():
        return jsonify({"sucesso": False}), 401
    data = request.json or {}
    nome = str(data.get("nome", "")).strip()[:30]
    comodo, tipo = data.get("comodo"), data.get("tipo", "outro")
    lista = casa_do_usuario(dono())
    if not nome:
        return jsonify({"sucesso": False, "mensagem": "Digite um nome para o dispositivo."}), 400
    if comodo not in COMODO_CAM or tipo not in TIPOS:
        return jsonify({"sucesso": False, "mensagem": "Cômodo ou tipo inválido."}), 400
    if len(lista) >= 30:
        return jsonify({"sucesso": False, "mensagem": "Limite de 30 dispositivos atingido."}), 400
    lista.append({"id": uuid.uuid4().hex[:8], "nome": nome, "comodo": comodo, "tipo": tipo, "ligado": False})
    casa_salvar(dono(), lista)
    registrar("info", f"Dispositivo adicionado: {nome} ({comodo})")
    return jsonify({"sucesso": True, "dispositivos": lista, "mensagem": f"Dispositivo '{nome}' adicionado."})


@app.route("/api/casa/remover", methods=["POST"])
def casa_remover():
    if not logado():
        return jsonify({"sucesso": False}), 401
    antiga = casa_do_usuario(dono())
    lista = [d for d in antiga if d["id"] != (request.json or {}).get("id")]
    for d in antiga:
        if d not in lista:
            registrar("info", f"Dispositivo removido: {d['nome']} ({d['comodo']})")
    casa_salvar(dono(), lista)
    return jsonify({"sucesso": True, "dispositivos": lista})


# ---------- modo apresentação: atalhos que forçam eventos (desligue com MODO_DEMO=0) ----------
MODO_DEMO = os.environ.get("MODO_DEMO", "1") != "0"


@app.route("/api/demo/<acao>", methods=["POST"])
def demo(acao):
    if not MODO_DEMO:
        return jsonify({"sucesso": False, "mensagem": "Modo de apresentação desativado."}), 403
    if not logado():
        return jsonify({"sucesso": False}), 401
    if acao == "invasao":
        session["invasor"] = {"comodo": "quintal"}
        registrar("alerta", "Pessoa estranha detectada na propriedade.")
    elif acao == "aviso":
        session["forcar_aviso"] = True
    elif acao in ("problema", "camera"):  # F3: problema qualquer, F4: defeito em uma câmera
        ativo = session.get("problema")
        if ativo is None:
            ativo = session.get("oculto")  # já existe um problema surgindo sozinho? a verificação encontra esse
        if ativo is None:
            ativo = random.choice([i for i, p in enumerate(PROBLEMAS) if acao == "problema" or p[5]])
            session["demo_scan"] = ativo  # a próxima verificação encontra
            session["pendente"] = ativo   # e uma verificação em andamento também
        p = PROBLEMAS[ativo]
        return jsonify({"sucesso": True, "problema": {"titulo": p[2], "resultado": p[1]}})
    else:
        return jsonify({"sucesso": False, "mensagem": "Atalho desconhecido."}), 404
    return jsonify({"sucesso": True})


# ---------- verificação do sistema de segurança ----------
@app.route("/api/varredura", methods=["POST"])
def varredura():
    if not logado():
        return jsonify({"sucesso": False}), 401
    ativo = session.get("problema")  # um problema não corrigido continua lá na próxima verificação
    forcado = session.pop("demo_scan", None)  # problema escolhido pelos atalhos F3 e F4
    oculto = session.get("oculto")  # problema que surgiu sozinho (a cada 30 s) e ainda não foi descoberto
    escolhido = ativo if ativo is not None else (oculto if oculto is not None else forcado)
    p = PROBLEMAS[escolhido] if escolhido is not None else None  # sem problema, o sistema está de acordo
    session["pendente"] = escolhido
    session["escaneando_ate"] = time.time() + 150  # enquanto verifica, nenhum problema novo surge
    L, r = [], random.randint

    def sec(nome):
        L.append([nome, "", "titulo"])

    def v(chave, acao, ok="OK"):
        L.append([acao, p[1], "alerta"] if p and p[0] == chave else [acao, ok, "ok"])

    sec("REDE E ROTEADOR")
    v("r1", "Conectando ao hub central 192.168.0.1", f"{r(4, 18)} ms")
    v("r2", "Testando firewall e criptografia do Wi-Fi", "firewall ativo, WPA3")
    v("r3", "Procurando portas expostas para a internet", "nenhuma porta aberta")
    v("r4", "Verificando o servidor DNS", f"resposta em {r(8, 30)} ms")
    v("wifi", "Comparando aparelhos conectados com a lista autorizada", "14 de 14 autorizados")
    sec("ACESSOS E SENHAS")
    v("login", "Tentativas de login nas últimas 24 h", "0 falhas")
    v("a2", "Política de senhas e confirmação em duas etapas", "ativas")
    v("a3", "Sessões abertas no aplicativo", f"{r(1, 3)} sessões conhecidas")
    sec("FECHADURAS E SENSORES")
    v("fechadura", "Fechadura da porta da frente 192.168.0.21", f"TRANCADA, bateria {r(70, 99)}%")
    v("s2", "Fechadura da porta dos fundos 192.168.0.22", f"TRANCADA, bateria {r(70, 99)}%")
    v("s3", "Sensores magnéticos das 3 portas", "todos fechados")
    v("janela", "Sensores magnéticos das 6 janelas", "todas fechadas")
    v("s5", "Sensor de movimento da sala", "ativo")
    v("s6", "Sensor de movimento da garagem", "ativo")
    v("s7", "Detector de fumaça da cozinha", f"normal, bateria {r(60, 99)}%")
    v("s8", "Temperatura da cozinha", f"{r(22, 27)} graus C")
    sec("ALARME")
    v("l1", "Central de alarme", "armada em modo ausente")
    v("l2", "Teste de continuidade da sirene")
    v("sirene", "Bateria da sirene", f"{r(70, 99)}%")
    v("l4", "Comunicação com a central de monitoramento", f"{r(40, 90)} ms")
    sec("CÂMERAS")
    for c, nome in CAMERAS.items():
        v(c, f"{c.replace('cam', 'CAM ')} {nome}", f"online, 1080p, {r(22, 30)} fps, sinal -{r(40, 62)} dBm")
    sec("ATUALIZAÇÕES DE FIRMWARE")
    v("f1", "Hub central", "v3.2.1, atualizado")
    v("f2", "Fechaduras inteligentes", "v2.8.0, atualizado")
    v("campainha", "Campainha inteligente", "v2.1.0, atualizado")
    v("f4", "Câmeras", "v4.0.2, atualizado")
    return jsonify({"sucesso": True, "linhas": L, "problema": p[2] if p else None})


@app.route("/api/varredura/concluir", methods=["POST"])
def varredura_concluir():
    """O problema só é 'descoberto' (e a opção de corrigir só aparece) quando a verificação termina."""
    if not logado():
        return jsonify({"sucesso": False}), 401
    pend = session.pop("pendente", None)
    session["problema"] = pend
    session.pop("demo_scan", None)
    session.pop("escaneando_ate", None)
    if pend is not None:
        session.pop("oculto", None)  # descoberto
    registrar("ok" if pend is None else "alerta",
              "Verificação concluída: nenhum problema encontrado." if pend is None
              else f"Verificação concluída: {PROBLEMAS[pend][2]}.")
    return jsonify({"sucesso": True, "problema": pend is not None, "titulo": PROBLEMAS[pend][2] if pend is not None else None})


@app.route("/api/resolver", methods=["POST"])
def resolver():
    idx = session.get("problema")
    if not logado() or idx is None:
        return jsonify({"sucesso": False, "mensagem": "Nenhum problema para corrigir. Verifique o sistema primeiro."}), 400
    session["problema"] = None
    session.pop("oculto", None)
    session["prox_problema"] = time.time() + INTERVALO_PROBLEMA  # o próximo problema surge 30 s depois
    registrar("ok", f"Problema corrigido: {PROBLEMAS[idx][2]}.")
    return jsonify({"sucesso": True, "passos": PROBLEMAS[idx][3], "mensagem": PROBLEMAS[idx][4]})


# ---------- câmeras e intruso ----------
@app.route("/api/status")
def status():
    if not logado():
        return jsonify({"sucesso": False}), 401
    agora = time.time()
    idx = session.get("problema")      # já descoberto pela verificação
    oculto = session.get("oculto")     # existe no sistema, mas ainda não foi descoberto
    novo = False
    espera = session.setdefault("prox_problema", agora + INTERVALO_PROBLEMA)
    # a cada 30 s surge um problema fictício (se não houver outro pendente nem verificação em andamento)
    if (idx is None and oculto is None and session.get("demo_scan") is None
            and agora >= espera and agora > session.get("escaneando_ate", 0)):
        oculto = sortear_problema()
        session["oculto"] = oculto
        novo = True
        registrar("alerta", "Alerta automático: o sistema detectou uma anomalia. Faça uma verificação.")
    visivel = idx if idx is not None else oculto  # defeito de câmera aparece na imagem assim que surge
    estados = {c: None for c in CAMERAS}
    if visivel is not None and PROBLEMAS[visivel][5]:
        estados[PROBLEMAS[visivel][5]] = PROBLEMAS[visivel][6]
    inv = session.get("invasor")
    if inv and random.random() < 0.55:  # depois que aparece (F1), ele anda pela casa, como no FNAF
        inv["comodo"] = random.choice(VIZINHOS[inv["comodo"]])
    session["invasor"] = inv
    aviso = None  # o aviso da IA só aparece quando o atalho F2 é usado
    if session.pop("forcar_aviso", False):
        aviso = dict(zip(("titulo", "onde", "risco", "achado", "passos"), random.choice(VULNERABILIDADES)),
                     hora=time.strftime("%H:%M"))
        registrar("ia", f"IA de segurança corrigiu uma vulnerabilidade: {aviso['titulo']}.")
    ocupado = idx is not None or oculto is not None
    return jsonify({"sucesso": True, "estados": estados, "problema": idx is not None,
                    "surgiu": oculto is not None, "novo_problema": novo,
                    "proximo_em": 0 if ocupado else max(0, int(espera - agora)),
                    "luzes": luzes(dono()), "ar": ar_estados(dono()), "aviso": aviso,
                    "invasor": inv and {"comodo": inv["comodo"], "cam": COMODO_CAM[inv["comodo"]]}})


@app.route("/api/invasor/policia", methods=["POST"])
def invasor_policia():
    inv = session.get("invasor")
    if not logado() or not inv:
        return jsonify({"sucesso": False, "mensagem": "Nenhuma pessoa estranha na propriedade agora."}), 400
    if COMODO_CAM[inv["comodo"]] != (request.json or {}).get("cam"):
        return jsonify({"sucesso": False, "mensagem": "Ele já saiu dessa câmera! Procure nas outras."}), 400
    n, fases = info_policia(inv["comodo"])
    session["invasor"] = None
    registrar("ok", f"Polícia acionada: pessoa estranha detida ({inv['comodo']}).")
    return jsonify({"sucesso": True, "comodo": inv["comodo"], "frames": n, "fases": fases})


@app.route("/api/policia/<comodo>/<int:f>.png")
def policia_img(comodo, f):
    if not logado() or comodo not in COMODO_CAM or not 0 <= f < info_policia(comodo)[0]:
        return "", 404
    return Response(quadro_policia(comodo, f), mimetype="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.route("/api/camera/<cam>.png")
def camera_img(cam):
    estado = request.args.get("estado", "ok")
    if not logado() or cam not in CAMERAS or estado not in ("ok", "invasor", "sem_sinal", "lente_suja", "escuro", "congelada"):
        return "", 404
    ar = request.args.get("ar", 0, type=int)
    png = renderizar(cam, estado, request.args.get("f", 0, type=int), request.args.get("luz", "1") != "0",
                     ar if ar in (1, 2) else 0)
    return Response(png, mimetype="image/png", headers={"Cache-Control": "private, max-age=60"})


# ---------- histórico de eventos ----------
@app.route("/api/historico")
def historico():
    if not logado():
        return jsonify({"sucesso": False}), 401
    return jsonify({"sucesso": True, "eventos": HISTORICO.get(dono(), [])})


# ---------- Assistente virtual guiado: o chatbot entende comandos escritos ----------
def _norm(t):
    t = unicodedata.normalize("NFD", str(t).lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


SINONIMOS_COMODO = {"jardim": "quintal", "fundos": "quintal", "hall": "entrada", "living": "sala"}
PALAVRAS_GENERICAS = {"luz", "luzes", "condicionado", "entrada", "sala", "cozinha", "garagem", "quintal", "dispositivo"}


def _comodo_em(t):
    for c in COMODO_CAM:
        if re.search(rf"\b{c}\b", t):
            return c
    for k, c in SINONIMOS_COMODO.items():
        if re.search(rf"\b{k}\b", t):
            return c
    return None


def _cam_em(t):
    m = re.search(r"\bcam(?:era)?\s*(?:n\w*\s*)?([1-5])\b", t)
    if m:
        return "cam" + m.group(1)
    c = _comodo_em(t)
    return COMODO_CAM[c] if c else None


def _resp(msg, css="bot", acao=None, sug=None):
    return jsonify({"sucesso": True, "mensagem": msg, "tipo_css": css, "acao": acao,
                    "sugestoes": sug or ["Verificar o sistema", "Status", "Ver câmeras", "Ajuda"]})


def _resumo_status():
    idx, oculto = session.get("problema"), session.get("oculto")
    lista = casa_do_usuario(dono())
    luz_on = sum(1 for d in lista if d["tipo"] == "luz" and d["ligado"])
    luz_tot = sum(1 for d in lista if d["tipo"] == "luz")
    linhas = []
    if idx is not None:
        linhas.append(f"⚠️ Problema encontrado: {PROBLEMAS[idx][2]}. Posso corrigir agora.")
    elif oculto is not None:
        linhas.append("⚠️ Detectei uma anomalia no sistema, mas ainda não sei o que é. Faça uma verificação.")
    else:
        linhas.append("✅ Nenhum problema conhecido no momento.")
    linhas.append(f"💡 Luzes acesas: {luz_on} de {luz_tot}.")
    ar = [d for d in lista if d["tipo"] == "ar"]
    if ar:
        linhas.append("❄️ Ar-condicionado: " + ", ".join(f"{d['nome']} {'ligado' if d['ligado'] else 'desligado'}" for d in ar) + ".")
    visivel = idx if idx is not None else oculto
    if visivel is not None and PROBLEMAS[visivel][5]:
        linhas.append(f"📷 {PROBLEMAS[visivel][5].replace('cam', 'CAM ')} está com defeito.")
    else:
        linhas.append("📷 As 5 câmeras estão online.")
    linhas.append("🚨 Há uma pessoa estranha na propriedade!" if session.get("invasor") else "🔒 Nenhuma pessoa estranha na propriedade.")
    return "\n".join(linhas)


def _comando_dispositivo(t, ligar):
    lista = casa_do_usuario(dono())
    tipo = None
    if re.search(r"\b(luz|luzes|lampada\w*|iluminacao)\b", t):
        tipo = "luz"
    elif re.search(r"\b(ar|climatizador\w*|refrigeracao)\b", t) or "condicionado" in t:
        tipo = "ar"
    comodo, todos = _comodo_em(t), bool(re.search(r"\b(tod[oa]s?|tudo)\b", t))
    palavras = set(t.split())
    por_nome = [d for d in lista if any(w in palavras for w in _norm(d["nome"]).split()
                                        if len(w) > 3 and w not in PALAVRAS_GENERICAS)]
    if por_nome:
        alvos = por_nome
    else:
        cand = [d for d in lista if (tipo is None or d["tipo"] == tipo) and (comodo is None or d["comodo"] == comodo)]
        if tipo is None and comodo is None and not todos:
            return _resp("O que você quer " + ("ligar" if ligar else "desligar") + "? Diga, por exemplo: "
                         f"“{'ligar' if ligar else 'desligar'} a luz da sala”.", "bot-alerta",
                         sug=["Ligar a luz da sala", "Desligar todas as luzes", "Ligar o ar"])
        if tipo is None and comodo is not None and not todos and len(cand) > 1:
            return _resp(f"Na {comodo} tem {len(cand)} dispositivos: " + ", ".join(d["nome"] for d in cand)
                         + ". Qual deles?", "bot-alerta", sug=[("Ligar " if ligar else "Desligar ") + d["nome"] for d in cand][:4])
        if tipo is not None and comodo is None and not todos and len(cand) > 1:
            salas = sorted({d["comodo"] for d in cand})
            return _resp(f"Qual cômodo? Tenho {'luzes' if tipo == 'luz' else 'ar-condicionado'} em: " + ", ".join(salas) + ".",
                         "bot-alerta", sug=[f"{'Ligar' if ligar else 'Desligar'} a luz da {c}" if tipo == 'luz'
                                            else f"{'Ligar' if ligar else 'Desligar'} o ar da {c}" for c in salas][:4])
        alvos = cand
    if not alvos:
        return _resp("Não encontrei nenhum dispositivo assim na sua casa. Veja a aba Casa para adicionar um.", "bot-erro",
                     sug=["Ir para Casa", "Ajuda"])
    mudou = []
    for d in alvos:
        if d["ligado"] != ligar:
            d["ligado"] = ligar
            mudou.append(d)
            registrar("info", f"{d['nome']} ({d['comodo']}): {'ligado' if ligar else 'desligado'} pelo assistente virtual guiado")
    if mudou:
        casa_salvar(dono(), lista)
    estado = "LIGADO" if ligar else "DESLIGADO"
    if not mudou:
        return _resp("Já estava " + estado.lower() + ": " + ", ".join(d["nome"] for d in alvos) + ".", acao={"tipo": "atualizar"})
    extra = ""
    if any(d["tipo"] == "luz" for d in mudou):
        extra = "\nDica: a luz do cômodo muda a imagem da câmera. Sem luz ela usa a visão noturna."
    return _resp("Pronto!\n" + "\n".join(f"• {d['nome']}: {estado}" for d in mudou) + extra, "bot-sucesso",
                 {"tipo": "atualizar"}, ["Ver câmeras", "Status", "Histórico"])


@app.route("/api/chatbot", methods=["POST"])
def chatbot():
    if not logado():
        return jsonify({"sucesso": False, "mensagem": "Entre na sua conta para falar com o assistente virtual guiado.", "tipo_css": "bot-erro"}), 401
    t = _norm((request.json or {}).get("texto", ""))
    nome = nome_de(session["user"]).split()[0]
    if not t:
        return _resp("Pode escrever ou tocar em uma das sugestões.")

    if re.search(r"\b(simul\w*|forc\w*)\b", t) and re.search(r"\b(invasao|invasor|intruso|estranho|aviso|vulnerabilidade|problema)\b", t):
        if not MODO_DEMO:
            return _resp("O modo de apresentação está desativado neste servidor.", "bot-alerta")
        if re.search(r"\b(invasao|invasor|intruso|estranho)\b", t):
            session["invasor"] = {"comodo": "quintal"}
            registrar("alerta", "Pessoa estranha detectada na propriedade.")
            return _resp("🚨 Simulação iniciada: uma pessoa estranha entrou pelos fundos. Abra as câmeras e ache onde ela está!",
                         "bot-erro", {"tipo": "tela", "tela": "cameras"}, ["Ver câmeras", "Chamar a polícia"])
        if re.search(r"\b(aviso|vulnerabilidade)\b", t):
            session["forcar_aviso"] = True
            return _resp("🤖 Certo! Em instantes a IA mostra uma vulnerabilidade que ela corrigiu sozinha.", acao={"tipo": "atualizar"})
        if session.get("problema") is None and session.get("oculto") is None:
            session["oculto"] = sortear_problema()
            registrar("alerta", "Alerta automático: o sistema detectou uma anomalia. Faça uma verificação.")
        return _resp("⚠️ Criei um problema no sistema. Faça a verificação para descobrir o que é.", "bot-alerta",
                     sug=["Verificar o sistema", "Status"])

    if re.search(r"\b(oi|ola|opa|eai|e ai|bom dia|boa tarde|boa noite|hey|hello)\b", t) and len(t) < 30:
        return _resp(f"Olá, {nome}! Sou o assistente virtual guiado. Posso verificar o sistema, mostrar as câmeras e controlar a casa. "
                     "O que você precisa?")
    if re.search(r"\b(obrigad\w*|valeu|vlw|brigad\w*)\b", t):
        return _resp("De nada! Estou de olho na sua casa. 😉")
    if re.search(r"\b(ajuda|help|comandos|o que (voce )?(faz|pode)|como (funciona|uso))\b", t):
        return _resp("Eu entendo frases como:\n• “verificar o sistema” e “corrigir o problema”\n• “ver a câmera da cozinha”\n"
                     "• “ligar a luz da sala”, “desligar todas as luzes”, “ligar o ar”\n• “status” e “histórico”\n"
                     "• “chamar a polícia” (quando houver alguém estranho)\n" + ("• “simular invasão” (modo apresentação)" if MODO_DEMO else ""),
                     sug=["Verificar o sistema", "Ligar a luz da sala", "Ver câmeras", "Status"])
    if re.search(r"\b(historico|eventos|o que aconteceu|registro|log|logs)\b", t):
        ev = HISTORICO.get(dono(), [])[:5]
        corpo = "\n".join(f"[{e['hora']}] {e['texto']}" for e in ev) or "Ainda não houve nenhum evento."
        return _resp("Os últimos eventos:\n" + corpo, acao={"tipo": "tela", "tela": "historico"}, sug=["Status", "Verificar o sistema"])
    if re.search(r"\b(status|situacao|resumo|como esta|tudo bem|esta tudo certo)\b", t):
        return _resp(_resumo_status(), "bot-alerta" if session.get("invasor") or session.get("problema") is not None else "bot",
                     sug=["Verificar o sistema", "Ver câmeras", "Histórico"])
    if re.search(r"\b(policia|190)\b", t):
        if session.get("invasor"):
            return _resp("🚨 Há uma pessoa estranha na propriedade! Abra as câmeras, ache onde ela está e toque em CHAMAR A POLÍCIA.",
                         "bot-erro", {"tipo": "tela", "tela": "cameras"}, ["Ver câmeras"])
        return _resp("Não há ninguém estranho na propriedade agora. Se aparecer, eu aviso você.")
    if re.search(r"\b(verific\w*|varredura|diagnostic\w*|escane\w*|scan|checar|checagem|analis\w*)\b", t):
        return _resp("🔍 Iniciando a verificação completa do sistema. Acompanhe o relatório na aba Início.",
                     acao={"tipo": "verificar"}, sug=["Status", "Ver câmeras"])
    if re.search(r"\b(corrig\w*|resolv\w*|consert\w*|arrum\w*|solucion\w*|repar\w*)\b", t):
        if session.get("problema") is not None:
            return _resp(f"🛠️ Corrigindo agora: {PROBLEMAS[session['problema']][2]}.", "bot-sucesso", {"tipo": "corrigir"})
        if session.get("oculto") is not None:
            return _resp("Detectei uma anomalia, mas preciso descobrir o que é antes de corrigir. Posso verificar o sistema agora?",
                         "bot-alerta", sug=["Verificar o sistema"])
        return _resp("Não há nenhum problema para corrigir. Está tudo certo por aqui! ✅")
    if re.search(r"\b(deslig\w*|apag\w*|desativ\w*)\b", t):
        return _comando_dispositivo(t, False)
    if re.search(r"\b(lig\w*|acend\w*|ativ\w*)\b", t):
        return _comando_dispositivo(t, True)
    if re.search(r"\b(camera\w*|cam|cameras|monitor|ver|mostra\w*|abrir)\b", t):
        cam = _cam_em(t)
        if cam:
            return _resp(f"📷 Abrindo a {cam.replace('cam', 'CAM ')} ({CAMERAS[cam].lower()}).", acao={"tipo": "camera", "cam": cam},
                         sug=["Status", "Ligar a luz da " + {v: k for k, v in COMODO_CAM.items()}[cam]])
        if re.search(r"\b(casa|dispositivos?|luzes)\b", t):
            return _resp("Abrindo o controle da casa.", acao={"tipo": "tela", "tela": "casa"})
        return _resp("Abrindo as câmeras.", acao={"tipo": "tela", "tela": "cameras"}, sug=["Ver a câmera da cozinha", "Status"])
    if re.search(r"\b(luz|luzes|lampada\w*|ar|condicionado)\b", t):
        return _resp("Quer ligar ou desligar? Diga, por exemplo: “ligar a luz da sala” ou “desligar o ar”.", "bot-alerta",
                     sug=["Ligar a luz da sala", "Desligar todas as luzes", "Ligar o ar"])
    return _resp("Não entendi essa. 🤔 Tente algo como “verificar o sistema”, “ver a câmera da garagem” ou “ligar a luz da sala”.",
                 "bot-alerta", sug=["Ajuda", "Verificar o sistema", "Ver câmeras", "Status"])



if __name__ == "__main__":
    # debug só se pedir (FLASK_DEBUG=1); host 0.0.0.0 deixa outros aparelhos da rede abrirem o site
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1" and not EM_PRODUCAO, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))