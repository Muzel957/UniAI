"""Casa inteligente em pixel art: câmeras de segurança animadas + animação da polícia.
Python puro (sem Pillow). As câmeras são desenhadas a cada quadro: cenas, objetos animados, visão noturna
infravermelha (luz apagada), distorção de lente, ruído de vídeo, defeitos e a pessoa estranha."""
import math
import random
import struct
import zlib
from functools import lru_cache

W, H, ESC = 160, 90, 4            # câmeras: 160x90 pixels (16:9), ampliados 4x = 640x360
FRAMES = 24                       # quadros do ciclo de animação das câmeras
CAMERAS = {"cam1": "ENTRADA", "cam2": "SALA", "cam3": "COZINHA", "cam4": "GARAGEM", "cam5": "QUINTAL"}
COMODO_CAM = {"entrada": "cam1", "sala": "cam2", "cozinha": "cam3", "garagem": "cam4", "quintal": "cam5"}


def mix(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def esc(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


class Tela:
    def __init__(self, cor, w=W, h=H):
        self.w, self.h = w, h
        self.p = [[cor] * w for _ in range(h)]

    def ret(self, x, y, w, h, c):
        for j in range(max(y, 0), min(y + h, self.h)):
            row = self.p[j]
            for i in range(max(x, 0), min(x + w, self.w)):
                row[i] = c

    def grad(self, x, y, w, h, c0, c1):
        for j in range(h):
            self.ret(x, y + j, w, 1, mix(c0, c1, j / max(1, h - 1)))

    def circ(self, cx, cy, r, c):
        for j in range(max(0, cy - r), min(self.h, cy + r + 1)):
            for i in range(max(0, cx - r), min(self.w, cx + r + 1)):
                if (i - cx) ** 2 + (j - cy) ** 2 <= r * r:
                    self.p[j][i] = c

    def luz(self, cx, cy, r, c, forca=0.4):
        """Brilho suave (lâmpadas, TV, lua, giroflex)."""
        for j in range(max(0, cy - r), min(self.h, cy + r)):
            for i in range(max(0, cx - r), min(self.w, cx + r)):
                d = ((i - cx) ** 2 + (j - cy) ** 2) ** 0.5
                if d < r:
                    self.p[j][i] = mix(self.p[j][i], c, forca * (1 - d / r) ** 1.5)

    def pto(self, x, y, c, a=1.0):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.p[y][x] = c if a >= 1 else mix(self.p[y][x], c, a)

    def mret(self, x, y, w, h, c, a):
        """Retângulo translúcido."""
        for j in range(max(y, 0), min(y + h, self.h)):
            row = self.p[j]
            for i in range(max(x, 0), min(x + w, self.w)):
                row[i] = mix(row[i], c, a)

    def lin(self, x0, y0, x1, y1, c):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.pto(x0, y0, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy; x0 += sx
            if e2 <= dx:
                err += dx; y0 += sy

    def elip(self, cx, cy, rx, ry, c):
        for j in range(max(0, cy - ry), min(self.h, cy + ry + 1)):
            for i in range(max(0, cx - rx), min(self.w, cx + rx + 1)):
                if ((i - cx) / rx) ** 2 + ((j - cy) / ry) ** 2 <= 1:
                    self.p[j][i] = c

    def escurecer(self, cx, cy, rx, ry, k):
        """Sombra suave em forma de elipse."""
        for j in range(max(0, cy - ry), min(self.h, cy + ry + 1)):
            for i in range(max(0, cx - rx), min(self.w, cx + rx + 1)):
                d = ((i - cx) / rx) ** 2 + ((j - cy) / ry) ** 2
                if d <= 1:
                    self.p[j][i] = esc(self.p[j][i], 1 - (1 - k) * (1 - d))

    def png(self, e=ESC):
        linhas = []
        for linha in self.p:
            r = b"\x00" + b"".join(bytes(c) * e for c in linha)
            linhas.append(r * e)

        def chunk(tipo, dados):
            return (struct.pack(">I", len(dados)) + tipo + dados
                    + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))

        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w * e, self.h * e, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(b"".join(linhas), 4))
                + chunk(b"IEND", b""))


# ====================== CENAS (cores de noite, com luzes quentes) ======================
def comodo(y, p0, p1, piso1, piso2, vx=80):
    """Parede com sanca e rodapé + piso de tábuas em perspectiva."""
    t = Tela(p1)
    t.grad(0, 0, W, y, p0, p1)
    t.ret(0, 0, W, 2, esc(p0, 0.6))
    t.ret(0, y - 3, W, 3, esc(p1, 0.62)); t.ret(0, y - 3, W, 1, mix(p1, (255, 255, 255), 0.18))
    t.grad(0, y, W, H - y, esc(piso1, 0.7), piso1)
    k, yy = 0, y + 3
    while yy < H:                                         # tábuas: espaçamento cresce com a proximidade
        t.ret(0, yy, W, 1, piso2)
        k += 1; yy += 2 + k
    vy = y - 34
    for xb in range(-160, 330, 22):                       # emendas convergindo para o ponto de fuga
        for j in range(y, H):
            x = int(vx + (xb - vx) * (j - vy) / (H - 1 - vy))
            if 0 <= x < W:
                t.p[j][x] = piso2
    return t


def apagar(t, luz, k=0.36):
    if not luz:
        t.p = [[esc(c, k) for c in row] for row in t.p]


def brilho(t, luz, x, y, r, c, a=0.5):
    if luz:
        t.luz(x, y, r, c, a)


def janela(t, x, y, w, h, c0=(36, 52, 128), c1=(92, 120, 196), cruz=True, lua=True):
    t.ret(x - 3, y - 3, w + 6, h + 6, (74, 78, 112)); t.ret(x - 3, y - 3, w + 6, 1, (112, 118, 156))
    t.grad(x, y, w, h, c0, c1)
    if lua:
        t.luz(x + w * 2 // 3, y + h // 3, max(w, h), (230, 236, 255), 0.45)
        t.circ(x + w * 2 // 3, y + h // 4, 3, (244, 244, 220))
    if cruz:
        t.ret(x + w // 2 - 1, y, 2, h, (74, 78, 112)); t.ret(x, y + h // 2 - 1, w, 2, (74, 78, 112))
    t.ret(x - 5, y + h + 3, w + 10, 3, (122, 126, 160))   # peitoril


def cortina(t, x, y, h, w, cor, balanco, lado):
    """Cortina balançando (mais movimento embaixo). lado: -1 esquerda, 1 direita."""
    for dy in range(h):
        s = int(balanco * dy / max(1, h) * lado)
        t.ret(x + s, y + dy, w, 1, cor)
        for c in range(1, w, 3):
            t.pto(x + s + c, y + dy, esc(cor, 0.78))
    t.ret(x - 3, y - 2, w + 6, 2, (90, 84, 78))


def tapete(t, y0, y1, cx, w0, w1, c1, c2, borda):
    for j in range(y0, y1):
        a = (j - y0) / max(1, y1 - y0 - 1)
        half = int(w0 + (w1 - w0) * a)
        t.ret(cx - half, j, 2 * half, 1, c1)
        t.ret(cx - half, j, 3, 1, borda); t.ret(cx + half - 3, j, 3, 1, borda)
        for i in range(cx - half + 5, cx + half - 5, 6):
            if (i // 6 + j // 2) % 2 == 0:
                t.p[j][i] = c2
    t.ret(cx - w0, y0, 2 * w0, 2, borda); t.ret(cx - w1, y1 - 2, 2 * w1, 2, borda)


# ---------- ENTRADA ----------
def cena_entrada(luz):
    y = 58
    t = comodo(y, (38, 44, 78), (62, 68, 108), (108, 76, 62), (82, 56, 48))
    t.ret(56, 6, 48, 52, (50, 34, 30)); t.ret(59, 9, 42, 49, (120, 84, 62)); t.ret(59, 9, 42, 1, (150, 110, 80))   # porta
    for px, py in ((64, 14), (82, 14), (64, 36), (82, 36)):
        t.ret(px, py, 14, 18, (92, 62, 48)); t.ret(px + 1, py + 1, 12, 16, (112, 78, 58)); t.ret(px + 1, py + 1, 12, 1, (140, 102, 74))
    t.circ(80, 28, 2, (22, 24, 34)); t.pto(79, 27, (170, 180, 200))                                              # olho mágico
    t.ret(95, 33, 3, 4, (238, 198, 92)); t.ret(92, 23, 7, 9, (28, 32, 44)); t.ret(60, 58, 40, 1, (60, 40, 34))   # maçaneta e fechadura
    t.ret(63, 61, 34, 7, (34, 32, 40)); t.ret(63, 61, 34, 1, (70, 66, 76)); t.ret(65, 64, 30, 1, (54, 52, 60))   # capacho
    t.ret(42, 18, 13, 2, (86, 60, 50)); t.ret(44, 16, 8, 2, (176, 148, 90))                                      # cabideiro e chapéu
    t.ret(43, 20, 10, 22, (150, 66, 78)); t.ret(47, 20, 1, 22, (178, 90, 100)); t.ret(43, 40, 10, 2, (116, 48, 60))
    t.ret(44, 61, 7, 3, (28, 28, 38)); t.ret(52, 61, 7, 3, (28, 28, 38)); t.ret(44, 61, 7, 1, (60, 60, 74))      # sapatos
    t.ret(114, 16, 28, 28, (126, 96, 62)); t.grad(116, 18, 24, 24, (66, 82, 118), (100, 116, 154))              # espelho
    t.lin(120, 40, 130, 20, (150, 164, 196)); t.lin(124, 40, 134, 20, (130, 146, 180))
    t.ret(108, 47, 46, 3, (134, 94, 66)); t.ret(110, 50, 42, 10, (102, 72, 54)); t.ret(126, 54, 10, 1, (238, 198, 92))  # aparador
    t.ret(110, 60, 3, 6, (88, 60, 46)); t.ret(149, 60, 3, 6, (88, 60, 46))
    t.ret(132, 44, 9, 3, (80, 112, 154)); t.ret(133, 42, 8, 2, (176, 90, 90))                                   # livros
    t.ret(144, 41, 9, 6, (176, 92, 62)); t.circ(148, 36, 5, (48, 118, 76)); t.circ(144, 33, 3, (62, 142, 90)); t.circ(152, 33, 3, (54, 130, 82))
    t.ret(121, 40, 4, 7, (206, 176, 96)); t.ret(116, 31, 14, 9, (240, 204, 140) if luz else (150, 130, 96))      # abajur
    t.ret(68, 0, 24, 3, (62, 62, 72)); t.ret(72, 3, 16, 3, (240, 206, 146) if luz else (140, 120, 90))           # luminária
    tapete(t, 70, 88, 80, 26, 44, (122, 54, 66), (176, 104, 100), (206, 160, 96))
    apagar(t, luz)
    janela(t, 12, 12, 28, 32)
    brilho(t, luz, 80, 6, 34, (255, 204, 130), 0.5)
    brilho(t, luz, 123, 36, 24, (255, 204, 130), 0.5)
    return t


def din_entrada(t, f, luz):
    sway = 2.2 * math.sin(f * 0.45)
    cortina(t, 6, 12, 36, 7, (150, 86, 100), sway, 1)
    cortina(t, 38, 12, 36, 7, (150, 86, 100), sway, -1)
    if f % 12 < 9:
        t.ret(94, 25, 2, 2, (80, 255, 140))                                      # fechadura trancada: LED verde
    if luz:                                                                      # mariposa girando em volta da luminária
        t.pto(80 + int(9 * math.cos(f * 0.8)), 8 + int(4 * math.sin(f * 1.3)), (240, 238, 210))
    if 7 <= f <= 11:                                                             # faróis de um carro passando na rua
        x0 = 150 - (f - 7) * 44
        for j in range(0, 58):
            for i in range(x0 + j // 2, x0 + j // 2 + 16):
                if 0 <= i < W:
                    t.p[j][i] = mix(t.p[j][i], (255, 244, 200), 0.17)


# ---------- SALA ----------
def cena_sala(luz):
    y = 58
    t = comodo(y, (44, 48, 86), (66, 64, 108), (104, 72, 58), (82, 56, 48))
    t.ret(60, 16, 36, 20, (146, 106, 60)); t.grad(62, 18, 32, 16, (74, 138, 160), (170, 168, 116))              # quadro
    t.circ(72, 26, 4, (240, 220, 150)); t.ret(62, 30, 32, 4, (60, 100, 90))
    t.ret(112, 14, 11, 11, (200, 196, 184)); t.circ(117, 19, 4, (236, 232, 220)); t.circ(117, 19, 5, (200, 196, 184))  # relógio
    tapete(t, 64, 88, 80, 40, 58, (110, 58, 82), (150, 84, 106), (196, 150, 100))
    t.ret(50, 36, 64, 15, (66, 98, 130)); t.ret(52, 38, 60, 2, (88, 122, 154))                                  # sofá: encosto
    t.ret(46, 48, 72, 14, (82, 118, 150)); t.ret(46, 48, 72, 2, (104, 140, 170)); t.ret(46, 60, 72, 3, (50, 78, 104))
    t.ret(42, 42, 8, 21, (62, 94, 126)); t.ret(114, 42, 8, 21, (62, 94, 126))
    t.ret(54, 41, 11, 10, (220, 130, 96)); t.ret(98, 41, 11, 10, (232, 202, 110)); t.ret(56, 43, 7, 1, (240, 170, 130))
    t.ret(58, 70, 48, 5, (150, 108, 72)); t.ret(58, 70, 48, 1, (184, 140, 98)); t.ret(60, 75, 3, 8, (96, 68, 50)); t.ret(101, 75, 3, 8, (96, 68, 50))
    t.ret(66, 66, 10, 4, (200, 80, 80)); t.ret(86, 66, 6, 4, (236, 236, 228)); t.ret(87, 65, 4, 1, (120, 80, 60))  # livro e xícara
    t.ret(124, 52, 34, 11, (90, 62, 52)); t.ret(124, 52, 34, 2, (122, 88, 70))                                   # rack
    t.ret(124, 30, 32, 21, (14, 16, 24)); t.ret(122, 51, 36, 2, (34, 34, 42))                                    # TV
    t.ret(150, 62, 3, 3, (90, 62, 50)); t.ret(128, 63, 3, 3, (90, 62, 50))
    t.ret(2, 56, 12, 6, (176, 92, 62)); t.circ(8, 50, 7, (46, 116, 74)); t.circ(4, 45, 4, (60, 138, 88)); t.circ(12, 45, 4, (52, 126, 80))  # vaso
    t.ret(155, 26, 1, 36, (60, 60, 72)); t.ret(148, 20, 12, 8, (240, 206, 140) if luz else (150, 130, 96))      # abajur de piso
    t.ret(150, 62, 10, 2, (60, 60, 72))
    apagar(t, luz)
    janela(t, 10, 8, 32, 34)
    brilho(t, luz, 154, 24, 26, (255, 204, 130), 0.5)
    return t


def din_sala(t, f, luz):
    sway = 2.0 * math.sin(f * 0.4)
    cortina(t, 3, 8, 40, 8, (176, 110, 80), sway, 1)
    cortina(t, 40, 8, 40, 8, (176, 110, 80), sway, -1)
    r = random.Random(f // 2)
    cor = ((78, 140, 220), (222, 130, 76), (96, 190, 130), (170, 108, 210), (232, 232, 244), (70, 98, 160))[(f // 3) % 6]
    t.grad(126, 32, 28, 17, mix(cor, (255, 255, 255), 0.15), esc(cor, 0.6))                                      # TV ligada
    for _ in range(3):
        t.ret(126 + r.randrange(24), 33 + r.randrange(12), r.randrange(3, 8), r.randrange(2, 6), esc(cor, 0.35 + r.random() * 0.8))
    t.luz(140, 42, 34, cor, 0.30)
    t.ret(124, 29, 32, 1, (30, 30, 38))
    ang = math.sin(f * 0.5)                                                                                       # gato dormindo, cauda balançando
    t.elip(78, 44, 8, 5, (204, 166, 124)); t.elip(78, 46, 8, 3, (180, 144, 104)); t.circ(70, 42, 3, (212, 176, 134))
    t.pto(68, 39, (212, 176, 134)); t.pto(72, 39, (212, 176, 134)); t.pto(69, 42, (40, 36, 40)); t.pto(71, 42, (40, 36, 40))
    for k in range(5):
        t.pto(85 + k, 47 - int(ang * 1.5) + (k // 3), (190, 150, 110))
    for k in range(3):                                                                                             # ventilador de teto
        a = f * 0.9 + k * 2.094
        t.lin(80, 4, 80 + int(20 * math.cos(a)), 4 + int(2 * math.sin(a)), (104, 96, 88))
    t.ret(77, 2, 7, 3, (64, 64, 74))
    cx, cy = 117, 19                                                                                               # ponteiro do relógio
    a = (f / FRAMES) * 2 * math.pi * 6
    t.lin(cx, cy, cx + int(3 * math.sin(a)), cy - int(3 * math.cos(a)), (50, 50, 60))


# ---------- COZINHA ----------
def cena_cozinha(luz):
    y = 60
    t = comodo(y, (64, 66, 98), (86, 86, 116), (120, 120, 138), (94, 96, 114), vx=70)
    for j in range(26, 46):                                                                                        # azulejos
        for i in range(0, 126, 4):
            t.ret(i, j, 4, 1, (124, 140, 166) if (i // 4 + j) % 2 else (104, 120, 146))
    t.ret(4, 6, 40, 20, (108, 82, 66)); t.ret(48, 6, 40, 20, (108, 82, 66)); t.ret(44, 6, 4, 20, (80, 60, 50))
    t.ret(4, 6, 40, 1, (136, 106, 86)); t.ret(48, 6, 40, 1, (136, 106, 86))
    for x in (38, 50, 80):
        t.ret(x, 20, 2, 4, (236, 204, 122))
    t.ret(100, 14, 24, 7, (160, 164, 180)); t.ret(108, 10, 8, 4, (130, 134, 150)); t.ret(100, 21, 24, 1, (96, 100, 116))  # coifa
    t.ret(0, 44, 126, 4, (184, 176, 168)); t.ret(0, 48, 126, 12, (92, 70, 62)); t.ret(0, 48, 126, 1, (122, 96, 82))     # bancada
    for x in (22, 46, 70, 94):
        t.ret(x, 48, 1, 12, (64, 48, 44)); t.ret(x - 4, 52, 2, 3, (236, 204, 122))
    t.ret(4, 34, 22, 10, (196, 198, 208)); t.ret(6, 36, 12, 6, (26, 28, 38)); t.ret(20, 36, 4, 5, (70, 74, 90))    # micro-ondas
    t.ret(34, 40, 18, 4, (170, 174, 190)); t.ret(40, 37, 6, 3, (30, 30, 40)); t.ret(42, 31, 2, 6, (206, 210, 226))   # pia e torneira
    t.ret(100, 44, 24, 3, (28, 28, 36)); t.circ(108, 44, 3, (60, 60, 72)); t.circ(118, 44, 3, (60, 60, 72))        # fogão
    t.ret(105, 36, 14, 8, (150, 154, 170)); t.ret(104, 36, 16, 1, (190, 194, 210)); t.ret(118, 38, 4, 1, (60, 60, 72))  # panela
    t.ret(128, 12, 28, 48, (154, 168, 188)); t.ret(128, 28, 28, 1, (96, 108, 126)); t.ret(128, 12, 28, 1, (190, 204, 224))   # geladeira
    t.ret(131, 15, 2, 9, (224, 228, 240)); t.ret(131, 31, 2, 12, (224, 228, 240))
    t.ret(138, 17, 4, 4, (236, 220, 110)); t.ret(145, 33, 4, 5, (236, 130, 130)); t.ret(138, 36, 4, 4, (110, 190, 236))
    t.ret(52, 63, 56, 5, (156, 112, 74)); t.ret(52, 63, 56, 1, (188, 144, 100)); t.ret(76, 68, 6, 14, (98, 68, 50)); t.ret(66, 82, 26, 3, (82, 56, 44))  # mesa
    t.circ(80, 62, 5, (206, 70, 70)); t.circ(84, 61, 4, (236, 190, 70)); t.ret(74, 62, 14, 2, (190, 150, 100))
    t.ret(44, 52, 4, 28, (110, 78, 58)); t.ret(44, 52, 10, 3, (130, 94, 70)); t.ret(112, 52, 4, 28, (110, 78, 58)); t.ret(106, 52, 10, 3, (130, 94, 70))  # cadeiras
    t.ret(46, 8, 1, 14, (200, 200, 210))
    apagar(t, luz)
    janela(t, 66, 10, 24, 28, cruz=True)
    brilho(t, luz, 40, 20, 34, (255, 224, 160), 0.45)
    brilho(t, luz, 80, 4, 40, (255, 230, 170), 0.35)
    return t


def din_cozinha(t, f, luz):
    t.ret(7, 36, 14, 6, (36, 40, 52))
    if f % 8 < 5:
        t.ret(10, 37, 2, 4, (90, 255, 150)); t.ret(14, 37, 2, 4, (90, 255, 150)); t.ret(17, 38, 1, 1, (90, 255, 150))  # relógio do micro-ondas
    else:
        t.ret(10, 37, 2, 4, (90, 255, 150)); t.ret(14, 37, 2, 4, (90, 255, 150))
    fl = (f % 3)                                                                                                    # chama azul
    t.ret(106, 44, 5, 1, (110, 170, 255)); t.pto(107 + fl, 43, (255, 190, 90)); t.pto(109, 43, (110, 170, 255))
    for k in range(6):                                                                                              # vapor subindo da panela
        pf = (f * 2 + k * 5) % 30
        t.pto(110 + int(2 * math.sin(pf * 0.5 + k)), 36 - pf // 2, (214, 220, 232), 0.55 - pf * 0.015)
    gota = (f * 2) % 12                                                                                             # gota na torneira
    if gota < 8:
        t.pto(43, 37 + gota, (140, 190, 240))
    t.pto(133, 14, (90, 255, 140) if f % 12 < 8 else (30, 80, 50))                                                  # LED da geladeira
    cx, cy = 46, 14                                                                                                 # relógio de parede
    t.circ(cx, cy, 5, (230, 230, 220)); t.circ(cx, cy, 4, (244, 244, 236))
    a = (f / FRAMES) * 2 * math.pi * 6
    t.lin(cx, cy, cx + int(3 * math.sin(a)), cy - int(3 * math.cos(a)), (40, 40, 50)); t.lin(cx, cy, cx, cy - 2, (40, 40, 50))


# ---------- GARAGEM ----------
def cena_garagem(luz):
    y = 60
    t = comodo(y, (72, 78, 96), (58, 62, 80), (88, 90, 102), (66, 68, 80), vx=60)
    t.ret(10, 8, 90, 52, (112, 118, 136))                                                                           # portão
    for yy in range(8, 60, 8):
        t.ret(10, yy, 90, 1, (72, 76, 92)); t.ret(10, yy + 1, 90, 1, (134, 140, 158))
    for xx in range(16, 100, 20):
        t.ret(xx, 12, 12, 5, (30, 38, 70)); t.ret(xx, 12, 12, 1, (90, 110, 190))
    t.ret(10, 58, 90, 2, (172, 192, 244))
    t.elip(60, 74, 36, 7, (46, 48, 58))                                                                              # sombra/óleo do carro
    t.ret(24, 38, 70, 14, (156, 40, 54)); t.ret(24, 38, 70, 1, (226, 104, 114)); t.ret(24, 50, 70, 3, (100, 24, 36))   # carro
    t.ret(40, 28, 40, 11, (136, 32, 46)); t.ret(40, 28, 40, 1, (196, 70, 84))
    t.grad(43, 30, 16, 8, (156, 196, 236), (100, 142, 196)); t.grad(61, 30, 17, 8, (156, 196, 236), (100, 142, 196)); t.ret(59, 30, 2, 8, (110, 28, 40))
    t.ret(90, 41, 5, 4, (255, 238, 156)); t.ret(24, 42, 3, 4, (236, 60, 60)); t.ret(24, 48, 70, 1, (60, 16, 24)); t.ret(58, 40, 1, 12, (110, 28, 40))
    for cx in (38, 80):
        t.circ(cx, 53, 7, (20, 20, 26)); t.circ(cx, 53, 4, (154, 156, 170)); t.circ(cx, 53, 1, (60, 60, 72))
    t.ret(104, 16, 52, 28, (120, 104, 86)); t.ret(104, 16, 52, 1, (150, 132, 108))                                    # painel de ferramentas
    for x, h in ((108, 12), (116, 9), (124, 14), (134, 10)):
        t.ret(x, 20, 2, h, (62, 62, 72)); t.ret(x - 1, 20 + h, 4, 3, (198, 200, 212))
    t.ret(142, 22, 8, 8, (206, 156, 76)); t.ret(146, 32, 7, 4, (170, 170, 184))
    t.ret(104, 46, 52, 4, (136, 94, 64)); t.ret(106, 50, 3, 12, (96, 66, 50)); t.ret(151, 50, 3, 12, (96, 66, 50))     # bancada
    t.ret(112, 41, 10, 5, (96, 126, 164)); t.ret(128, 40, 8, 6, (176, 110, 70))
    t.ret(140, 52, 14, 14, (76, 90, 80)); t.ret(140, 52, 14, 2, (104, 120, 108))                                       # lixeira
    t.ret(3, 30, 5, 9, (28, 34, 46))
    t.ret(50, 2, 64, 3, (230, 236, 246) if luz else (130, 134, 140))                                                   # lâmpada fluorescente
    apagar(t, luz)
    brilho(t, luz, 82, 4, 58, (214, 228, 255), 0.5)
    return t


def din_garagem(t, f, luz):
    t.ret(4, 31, 3, 3, (255, 70, 70) if f % 12 < 6 else (60, 20, 24))                                               # sensor do portão
    t.pto(78, 42, (255, 50, 50) if f % 8 < 2 else (70, 20, 24))                                                      # LED do alarme do carro
    if luz and f in (5, 6, 15):                                                                                      # lâmpada piscando
        t.mret(0, 0, W, H, (0, 0, 20), 0.30)
    if luz:                                                                                                          # poeira no ar
        for k in range(9):
            x = (k * 17 + f * 2 + (k % 3) * 5) % 100 + 50
            yy = (k * 11 + f) % 36 + 8
            t.pto(x, yy, (230, 236, 248), 0.6)


# ---------- QUINTAL ----------
def cena_quintal(luz):
    t = Tela((20, 24, 56))
    t.grad(0, 0, W, 46, (6, 8, 30), (46, 52, 104))
    r = random.Random(3)
    t.circ(118, 12, 7, (246, 246, 216)); t.luz(118, 12, 30, (190, 205, 255), 0.38)
    for x in range(0, W, 2):                                                                                         # morros distantes
        t.ret(x, 36 + int(5 * ((x // 9) % 3)) + int(3 * math.sin(x / 11)), 2, 14, (20, 26, 56))
    t.ret(0, 44, W, 20, (26, 34, 64))
    t.grad(0, 52, W, 38, (34, 74, 58), (14, 38, 34))                                                                 # gramado
    for _ in range(120):
        t.pto(r.randrange(W), r.randrange(54, 90), r.choice(((52, 104, 76), (24, 52, 44), (60, 120, 84))))
    for x in range(0, 118, 7):                                                                                       # cerca de madeira
        t.ret(x, 28, 6, 28, (100, 74, 62)); t.ret(x, 28, 6, 2, (136, 104, 86)); t.ret(x + 5, 28, 1, 28, (66, 48, 42))
    t.ret(0, 36, 118, 2, (76, 56, 50)); t.ret(0, 48, 118, 2, (76, 56, 50))
    t.ret(118, 14, 42, 52, (118, 104, 112)); t.ret(118, 14, 42, 3, (86, 50, 62)); t.ret(116, 12, 44, 3, (122, 70, 84))   # parede da casa
    for yy in range(18, 66, 4):
        t.ret(118, yy, 42, 1, (96, 84, 94))
    t.ret(126, 22, 16, 22, (66, 60, 76)); t.grad(128, 24, 12, 18, (244, 196, 120), (210, 148, 84)); t.ret(133, 24, 2, 18, (66, 60, 76))   # janela acesa
    t.ret(146, 30, 12, 36, (84, 62, 56)); t.ret(148, 32, 8, 32, (106, 78, 68)); t.ret(153, 46, 2, 2, (236, 196, 100))                       # porta dos fundos
    t.luz(134, 34, 24, (255, 200, 120), 0.35)
    for k in range(5):
        t.ret(40 + k * 5, 70 + k * 4, 8, 4, (120, 122, 130)); t.ret(40 + k * 5, 70 + k * 4, 8, 1, (150, 152, 160))   # pedras do caminho
    t.ret(12, 60, 18, 10, (40, 40, 48)); t.ret(10, 58, 22, 3, (70, 70, 80)); t.ret(14, 70, 2, 8, (50, 50, 58)); t.ret(26, 70, 2, 8, (50, 50, 58))  # churrasqueira
    t.ret(60, 70, 26, 3, (120, 96, 70)); t.ret(64, 73, 3, 9, (88, 68, 52)); t.ret(80, 73, 3, 9, (88, 68, 52))                                  # mesa do jardim
    t.ret(96, 40, 2, 20, (60, 60, 72)); t.ret(91, 36, 12, 5, (255, 224, 150) if luz else (120, 110, 90))                                      # poste de luz
    apagar(t, luz, 0.5)
    brilho(t, luz, 97, 38, 30, (255, 224, 150), 0.5)
    return t


def din_quintal(t, f, luz):
    r = random.Random(11)
    for k in range(34):                                                                                              # estrelas cintilando
        x, y = r.randrange(W), r.randrange(34)
        if (f + k) % 6 != 0:
            t.pto(x, y, (232, 232, 255), 0.55 + 0.45 * ((f + k) % 3) / 2)
    for k, (cy, rx) in enumerate(((20, 18), (8, 14))):                                                                # nuvens passando pela lua
        cx = int((f * 2.2 + k * 80) % (W + 60)) - 30
        t.elip(cx, cy, rx, 3, (62, 68, 118)); t.elip(cx + 6, cy - 2, rx - 5, 3, (74, 80, 130))
    sw = int(round(1.4 * math.sin(f * 0.35)))                                                                         # árvore balançando
    t.ret(24, 26, 6, 32, (78, 54, 46)); t.ret(24, 26, 2, 32, (102, 72, 60))
    t.circ(27 + sw, 16, 14, (28, 76, 62)); t.circ(18 + sw, 22, 9, (36, 92, 72)); t.circ(36 + sw, 21, 9, (42, 104, 80)); t.circ(28 + sw, 11, 8, (46, 112, 86))
    for k in range(10):
        t.pto(14 + k * 3 + sw, 12 + (k * 7) % 18, (70, 150, 110))
    for k in range(5):                                                                                                # vaga-lumes
        x = int(40 + k * 18 + 8 * math.sin(f * 0.4 + k * 2))
        y = int(58 + k * 5 + 4 * math.cos(f * 0.5 + k))
        if (f + k * 3) % 8 < 5:
            t.pto(x, y, (210, 255, 120)); t.luz(x, y, 4, (210, 255, 120), 0.4)
    if luz:                                                                                                           # mariposas no poste de luz
        for k in range(3):
            t.pto(97 + int(8 * math.cos(f * 0.9 + k * 2.1)), 36 + int(5 * math.sin(f * 1.2 + k)), (240, 238, 210))
    for k in range(18):                                                                                               # grama ao vento
        gx = (k * 9 + 5) % 118
        gy = 72 + (k * 5) % 16
        t.pto(gx + (1 if (f + k) % 6 < 3 else 0), gy, (88, 156, 108)); t.pto(gx, gy + 1, (60, 120, 84))


CENAS = {"cam1": cena_entrada, "cam2": cena_sala, "cam3": cena_cozinha, "cam4": cena_garagem, "cam5": cena_quintal}
DINAMICOS = {"cam1": din_entrada, "cam2": din_sala, "cam3": din_cozinha, "cam4": din_garagem, "cam5": din_quintal}


@lru_cache(maxsize=12)
def _cena(cam, luz):
    return CENAS[cam](luz)


# ====================== AR-CONDICIONADO NA CÂMERA ======================
AR_POS = {"cam1": (108, 3), "cam2": (66, 4), "cam3": (98, 3), "cam4": (110, 3), "cam5": (128, 60)}


def ar_corpo(t, cam, ar):
    """Aparelho visível na câmera: split na parede (no quintal, a unidade externa)."""
    if not ar:
        return
    x, y = AR_POS[cam]
    if cam == "cam5":
        t.ret(x, y, 22, 14, (152, 158, 172)); t.ret(x, y + 12, 22, 2, (96, 100, 114)); t.circ(x + 10, y + 6, 5, (54, 58, 70))
        t.ret(x, y, 22, 1, (190, 196, 208))
    else:
        t.ret(x, y, 26, 8, (210, 214, 224)); t.ret(x, y, 26, 1, (238, 240, 246)); t.ret(x, y + 6, 26, 2, (150, 156, 170)); t.ret(x + 2, y + 5, 22, 1, (70, 74, 88))


def ar_vento(t, cam, ar, f):
    """Ligado: LED azul e vento saindo (ou ventilador girando na unidade externa)."""
    if ar != 2:
        return
    x, y = AR_POS[cam]
    azul = (110, 210, 255)
    if cam == "cam5":
        for i in range(4):
            a = f * 0.6 + i * math.pi / 2
            for k in range(1, 6):
                t.pto(x + 10 + round(k * math.cos(a)), y + 6 + round(k * math.sin(a)), (208, 214, 226))
        t.ret(x + 17, y + 10, 2, 2, azul)
    else:
        t.ret(x + 22, y + 2, 2, 2, azul); t.luz(x + 23, y + 3, 5, azul, 0.6)
        for k in range(14):
            py = y + 8 + (k * 5 + f * 2) % 22
            px = x + 2 + (k * 7) % 22 + (1 if ((py - y) // 4) % 2 else 0)
            t.pto(px, py, (196, 232, 255), 0.7)


# ====================== A PESSOA ESTRANHA ======================
# (sorriso largo, olhos brilhando, braços compridos, lanterna e passos: ela anda pelo cômodo)
CENTRO = {"cam1": 84, "cam2": 76, "cam3": 78, "cam4": 62, "cam5": 70}
PES = {"cam1": 76, "cam2": 76, "cam3": 78, "cam4": 80, "cam5": 82}


def feixe(t, x0, y0, d, comp, abert, cor, a):
    """Cone de luz da lanterna."""
    for k in range(comp):
        h = 1 + abert * k // comp
        forca = a * (1 - k / comp) ** 1.3
        c = y0 + k // 5
        for j in range(c - h, c + h + 1):
            t.pto(x0 + d * k, j, cor, forca * (1 - abs(j - c) / (h + 1)))


def invasor(t, cam, f, rng):
    ang = f * 4 * math.pi / FRAMES
    x = CENTRO[cam] + int(22 * math.sin(ang))
    d = 1 if math.cos(ang) >= 0 else -1
    pes = PES[cam]
    esc_, pele, brilho_, dente = (10, 10, 18), (206, 212, 196), (255, 238, 110), (246, 246, 238)
    passo = f % 2
    t.escurecer(x, pes + 1, 13, 3, 0.45)
    t.luz(x, pes - 20, 26, (214, 30, 46), 0.22)
    feixe(t, x + d * 14, pes - 21, d, 44, 15, (255, 244, 190), 0.55)
    R = lambda dx, dy, w, h, c: t.ret(x - 8 + dx, pes - 38 + dy, w, h, c)
    R(3, 26, 4, 11 - passo, esc_); R(9, 26, 4, 10 + passo, esc_)                       # pernas alternando
    R(2, 37 - passo, 6, 1, (36, 36, 48)); R(9, 36 + passo, 6, 1, (36, 36, 48))
    R(1, 12, 14, 15, esc_); R(1, 12, 14, 1, (34, 34, 48)); R(7, 14, 2, 9, (26, 26, 38))   # moletom
    R(3, 0, 10, 1, esc_); R(2, 1, 12, 12, esc_)                                          # capuz
    R(4, 4, 8, 7, pele); R(4, 4, 8, 1, (176, 182, 170))
    olho = brilho_ if f % 9 != 4 else pele                                               # pisca de vez em quando
    R(5, 6, 2, 2, olho); R(9, 6, 2, 2, olho)
    R(5, 10, 6, 1, dente); R(6, 10, 1, 1, esc_); R(8, 10, 1, 1, esc_); R(10, 10, 1, 1, esc_)
    t.luz(x - 3, pes - 32, 5, brilho_, 0.35); t.luz(x + 1, pes - 32, 5, brilho_, 0.35)
    if d == 1:
        R(-3, 13, 3, 22, esc_); R(-3, 35, 3, 3, pele)                                    # braço que balança
        R(15, 13, 3, 6, esc_); R(17, 17, 10, 3, esc_); R(27, 15, 5, 6, (255, 244, 190))   # braço com a lanterna
    else:
        R(16, 13, 3, 22, esc_); R(16, 35, 3, 3, pele)
        R(-2, 13, 3, 6, esc_); R(-11, 17, 10, 3, esc_); R(-16, 15, 5, 6, (255, 244, 190))


# ====================== LENTE, COR E RUÍDO ======================
def _tabelas():
    cx, cy = (W - 1) / 2, (H - 1) / 2
    sj, si, vig = [], [], []
    for j in range(H):
        a, b, c = [], [], []
        for i in range(W):
            nx, ny = (i - cx) / cx, (j - cy) / cy
            r2 = nx * nx + ny * ny
            f = 1 + 0.055 * r2                                   # distorção de lente (barril)
            a.append(max(0, min(H - 1, int(round(cy + ny * f * cy)))))
            b.append(max(0, min(W - 1, int(round(cx + nx * f * cx)))))
            c.append(max(0.34, 1.10 - 0.62 * r2))                # vinheta
        sj.append(a); si.append(b); vig.append(c)
    return sj, si, vig


_SJ, _SI, _VIG = _tabelas()
_CL = [min(255, i) for i in range(2048)]


def _lente(t):
    p = t.p
    t.p = [[p[_SJ[j][i]][_SI[j][i]] for i in range(W)] for j in range(H)]


def _cor(t, ir, f, frio):
    """Vídeo colorido (luz acesa) ou visão noturna infravermelha (luz apagada)."""
    banda = (f * 7) % (H + 24) - 12                              # faixa de varredura descendo
    cl, p = _CL, t.p
    for j in range(H):
        row, v = p[j], _VIG[j]
        b = 1.09 if banda <= j < banda + 8 else 1.0
        for i in range(W):
            r, g, bl = row[i]
            l = (r * 3 + g * 6 + bl) / 10
            k = v[i] * b
            if ir:
                l *= 2.1 * k
                row[i] = (cl[int(l * 0.44)], cl[int(l)], cl[int(l * 0.52)])
            else:
                row[i] = (cl[int((r * 0.74 + l * 0.26) * k * (0.86 if frio else 0.98))],
                          cl[int((g * 0.74 + l * 0.26) * k)],
                          cl[int((bl * 0.74 + l * 0.26) * k * (1.2 if frio else 1.03))])


def _chiado(t, rng, n=2):
    for _ in range(n):                                           # linhas deslocadas, como fita velha
        y, d = rng.randrange(H), rng.randrange(-3, 4)
        t.p[y] = t.p[y][d:] + t.p[y][:d]


def _ruido(t, rng, qtd, minimo=60, verde=False):
    for _ in range(qtd):
        v = rng.randrange(minimo, 256)
        t.p[rng.randrange(H)][rng.randrange(W)] = (v // 2, v, v * 2 // 3) if verde else (v, v, v)


def _desfocar(t):
    """Imagem fora de foco: média em blocos 3x3 misturada com a original."""
    p = t.p
    for j in range(0, H, 3):
        for i in range(0, W, 3):
            bloco = [p[y][x] for y in range(j, min(H, j + 3)) for x in range(i, min(W, i + 3))]
            n = len(bloco)
            m = (sum(c[0] for c in bloco) // n, sum(c[1] for c in bloco) // n, sum(c[2] for c in bloco) // n)
            for y in range(j, min(H, j + 3)):
                for x in range(i, min(W, i + 3)):
                    p[y][x] = mix(p[y][x], m, 0.8)


# ====================== DEFEITOS DAS CÂMERAS ======================
def _defeito(t, estado, f, rng):
    if estado == "sem_sinal":                                    # chuvisco com uma sombra da imagem e a tela rolando
        fantasma = [[(c[0] + c[1] + c[2]) // 3 for c in row] for row in t.p]
        roll = (f * 11) % H
        for j in range(H):
            for i in range(W):
                v = rng.randrange(25, 215)
                t.p[j][i] = (v + fantasma[(j + roll) % H][i] // 7,) * 3
        for _ in range(3):
            t.ret(0, rng.randrange(H), W, rng.randrange(1, 4), (222, 222, 222))
        t.ret(0, (f * 17) % H, W, 5, (120, 120, 120))
    elif estado == "lente_suja":                                 # foco perdido, gotas e mancha de luz
        _desfocar(t)
        t.mret(0, 0, W, H, (150, 168, 150), 0.18)
        r = random.Random(5)
        for _ in range(11):
            cx, cy, rr = r.randrange(8, W - 8), r.randrange(8, H - 8), r.randrange(4, 10)
            for y in range(max(0, cy - rr), min(H, cy + rr)):
                for x in range(max(0, cx - rr), min(W, cx + rr)):
                    d2 = (x - cx) ** 2 + (y - cy) ** 2
                    if d2 < rr * rr:
                        t.p[y][x] = mix(t.p[y][x], (176, 196, 176), 0.5 if d2 > rr * rr * 0.5 else 0.28)
            t.pto(cx - rr // 3, cy - rr // 3, (240, 250, 240))
        t.luz(110, 20, 40, (236, 240, 226), 0.3)
    elif estado == "escuro":                                     # sem luz suficiente: quase nada aparece
        t.p = [[esc(c, 0.16) for c in row] for row in t.p]
        _ruido(t, rng, 420, 30)
    elif estado == "congelada":                                  # quadro travado com blocos corrompidos
        for _ in range(9):
            y, d = rng.randrange(H), rng.randrange(-14, 15)
            for j in range(y, min(H, y + rng.randrange(1, 5))):
                t.p[j] = t.p[j][d:] + t.p[j][:d]
        for _ in range(14):
            bx, by = rng.randrange(0, W - 8, 4), rng.randrange(0, H - 8, 4)
            sx, sy = rng.randrange(0, W - 8, 4), rng.randrange(0, H - 8, 4)
            blk = [row[sx:sx + 8] for row in t.p[sy:sy + 8]]
            for dj, row in enumerate(blk):
                t.p[by + dj][bx:bx + 8] = row
        t.ret(0, rng.randrange(H), W, 1, (235, 235, 235))


@lru_cache(maxsize=260)
def _render(cam, estado, frame, luz, ar):
    rng = random.Random(f"{cam}{estado}{frame}{luz}{ar}")
    base = _cena(cam, luz)
    t = Tela((0, 0, 0))
    t.p = [row[:] for row in base.p]
    DINAMICOS[cam](t, frame, luz)
    ar_corpo(t, cam, ar)
    ar_vento(t, cam, ar, frame)
    if estado == "invasor":
        invasor(t, cam, frame, rng)
    _lente(t)
    if estado in ("sem_sinal", "lente_suja", "escuro", "congelada"):
        if estado in ("lente_suja", "congelada"):
            _cor(t, not luz, frame, ar == 2)
        _defeito(t, estado, frame, rng)
        if estado != "sem_sinal":
            _chiado(t, rng, 1 if estado == "congelada" else 2)
        _ruido(t, rng, 60 if estado != "escuro" else 0, 50)
        return t.png()
    _cor(t, not luz, frame, ar == 2)
    _chiado(t, rng, 2)
    _ruido(t, rng, 70 if luz else 110, 50, verde=not luz)
    return t.png()


def renderizar(cam, estado="ok", frame=0, luz=True, ar=0):
    """PNG da câmera. Estados: ok, sem_sinal, lente_suja, escuro, congelada, invasor.
    luz: luz do cômodo ligada (imagem colorida) ou apagada (visão noturna infravermelha).
    ar: 0 = sem ar-condicionado no cômodo, 1 = desligado, 2 = ligado."""
    return _render(cam, estado, 0 if estado == "congelada" else frame % FRAMES, bool(luz), ar)


# ---------- ANIMAÇÃO: A POLÍCIA CHEGA E TIRA O ESTRANHO ----------
CW, CH = 128, 72
XC = {"garagem": 15, "entrada": 36, "sala": 58, "cozinha": 83, "quintal": 112}


@lru_cache(maxsize=1)
def _casa():
    t = Tela((20, 22, 52), CW, CH)
    t.grad(0, 0, CW, 58, (10, 12, 38), (46, 50, 96))
    r = random.Random(7)
    for _ in range(36):
        t.p[r.randrange(40)][r.randrange(CW)] = (230, 230, 255)
    t.circ(118, 9, 5, (244, 244, 214)); t.luz(118, 9, 22, (200, 210, 255), 0.3)
    t.grad(94, 48, 34, 12, (34, 72, 58), (24, 50, 44))                                         # quintal
    for x in range(96, 128, 5):
        t.ret(x, 44, 4, 14, (96, 72, 62))
    t.ret(108, 34, 3, 24, (74, 50, 42)); t.circ(109, 28, 10, (34, 84, 66)); t.circ(103, 33, 6, (42, 98, 76))
    t.ret(2, 5, 94, 4, (70, 36, 50)); t.ret(4, 9, 90, 5, (112, 60, 72)); t.ret(76, 0, 6, 8, (86, 60, 64))  # telhado
    for x, w, c in ((4, 22, (62, 70, 88)), (26, 20, (74, 66, 100)), (46, 24, (90, 72, 100)), (70, 24, (100, 88, 88))):
        t.grad(x, 14, w, 40, c, esc(c, 0.78)); t.ret(x, 54, w, 4, (112, 78, 60))
        t.luz(x + w // 2, 18, 20, (255, 200, 120), 0.42)
        t.ret(x, 14, 2, 44, (50, 44, 62)); t.ret(x, 38, 2, 16, c)                               # divisória com porta aberta
    t.ret(94, 14, 2, 44, (50, 44, 62))
    t.ret(6, 24, 14, 2, (96, 74, 62)); t.ret(8, 19, 4, 5, (150, 110, 70)); t.ret(14, 20, 4, 4, (150, 110, 70))   # garagem
    t.ret(30, 34, 3, 20, (110, 78, 56)); t.ret(34, 30, 8, 2, (110, 78, 56)); t.ret(35, 32, 2, 8, (160, 76, 84))  # entrada
    t.ret(50, 46, 16, 8, (60, 92, 114)); t.ret(50, 42, 16, 4, (50, 78, 100)); t.ret(52, 26, 10, 7, (18, 22, 34)); t.ret(53, 27, 8, 5, (70, 130, 210))  # sala
    t.ret(88, 26, 6, 28, (150, 164, 182)); t.ret(72, 46, 14, 8, (92, 70, 60)); t.ret(72, 44, 14, 2, (176, 168, 160))  # cozinha
    t.ret(0, 58, CW, 2, (120, 122, 140)); t.ret(0, 60, CW, 12, (46, 48, 58))                    # calçada e rua
    for x in range(0, CW, 14):
        t.ret(x, 67, 7, 1, (220, 190, 80))
    return t


def _carro(t, x, f, luzes):
    y = 60
    t.ret(x, y + 2, 28, 6, (226, 230, 240)); t.ret(x + 6, y - 2, 14, 5, (226, 230, 240))
    t.ret(x + 8, y - 1, 4, 3, (90, 130, 180)); t.ret(x + 13, y - 1, 5, 3, (90, 130, 180)); t.ret(x, y + 5, 28, 2, (40, 64, 160))
    t.ret(x + 3, y + 8, 6, 4, (18, 18, 24)); t.ret(x + 19, y + 8, 6, 4, (18, 18, 24))
    if luzes:
        a = (f // 2) % 2
        t.ret(x + 8, y - 3, 4, 1, (255, 50, 50) if a else (70, 40, 60)); t.ret(x + 14, y - 3, 4, 1, (70, 40, 60) if a else (70, 110, 255))
        t.luz(x + 10 if a else x + 16, y - 3, 26, (255, 50, 50) if a else (70, 110, 255), 0.55)


def _pessoa(t, x, y, corpo, chapeu, passo, intruso=False, cima=False):
    pele = (208, 214, 198) if intruso else (236, 196, 160)
    t.ret(x, y, 7, 2, chapeu); t.ret(x + 1, y + 1, 5, 4, pele); t.ret(x + 1, y + 5, 5, 5, corpo)
    ay = y + 1 if cima else y + 5
    t.ret(x - 1, ay, 1, 4, corpo); t.ret(x + 7, ay, 1, 4, corpo)
    t.ret(x + 1, y + 10, 2, 5 - passo % 2, (25, 28, 50)); t.ret(x + 4, y + 10, 2, 4 + passo % 2, (25, 28, 50))
    if intruso:
        t.ret(x + 2, y + 2, 1, 1, (255, 240, 120)); t.ret(x + 4, y + 2, 1, 1, (255, 240, 120)); t.ret(x + 2, y + 4, 3, 1, (246, 246, 240))
    else:
        t.ret(x + 3, y + 6, 1, 1, (240, 200, 60))


def _tempos(comodo):
    xi = XC[comodo]
    lado = 1 if xi >= 30 else -1
    ue = xi - 9 * lado
    L = max(4, abs(ue - 30) // 3 + 1)
    a = 12; b = a + 4; c = b + L; d = c + 8; e = d + L; h = e + 4
    return xi, lado, ue, L, a, b, c, d, e, h, h + 10


def info_policia(comodo):
    """(total de quadros, legendas [(quadro, texto)])."""
    xi, lado, ue, L, a, b, c, d, e, h, n = _tempos(comodo)
    return n, [(0, "A polícia está chegando!"), (a, "Os policiais desceram da viatura."),
               (b, f"Entrando na casa e procurando na {comodo}..."), (c, "Estranho encontrado!"),
               (c + 4, "Ele foi detido e algemado."), (d, "Levando o estranho para fora."),
               (e, "Colocando ele na viatura."), (h, "A polícia foi embora. Sua casa está segura!")]


@lru_cache(maxsize=700)
def quadro_policia(comodo, f):
    xi, lado, ue, L, a, b, c, d, e, h, n = _tempos(comodo)
    base = _casa()
    t = Tela((0, 0, 0), CW, CH)
    t.p = [row[:] for row in base.p]
    cx = -30 + 50 * f // a if f < a else (20 if f < h else 20 - 55 * (f - h) // 10)
    _carro(t, cx, f, f < h + 6)
    ix, ify, fy, ofic, cima, alg = xi, 58, 58, None, False, False
    if a <= f < b:
        ofic, fy = (30, 30 - 9 * lado), 62 - (f - a)
    elif b <= f < c:
        u = 30 + (ue - 30) * (f - b) // L
        ofic = (u, u - 9 * lado)
    elif c <= f < d:
        ofic = (ue, ue - 9 * lado); cima = f < c + 4; alg = not cima
    elif d <= f < e:
        v = ue + (30 - ue) * (f - d) // L
        ofic = (v, v + 18 * lado); ix = v + 9 * lado; alg = True
    elif e <= f < h - 1:
        ofic = (30, 30 + 18 * lado); ix = 30 + 9 * lado; ify = fy = 58 + (f - e); alg = True
    if f < h - 1:
        _pessoa(t, ix - 3, ify - 15, (12, 12, 20), (12, 12, 20), f, intruso=True, cima=cima)
        if alg:
            t.ret(ix - 1, ify - 9, 3, 1, (210, 210, 220))
    if ofic:
        for x in ofic:
            _pessoa(t, x - 3, fy - 15, (40, 64, 150), (24, 32, 90), f)
        if b <= f < d:
            t.luz(ofic[0] + 5 * lado, fy - 8, 15, (255, 240, 170), 0.4)
        if c <= f < c + 4:
            t.ret(ofic[0] - 1, fy - 24, 2, 4, (255, 220, 60)); t.ret(ofic[0] - 1, fy - 19, 2, 1, (255, 220, 60))
    return t.png(4)
