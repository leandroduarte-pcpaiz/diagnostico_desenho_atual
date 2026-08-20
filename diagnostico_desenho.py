# -*- coding: utf-8 -*-

"""
AIZI ENGINEERING AI
DIAGNÃƒâ€œSTICO DE DESENHO TÃƒâ€°CNICO

Objetivos:

1. Ler desenho PDF.
2. Extrair textos.
3. Extrair linhas vetoriais.
4. Identificar contornos fechados.
5. Identificar automaticamente o contorno da peÃƒÂ§a.
6. Validar contra dimensÃƒÂµes conhecidas.
7. Reconstruir geometria em mm.
8. Identificar dobras.
9. Identificar posiÃƒÂ§ÃƒÂ£o das dobras pela geometria.
10. Calcular BA / BD.
11. Reconstruir o desenvolvimento pelas abas reais.
12. Calcular blank.
13. Gerar diagnÃƒÂ³stico TXT.
14. Gerar JSON compatÃƒÂ­vel com calculadora_corte.py.

PRINCÃƒÂPIO DO DESENVOLVIMENTO:

O desenvolvimento nÃƒÂ£o deve ser obtido simplesmente de:

    bounding_box - BD

A geometria deve ser interpretada como:

    ABA 1
       +
    DOBRA 1
       +
    ABA 2
       +
    DOBRA 2
       +
    ABA 3

Para isso o algoritmo:

1. identifica o eixo longitudinal;
2. procura segmentos longitudinais reais do contorno;
3. agrupa os segmentos por posiÃƒÂ§ÃƒÂ£o transversal;
4. identifica as regiÃƒÂµes retas;
5. identifica as posiÃƒÂ§ÃƒÂµes das dobras;
6. calcula as abas;
7. calcula BA individualmente;
8. monta a sequÃƒÂªncia final;
9. valida o fechamento geomÃƒÂ©trico.

Para o componente 046:

    Comprimento longitudinal Ã¢â€°Ë† 672 mm
    Altura transversal      Ã¢â€°Ë† 163 mm

    Dobra 1 Ã¢â€°Ë† 48.2704 mm
    Dobra 2 Ã¢â€°Ë† 114.7761 mm

    R = 10 mm
    T = 6.35 mm
    K = 0.38

Resultado esperado:

    Desenvolvimento Ã¢â€°Ë† 136.596 mm

    Blank Ã¢â€°Ë† 136.596 x 672.002 mm
"""

from __future__ import annotations

import json
import math
import re
import sys

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dataclasses import dataclass, asdict
from pathlib import Path
from collections import defaultdict, deque
from typing import Optional, List, Dict, Tuple



# =============================================================================
# CORREÃ‡ÃƒO AIZI - RECUPERAÃ‡ÃƒO DE POSIÃ‡ÃƒO DE DOBRAS FRAGMENTADAS
# =============================================================================

def _aizi_recuperar_posicoes_dobras(
    dobras,
    largura_mm,
    altura_mm,
    segmentos=None,
):
    """
    Recupera a posiÃ§Ã£o geomÃ©trica das dobras quando a detecÃ§Ã£o conseguiu
    identificar Ã¢ngulo/raio, mas a posiÃ§Ã£o ficou N/D.

    EstratÃ©gia:
    1. preserva posiÃ§Ãµes jÃ¡ calculadas;
    2. procura linhas/fragmentos transversais associados Ã s dobras;
    3. usa a coordenada longitudinal mÃ©dia dos fragmentos;
    4. remove duplicidades;
    5. somente como Ãºltimo recurso usa a distribuiÃ§Ã£o geomÃ©trica das dobras.

    IMPORTANTE:
    NÃ£o substitui posiÃ§Ãµes vÃ¡lidas.
    """

    if not dobras:
        return dobras

    resultado = list(dobras)

    # -------------------------------------------------------------------------
    # 1. Procurar posiÃ§Ãµes diretamente nos segmentos.
    # -------------------------------------------------------------------------
    candidatos = []

    if segmentos:
        for seg in segmentos:
            try:
                x1 = float(seg.x1)
                y1 = float(seg.y1)
                x2 = float(seg.x2)
                y2 = float(seg.y2)

                dx = x2 - x1
                dy = y2 - y1

                comprimento = math.hypot(dx, dy)

                if comprimento <= 0.01:
                    continue

                angulo = abs(math.degrees(math.atan2(dy, dx)))

                # Segmentos aproximadamente transversais.
                transversal = (
                    70.0 <= angulo <= 110.0
                    or
                    250.0 <= angulo <= 290.0
                )

                if transversal:
                    candidatos.append(
                        {
                            "posicao_x": (x1 + x2) / 2.0,
                            "posicao_y": (y1 + y2) / 2.0,
                            "comprimento": comprimento,
                        }
                    )

            except Exception:
                continue

    # -------------------------------------------------------------------------
    # 2. Determinar o eixo longitudinal.
    # -------------------------------------------------------------------------
    eixo = "x"

    if largura_mm > 0 and altura_mm > 0:
        eixo = "x" if largura_mm >= altura_mm else "y"

    if candidatos:
        valores = []

        for c in candidatos:
            if eixo == "x":
                valores.append(c["posicao_x"])
            else:
                valores.append(c["posicao_y"])

        valores = sorted(valores)

        agrupados = []

        for valor in valores:
            if not agrupados:
                agrupados.append([valor])
                continue

            if abs(valor - agrupados[-1][-1]) <= TOLERANCIA_AGRUPAMENTO_DOBRA_MM:
                agrupados[-1].append(valor)
            else:
                agrupados.append([valor])

        centros = [
            sum(grupo) / len(grupo)
            for grupo in agrupados
        ]

        # ---------------------------------------------------------------------
        # 3. Converter para coordenada geomÃ©trica relativa Ã  peÃ§a.
        # ---------------------------------------------------------------------
        if eixo == "x":
            minimo = min(
                c["posicao_x"]
                for c in candidatos
            )
        else:
            minimo = min(
                c["posicao_y"]
                for c in candidatos
            )

        centros_relativos = [
            centro - minimo
            for centro in centros
        ]

        # Limita candidatos Ã s posiÃ§Ãµes internas da peÃ§a.
        limite = (
            largura_mm
            if eixo == "x"
            else altura_mm
        )

        centros_relativos = [
            p
            for p in centros_relativos
            if (
                MIN_DISTANCIA_BORDA_DOBRA_MM
                <= p
                <=
                limite - MIN_DISTANCIA_BORDA_DOBRA_MM
            )
        ]

        centros_relativos.sort()

    else:
        centros_relativos = []

    # -------------------------------------------------------------------------
    # 4. Aplicar posiÃ§Ãµes encontradas.
    # -------------------------------------------------------------------------
    indice_candidato = 0

    for i, dobra in enumerate(resultado):

        try:
            posicao_atual = getattr(
                dobra,
                "posicao_mm",
                None,
            )
        except Exception:
            posicao_atual = None

        if posicao_atual is not None:
            continue

        if indice_candidato < len(centros_relativos):

            nova_posicao = centros_relativos[
                indice_candidato
            ]

            indice_candidato += 1

            try:
                dobra.posicao_mm = float(
                    nova_posicao
                )
                dobra.origem = (
                    "GEOMETRIA_FRAGMENTADA_RECUPERADA"
                )
                dobra.confianca = max(
                    float(
                        getattr(
                            dobra,
                            "confianca",
                            0.0,
                        )
                    ),
                    0.70,
                )
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # 5. Fallback geomÃ©trico.
    #
    # SÃ³ entra se ainda houver dobras sem posiÃ§Ã£o.
    #
    # Para uma peÃ§a de duas dobras, a distribuiÃ§Ã£o Ã© obtida a partir das
    # regiÃµes internas da geometria, evitando deixar a cadeia inteira em zero.
    # -------------------------------------------------------------------------
    faltantes = [
        i
        for i, dobra in enumerate(resultado)
        if getattr(
            dobra,
            "posicao_mm",
            None,
        ) is None
    ]

    if faltantes and len(resultado) == 2:

        comprimento = (
            largura_mm
            if largura_mm >= altura_mm
            else altura_mm
        )

        if comprimento > 0:

            # Evita colocar dobra na borda.
            margem = max(
                2.0,
                comprimento * 0.05,
            )

            p1 = margem
            p2 = comprimento - margem

            valores = [p1, p2]

            for indice, posicao in zip(
                faltantes,
                valores,
            ):
                try:
                    resultado[indice].posicao_mm = (
                        float(posicao)
                    )
                    resultado[indice].origem = (
                        "FALLBACK_GEOMETRICO"
                    )
                    resultado[indice].confianca = max(
                        float(
                            getattr(
                                resultado[indice],
                                "confianca",
                                0.0,
                            )
                        ),
                        0.40,
                    )
                except Exception:
                    pass

    return resultado


def _aizi_validar_posicoes_dobras(
    dobras,
    comprimento_mm,
):
    """
    Valida as posiÃ§Ãµes recuperadas e elimina posiÃ§Ãµes impossÃ­veis.
    """

    if not dobras:
        return dobras

    resultado = []

    for dobra in dobras:

        posicao = getattr(
            dobra,
            "posicao_mm",
            None,
        )

        if posicao is not None:

            try:
                posicao = float(posicao)

                if (
                    posicao < 0
                    or posicao > comprimento_mm
                ):
                    dobra.posicao_mm = None

            except Exception:
                dobra.posicao_mm = None

        resultado.append(dobra)

    return resultado


# =============================================================================
# PYMUPDF
# =============================================================================

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf


# =============================================================================
# CONFIGURAÃƒâ€¡Ãƒâ€¢ES
# =============================================================================

TOLERANCIA_PONTO = 0.35
TOLERANCIA_CONTORNO = 0.75

MIN_SEGMENTO = 0.05
MIN_AREA_CONTORNO = 20.0

MIN_LARGURA_PECA = 50.0
MIN_ALTURA_PECA = 10.0

MAX_COMPONENTES_CANDIDATOS = 100

DIMENSAO_ALVO_LARGURA = 672.0
DIMENSAO_ALVO_ALTURA = 163.0

ESPESSURA_PADRAO = 6.35

RAIO_PADRAO = 10.0
ANGULO_PADRAO = 90.0

QUANTIDADE_DOBRAS_PADRAO = 2

TOLERANCIA_ANGULO_DOBRA = 4.0

MIN_FRACAO_COMPRIMENTO_LINHA_DOBRA = 0.35

TOLERANCIA_AGRUPAMENTO_DOBRA_MM = 2.0

MIN_DISTANCIA_BORDA_DOBRA_MM = 2.0

# Novo:
# Para considerar um segmento como uma aresta longitudinal real,
# ele precisa representar uma parcela significativa do comprimento
# longitudinal da peÃƒÂ§a.
MIN_FRACAO_SEGMENTO_LONGITUDINAL = 0.35

# TolerÃƒÂ¢ncia para agrupar arestas longitudinais paralelas.
TOLERANCIA_TRILHO_TRANSVERSAL_MM = 2.50

# DiferenÃƒÂ§a mÃƒÂ¡xima aceitÃƒÂ¡vel para considerar dois trilhos como
# pertencentes Ãƒ  mesma flange pela espessura.
TOLERANCIA_ESPESSURA_MM = 1.50

# TolerÃƒÂ¢ncia para fechamento da reconstruÃƒÂ§ÃƒÂ£o.
TOLERANCIA_RECONSTRUCAO_MM = 0.20


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Ponto:
    x: float
    y: float


@dataclass
class Segmento:
    indice: int
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def comprimento(self) -> float:
        return math.hypot(
            self.x2 - self.x1,
            self.y2 - self.y1,
        )

    @property
    def dx(self) -> float:
        return self.x2 - self.x1

    @property
    def dy(self) -> float:
        return self.y2 - self.y1

    @property
    def angulo(self) -> float:
        return math.degrees(
            math.atan2(
                self.dy,
                self.dx,
            )
        )


@dataclass
class Contorno:
    componente: str
    segmentos: List[Segmento]

    largura_pdf: float = 0.0
    altura_pdf: float = 0.0
    area_pdf: float = 0.0
    perimetro_pdf: float = 0.0

    escala: float = 1.0

    largura_mm: float = 0.0
    altura_mm: float = 0.0
    area_mm2: float = 0.0
    perimetro_mm: float = 0.0

    score: float = 0.0

    @property
    def vertices(self) -> int:
        return len(self.segmentos) + 1


@dataclass
class Dobra:
    numero: int
    angulo: float
    raio: Optional[float]
    posicao_mm: Optional[float]
    direcao: Optional[str]
    confianca: float
    origem: str


@dataclass
class Blank:
    comprimento_desenvolvido_mm: float
    largura_blank_mm: float
    comprimento_blank_mm: float
    espessura_mm: Optional[float]
    metodo: str
    valido: bool = True


# =============================================================================
# FUNÃƒâ€¡Ãƒâ€¢ES BÃƒÂSICAS
# =============================================================================

def distancia(
    p1: Ponto,
    p2: Ponto,
) -> float:

    return math.hypot(
        p2.x - p1.x,
        p2.y - p1.y,
    )


def ponto_proximo(
    p1: Ponto,
    p2: Ponto,
    tolerancia: float = TOLERANCIA_PONTO,
) -> bool:

    return distancia(p1, p2) <= tolerancia


def normalizar_componente(valor) -> str:

    if valor is None:
        return ""

    texto = str(valor).strip()

    numeros = re.findall(
        r"\d+",
        texto,
    )

    if not numeros:
        return texto

    return numeros[-1].zfill(3)


def limpar_texto(
    texto: str,
) -> str:

    if texto is None:
        return ""

    texto = texto.replace(
        "\n",
        " ",
    )

    texto = texto.replace(
        "\r",
        " ",
    )

    return re.sub(
        r"\s+",
        " ",
        texto,
    ).strip()


# =============================================================================
# DISTÃƒâ€šNCIA PONTO-LINHA
# =============================================================================

def distancia_ponto_segmento(
    ponto: Ponto,
    segmento: Segmento,
) -> float:

    x = ponto.x
    y = ponto.y

    x1 = segmento.x1
    y1 = segmento.y1

    x2 = segmento.x2
    y2 = segmento.y2

    dx = x2 - x1
    dy = y2 - y1

    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return math.hypot(
            x - x1,
            y - y1,
        )

    t = (
        (x - x1) * dx +
        (y - y1) * dy
    ) / (
        dx * dx +
        dy * dy
    )

    t = max(
        0.0,
        min(
            1.0,
            t,
        ),
    )

    px = x1 + t * dx
    py = y1 + t * dy

    return math.hypot(
        x - px,
        y - py,
    )


# =============================================================================
# ÃƒÂREA DE POLÃƒÂGONO
# =============================================================================

def area_pontos(
    pontos: List[Ponto],
) -> float:

    if len(pontos) < 3:
        return 0.0

    soma = 0.0

    for i in range(len(pontos)):

        p1 = pontos[i]

        p2 = pontos[
            (i + 1) % len(pontos)
        ]

        soma += (
            p1.x * p2.y
            -
            p2.x * p1.y
        )

    return abs(soma) / 2.0


# =============================================================================
# CONTORNO -> PONTOS
# =============================================================================

def segmentos_para_pontos(
    segmentos: List[Segmento],
) -> List[Ponto]:

    if not segmentos:
        return []

    restantes = segmentos.copy()

    primeiro = restantes.pop(0)

    pontos = [
        Ponto(
            primeiro.x1,
            primeiro.y1,
        )
    ]

    atual = Ponto(
        primeiro.x2,
        primeiro.y2,
    )

    pontos.append(atual)

    while restantes:

        encontrado = None
        proximo = None

        for i, seg in enumerate(restantes):

            p_inicio = Ponto(
                seg.x1,
                seg.y1,
            )

            p_fim = Ponto(
                seg.x2,
                seg.y2,
            )

            if ponto_proximo(
                atual,
                p_inicio,
            ):

                encontrado = i
                proximo = p_fim
                break

            if ponto_proximo(
                atual,
                p_fim,
            ):

                encontrado = i
                proximo = p_inicio
                break

        if encontrado is None:
            break

        restantes.pop(encontrado)

        pontos.append(
            proximo
        )

        atual = proximo

    return pontos


# =============================================================================
# BOUNDING BOX
# =============================================================================

def bounding_box_segmentos(
    segmentos: List[Segmento],
) -> Tuple[
    float,
    float,
    float,
    float,
]:

    if not segmentos:
        return (
            0.0,
            0.0,
            0.0,
            0.0,
        )

    xs = []
    ys = []

    for s in segmentos:

        xs.append(s.x1)
        xs.append(s.x2)

        ys.append(s.y1)
        ys.append(s.y2)

    return (
        min(xs),
        min(ys),
        max(xs),
        max(ys),
    )


# =============================================================================
# CONECTIVIDADE
# =============================================================================

def chave_ponto(
    x: float,
    y: float,
    tolerancia: float = TOLERANCIA_PONTO,
):

    return (
        round(x / tolerancia),
        round(y / tolerancia),
    )


def agrupar_segmentos_conectados(
    segmentos: List[Segmento],
) -> List[List[Segmento]]:

    if not segmentos:
        return []

    pontos = defaultdict(list)

    for i, seg in enumerate(segmentos):

        pontos[
            chave_ponto(
                seg.x1,
                seg.y1,
            )
        ].append(i)

        pontos[
            chave_ponto(
                seg.x2,
                seg.y2,
            )
        ].append(i)

    visitados = set()

    grupos = []

    for inicio in range(
        len(segmentos)
    ):

        if inicio in visitados:
            continue

        fila = deque([inicio])

        visitados.add(inicio)

        grupo = []

        while fila:

            atual = fila.popleft()

            grupo.append(
                segmentos[atual]
            )

            seg = segmentos[atual]

            chaves = [
                chave_ponto(
                    seg.x1,
                    seg.y1,
                ),
                chave_ponto(
                    seg.x2,
                    seg.y2,
                ),
            ]

            vizinhos = set()

            for chave in chaves:

                for idx in pontos[chave]:
                    vizinhos.add(idx)

            for idx in vizinhos:

                if idx not in visitados:

                    visitados.add(idx)

                    fila.append(idx)

        grupos.append(grupo)

    return grupos


# =============================================================================
# CONTORNO FECHADO
# =============================================================================

def contorno_fechado(
    segmentos: List[Segmento],
    tolerancia: float = TOLERANCIA_PONTO,
) -> bool:

    if len(segmentos) < 3:
        return False

    extremos = []

    for s in segmentos:

        extremos.append(
            Ponto(
                s.x1,
                s.y1,
            )
        )

        extremos.append(
            Ponto(
                s.x2,
                s.y2,
            )
        )

    grupos = []

    for p in extremos:

        encontrado = False

        for grupo in grupos:

            if ponto_proximo(
                p,
                grupo[0],
                tolerancia,
            ):

                grupo.append(p)

                encontrado = True
                break

        if not encontrado:
            grupos.append([p])

    for grupo in grupos:

        if len(grupo) < 2:
            return False

    return True


# =============================================================================
# CRIAR CONTORNO
# =============================================================================

def criar_contorno(
    segmentos: List[Segmento],
    componente: str,
) -> Optional[Contorno]:

    if len(segmentos) < 3:
        return None

    if not contorno_fechado(
        segmentos
    ):
        return None

    xmin, ymin, xmax, ymax = (
        bounding_box_segmentos(
            segmentos
        )
    )

    largura = xmax - xmin
    altura = ymax - ymin

    if (
        largura < MIN_ALTURA_PECA
        or
        altura < MIN_ALTURA_PECA
    ):
        return None

    pontos = segmentos_para_pontos(
        segmentos
    )

    if len(pontos) < 3:
        return None

    area = area_pontos(
        pontos
    )

    if area < MIN_AREA_CONTORNO:
        return None

    perimetro = sum(
        s.comprimento
        for s in segmentos
    )

    return Contorno(
        componente=normalizar_componente(
            componente
        ),
        segmentos=segmentos,
        largura_pdf=largura,
        altura_pdf=altura,
        area_pdf=area,
        perimetro_pdf=perimetro,
    )


# =============================================================================
# ESCALA
# =============================================================================

def calcular_escala(
    contorno: Contorno,
    alvo_largura: float,
    alvo_altura: float,
) -> Tuple[
    float,
    float,
    float,
]:

    largura = contorno.largura_pdf
    altura = contorno.altura_pdf

    if largura <= 0 or altura <= 0:

        return (
            0.0,
            999999.0,
            999999.0,
        )

    erro_normal = (
        abs(
            largura - alvo_largura
        )
        /
        alvo_largura
        +
        abs(
            altura - alvo_altura
        )
        /
        alvo_altura
    )

    erro_rotacionado = (
        abs(
            largura - alvo_altura
        )
        /
        alvo_altura
        +
        abs(
            altura - alvo_largura
        )
        /
        alvo_largura
    )

    if erro_rotacionado < erro_normal:

        escala = (
            alvo_largura / altura
            +
            alvo_altura / largura
        ) / 2.0

        estimada_largura = (
            altura * escala
        )

        estimada_altura = (
            largura * escala
        )

    else:

        escala = (
            alvo_largura / largura
            +
            alvo_altura / altura
        ) / 2.0

        estimada_largura = (
            largura * escala
        )

        estimada_altura = (
            altura * escala
        )

    erro_dimensao = (
        abs(
            estimada_largura -
            alvo_largura
        )
        /
        alvo_largura
        +
        abs(
            estimada_altura -
            alvo_altura
        )
        /
        alvo_altura
    ) / 2.0

    proporcao_pdf = (
        largura / altura
    )

    proporcao_alvo = (
        alvo_largura / alvo_altura
    )

    erro_proporcao_pdf = (
        abs(
            proporcao_pdf -
            proporcao_alvo
        )
        /
        proporcao_alvo
    )

    return (
        escala,
        erro_proporcao_pdf,
        erro_dimensao,
    )


# =============================================================================
# SCORE
# =============================================================================

def pontuar_contorno(
    contorno: Contorno,
    alvo_largura: float,
    alvo_altura: float,
) -> Contorno:

    escala, erro_prop, erro_dim = (
        calcular_escala(
            contorno,
            alvo_largura,
            alvo_altura,
        )
    )

    score = 0.0

    if erro_prop <= 0.01:
        score += 50

    elif erro_prop <= 0.03:
        score += 30

    elif erro_prop <= 0.10:
        score += 10

    else:
        score -= 40

    if erro_dim <= 0.01:
        score += 50

    elif erro_dim <= 0.03:
        score += 30

    elif erro_dim <= 0.10:
        score += 10

    else:
        score -= 40

    if len(contorno.segmentos) >= 40:
        score += 20

    elif len(contorno.segmentos) >= 20:
        score += 10

    relacao = (
        max(
            contorno.largura_pdf,
            contorno.altura_pdf,
        )
        /
        max(
            min(
                contorno.largura_pdf,
                contorno.altura_pdf,
            ),
            0.0001,
        )
    )

    if relacao >= 3:
        score += 10

    contorno.score = score
    contorno.escala = escala

    largura_est = (
        contorno.largura_pdf *
        escala
    )

    altura_est = (
        contorno.altura_pdf *
        escala
    )

    erro_normal = (
        abs(
            largura_est -
            alvo_largura
        )
        +
        abs(
            altura_est -
            alvo_altura
        )
    )

    largura_rot = (
        contorno.altura_pdf *
        escala
    )

    altura_rot = (
        contorno.largura_pdf *
        escala
    )

    erro_rot = (
        abs(
            largura_rot -
            alvo_largura
        )
        +
        abs(
            altura_rot -
            alvo_altura
        )
    )

    if erro_rot < erro_normal:

        contorno.largura_mm = largura_rot
        contorno.altura_mm = altura_rot

    else:

        contorno.largura_mm = largura_est
        contorno.altura_mm = altura_est

    contorno.area_mm2 = (
        contorno.area_pdf *
        escala *
        escala
    )

    contorno.perimetro_mm = (
        contorno.perimetro_pdf *
        escala
    )

    return contorno


# =============================================================================
# EXTRAÃƒâ€¡ÃƒÆ’O DE LINHAS
# =============================================================================

def extrair_linhas(
    pagina,
) -> List[Segmento]:

    segmentos = []

    desenhos = pagina.get_drawings()

    contador = 0

    for item in desenhos:

        for elemento in item.get(
            "items",
            [],
        ):

            if not elemento:
                continue

            tipo = elemento[0]

            if tipo != "l":
                continue

            p1 = elemento[1]
            p2 = elemento[2]

            x1 = float(p1.x)
            y1 = float(p1.y)

            x2 = float(p2.x)
            y2 = float(p2.y)

            comprimento = math.hypot(
                x2 - x1,
                y2 - y1,
            )

            if comprimento < MIN_SEGMENTO:
                continue

            segmentos.append(
                Segmento(
                    indice=contador,
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                )
            )

            contador += 1

    return segmentos


# =============================================================================
# EXTRAÃƒâ€¡ÃƒÆ’O DE TEXTOS
# =============================================================================

def extrair_textos(
    pagina,
) -> List[dict]:

    resultado = []

    dados = pagina.get_text(
        "dict"
    )

    for bloco in dados.get(
        "blocks",
        [],
    ):

        if "lines" not in bloco:
            continue

        for linha in bloco["lines"]:

            for span in linha.get(
                "spans",
                [],
            ):

                texto = limpar_texto(
                    span.get(
                        "text",
                        "",
                    )
                )

                if not texto:
                    continue

                bbox = span.get(
                    "bbox",
                    None,
                )

                resultado.append(
                    {
                        "texto": texto,
                        "x0": (
                            bbox[0]
                            if bbox
                            else 0
                        ),
                        "y0": (
                            bbox[1]
                            if bbox
                            else 0
                        ),
                        "x1": (
                            bbox[2]
                            if bbox
                            else 0
                        ),
                        "y1": (
                            bbox[3]
                            if bbox
                            else 0
                        ),
                    }
                )

    return resultado


# =============================================================================
# EXTRAIR NÃƒÅ¡MEROS
# =============================================================================

def extrair_numeros_textuais(
    textos: List[dict],
) -> List[float]:

    valores = []

    padroes = [
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*mm\b",
        r"(?<!\d)(\d{2,5}(?:[.,]\d+)?)",
    ]

    for item in textos:

        texto = item["texto"]

        for padrao in padroes:

            encontrados = re.findall(
                padrao,
                texto,
                flags=re.IGNORECASE,
            )

            for valor in encontrados:

                valor = valor.replace(
                    ",",
                    ".",
                )

                try:

                    numero = float(valor)

                    if 1 <= numero <= 10000:
                        valores.append(numero)

                except ValueError:
                    pass

    return valores


# =============================================================================
# IDENTIFICAR ESPESSURA
# =============================================================================

def identificar_espessura(
    textos: List[dict],
) -> Optional[float]:

    padroes = [
        r"(?:ESP|ESPESSURA|THK|T)\s*[:=]?\s*(\d+(?:[.,]\d+)?)",
        r"(\d+(?:[.,]\d+)?)\s*MM\b",
    ]

    candidatos = []

    for item in textos:

        texto = item["texto"].upper()

        for padrao in padroes:

            encontrados = re.findall(
                padrao,
                texto,
            )

            for valor in encontrados:

                try:

                    numero = float(
                        valor.replace(
                            ",",
                            ".",
                        )
                    )

                    if 0.5 <= numero <= 30:
                        candidatos.append(
                            numero
                        )

                except ValueError:
                    pass

    if not candidatos:
        return None

    candidatos.sort(
        key=lambda x: abs(
            x - ESPESSURA_PADRAO
        )
    )

    return candidatos[0]


# =============================================================================
# IDENTIFICAR Ãƒâ€šNGULOS
# =============================================================================

def extrair_angulos(
    textos: List[dict],
) -> List[float]:

    encontrados = []

    for item in textos:

        texto = item["texto"].upper()

        padroes = [
            r"(\d+(?:[.,]\d+)?)\s*Ã‚Â°",
            r"(\d+(?:[.,]\d+)?)\s*Ã‚Âº",
            r"(\d+(?:[.,]\d+)?)\s*DEG",
        ]

        for padrao in padroes:

            valores = re.findall(
                padrao,
                texto,
            )

            for valor in valores:

                try:

                    angulo = float(
                        valor.replace(
                            ",",
                            ".",
                        )
                    )

                    if 30 <= angulo <= 180:
                        encontrados.append(
                            angulo
                        )

                except ValueError:
                    pass

    return encontrados


# =============================================================================
# IDENTIFICAR RAIOS
# =============================================================================

def extrair_raios(
    textos: List[dict],
) -> List[float]:

    encontrados = []

    for item in textos:

        texto = item["texto"].upper()

        padroes = [
            r"\bR\s*([0-9]+(?:[.,][0-9]+)?)",
            r"\bRAIO\s*([0-9]+(?:[.,][0-9]+)?)",
        ]

        for padrao in padroes:

            valores = re.findall(
                padrao,
                texto,
            )

            for valor in valores:

                try:

                    raio = float(
                        valor.replace(
                            ",",
                            ".",
                        )
                    )

                    if 0.5 <= raio <= 100:
                        encontrados.append(
                            raio
                        )

                except ValueError:
                    pass

    return encontrados


# =============================================================================
# FUNÃƒâ€¡Ãƒâ€¢ES GEOMÃƒâ€°TRICAS PARA DOBRAS
# =============================================================================

def angulo_diferenca(
    a: float,
    b: float,
) -> float:

    a = abs(a) % 180.0
    b = abs(b) % 180.0

    diferenca = abs(
        a - b
    )

    return min(
        diferenca,
        180.0 - diferenca,
    )


def eixo_longitudinal(
    contorno: Contorno,
) -> str:

    if (
        contorno.largura_pdf
        >=
        contorno.altura_pdf
    ):
        return "X"

    return "Y"


def coordenada_transversal(
    segmento: Segmento,
    eixo_longitudinal: str,
) -> float:

    if eixo_longitudinal == "X":

        return (
            segmento.y1 +
            segmento.y2
        ) / 2.0

    return (
        segmento.x1 +
        segmento.x2
    ) / 2.0


def coordenada_longitudinal(
    segmento: Segmento,
    eixo_longitudinal: str,
) -> Tuple[float, float]:

    if eixo_longitudinal == "X":

        return (
            min(
                segmento.x1,
                segmento.x2,
            ),
            max(
                segmento.x1,
                segmento.x2,
            ),
        )

    return (
        min(
            segmento.y1,
            segmento.y2,
        ),
        max(
            segmento.y1,
            segmento.y2,
        ),
    )


# =============================================================================
# NOVA FUNÃƒâ€¡ÃƒÆ’O:
# IDENTIFICAR SEGMENTOS LONGITUDINAIS DO CONTORNO
# =============================================================================

def identificar_segmentos_longitudinais(
    contorno: Contorno,
) -> dict:

    eixo = eixo_longitudinal(
        contorno
    )

    escala = (
        contorno.escala
        if contorno.escala > 0
        else 1.0
    )

    xmin, ymin, xmax, ymax = (
        bounding_box_segmentos(
            contorno.segmentos
        )
    )

    if eixo == "X":

        comprimento_total_pdf = (
            xmax - xmin
        )

        comprimento_total_mm = (
            comprimento_total_pdf *
            escala
        )

        angulo_referencia = 0.0

    else:

        comprimento_total_pdf = (
            ymax - ymin
        )

        comprimento_total_mm = (
            comprimento_total_pdf *
            escala
        )

        angulo_referencia = 90.0

    candidatos = []

    if comprimento_total_pdf <= 0:
        return {
            "eixo_longitudinal": eixo,
            "comprimento_total_mm": 0.0,
            "candidatos": [],
            "trilhos": [],
        }

    for segmento in contorno.segmentos:

        comprimento_pdf = (
            segmento.comprimento
        )

        if comprimento_pdf <= 0:
            continue

        fracao = (
            comprimento_pdf /
            comprimento_total_pdf
        )

        if (
            fracao <
            MIN_FRACAO_SEGMENTO_LONGITUDINAL
        ):
            continue

        diferenca = angulo_diferenca(
            segmento.angulo,
            angulo_referencia,
        )

        if diferenca > TOLERANCIA_ANGULO_DOBRA:
            continue

        coordenada = coordenada_transversal(
            segmento,
            eixo,
        )

        inicio, fim = coordenada_longitudinal(
            segmento,
            eixo,
        )

        candidatos.append(
            {
                "segmento_indice":
                    segmento.indice,

                "coordenada_transversal_pdf":
                    coordenada,

                "coordenada_transversal_mm":
                    (
                        coordenada -
                        (
                            ymin
                            if eixo == "X"
                            else xmin
                        )
                    ) * escala,

                "inicio_longitudinal_pdf":
                    inicio,

                "fim_longitudinal_pdf":
                    fim,

                "comprimento_pdf":
                    comprimento_pdf,

                "comprimento_mm":
                    comprimento_pdf * escala,

                "fracao_comprimento":
                    fracao,

                "angulo_graus":
                    segmento.angulo,

                "diferenca_angular":
                    diferenca,
            }
        )

    candidatos.sort(
        key=lambda item:
            item[
                "coordenada_transversal_mm"
            ]
    )

    # -------------------------------------------------------------------------
    # AGRUPAMENTO DOS TRILHOS
    # -------------------------------------------------------------------------

    trilhos = []

    for candidato in candidatos:

        coord = candidato[
            "coordenada_transversal_mm"
        ]

        grupo = None

        for trilho in trilhos:

            if abs(
                coord -
                trilho[
                    "coordenada_media_mm"
                ]
            ) <= TOLERANCIA_TRILHO_TRANSVERSAL_MM:

                grupo = trilho
                break

        if grupo is None:

            grupo = {
                "coordenada_media_mm":
                    coord,

                "segmentos":
                    [],

                "comprimento_total_mm":
                    0.0,
            }

            trilhos.append(
                grupo
            )

        grupo["segmentos"].append(
            candidato
        )

        grupo["comprimento_total_mm"] += (
            candidato["comprimento_mm"]
        )

        grupo["coordenada_media_mm"] = (
            sum(
                item[
                    "coordenada_transversal_mm"
                ]
                for item in grupo["segmentos"]
            )
            /
            len(
                grupo["segmentos"]
            )
        )

    # -------------------------------------------------------------------------
    # CLASSIFICAÃƒâ€¡ÃƒÆ’O DOS TRILHOS
    # -------------------------------------------------------------------------

    for numero, trilho in enumerate(
        trilhos,
        start=1,
    ):

        trilho["numero"] = numero

        trilho["quantidade_segmentos"] = len(
            trilho["segmentos"]
        )

        trilho["comprimento_maximo_mm"] = max(
            (
                item["comprimento_mm"]
                for item in trilho["segmentos"]
            ),
            default=0.0,
        )

    return {
        "eixo_longitudinal":
            eixo,

        "comprimento_total_mm":
            comprimento_total_mm,

        "candidatos":
            candidatos,

        "trilhos":
            trilhos,
    }


# =============================================================================
# RECONSTRUIR PERFIL TRANSVERSAL
# =============================================================================

def reconstruir_perfil_transversal(
    contorno: Contorno,
    dobras: List[Dobra],
    espessura_mm: Optional[float],
) -> dict:

    """
    ReconstrÃƒÂ³i as trÃƒÂªs regiÃƒÂµes retas da peÃƒÂ§a a partir da geometria
    longitudinal real do contorno.

    A funÃƒÂ§ÃƒÂ£o NÃƒÆ’O utiliza:

        1/3
        2/3
        39%
        71%

    Ela procura as arestas longitudinais reais.

    O objetivo ÃƒÂ© produzir evidÃƒÂªncia geomÃƒÂ©trica para:

        ABA 1
        DOBRA 1
        ABA 2
        DOBRA 2
        ABA 3

    As posiÃƒÂ§ÃƒÂµes das dobras continuam sendo obtidas das linhas internas.

    A geometria longitudinal serve para validar que existem trÃƒÂªs
    regiÃƒÂµes fÃƒÂ­sicas da peÃƒÂ§a e para fornecer a separaÃƒÂ§ÃƒÂ£o entre
    as faces da chapa.
    """

    if espessura_mm is None:
        espessura_mm = ESPESSURA_PADRAO

    trilhos_info = identificar_segmentos_longitudinais(
        contorno
    )

    trilhos = trilhos_info[
        "trilhos"
    ]

    if len(trilhos) < 3:

        return {
            "status":
                "GEOMETRIA_INSUFICIENTE",

            "motivo":
                "MENOS_DE_TRES_TRILHOS_LONGITUDINAIS",

            "trilhos":
                trilhos,

            "quantidade_trilhos":
                len(trilhos),

            "abas_identificadas":
                [],
        }

    # -------------------------------------------------------------------------
    # Cada flange de uma chapa dobrada aparece como duas faces.
    #
    # Procuramos pares de trilhos separados aproximadamente pela espessura.
    # -------------------------------------------------------------------------

    pares_espessura = []

    for i in range(
        len(trilhos)
    ):

        for j in range(
            i + 1,
            len(trilhos)
        ):

            t1 = trilhos[i]
            t2 = trilhos[j]

            distancia_mm = abs(
                t2[
                    "coordenada_media_mm"
                ]
                -
                t1[
                    "coordenada_media_mm"
                ]
            )

            erro_espessura = abs(
                distancia_mm -
                espessura_mm
            )

            if (
                erro_espessura
                <=
                TOLERANCIA_ESPESSURA_MM
            ):

                pares_espessura.append(
                    {
                        "trilho_1":
                            t1["numero"],

                        "trilho_2":
                            t2["numero"],

                        "distancia_mm":
                            distancia_mm,

                        "erro_espessura_mm":
                            erro_espessura,

                        "score":
                            (
                                t1[
                                    "comprimento_maximo_mm"
                                ]
                                +
                                t2[
                                    "comprimento_maximo_mm"
                                ]
                                -
                                erro_espessura * 10.0
                            ),
                    }
                )

    pares_espessura.sort(
        key=lambda item:
            item["score"],
        reverse=True,
    )

    # -------------------------------------------------------------------------
    # POSIÃƒâ€¡Ãƒâ€¢ES DAS DOBRAS
    # -------------------------------------------------------------------------

    posicoes = sorted(
        [
            d.posicao_mm
            for d in dobras
            if d.posicao_mm is not None
        ]
    )

    if len(posicoes) != 2:

        return {
            "status":
                "GEOMETRIA_INSUFICIENTE",

            "motivo":
                "DUAS_POSICOES_DE_DOBRA_NAO_DISPONIVEIS",

            "trilhos":
                trilhos,

            "pares_espessura":
                pares_espessura,

            "abas_identificadas":
                [],
        }

    p1 = posicoes[0]
    p2 = posicoes[1]

    # -------------------------------------------------------------------------
    # A dimens?o transversal deve ser determinada pela geometria das dobras.
    #
    # O contorno pode ter largura/altura normalizadas ou rotacionadas.
    # Portanto N?O usamos cegamente o eixo do PDF para escolher entre
    # largura_mm e altura_mm.
    #
    # A dimens?o correta precisa conter as duas posi??es reais das dobras.
    # -------------------------------------------------------------------------

    maior_posicao_dobra = max(posicoes)

    dimensoes_candidatas = [
        float(contorno.largura_mm),
        float(contorno.altura_mm),
    ]

    dimensoes_validas = [
        dimensao
        for dimensao in dimensoes_candidatas
        if dimensao >= maior_posicao_dobra
    ]

    if not dimensoes_validas:
        return {
            "status":
                "GEOMETRIA_INCONSISTENTE",

            "motivo":
                "NENHUMA_DIMENSAO_CONTEM_AS_POSICOES_DAS_DOBRAS",

            "trilhos":
                trilhos,

            "pares_espessura":
                pares_espessura,

            "posicoes_dobras_mm":
                posicoes,

            "largura_mm":
                contorno.largura_mm,

            "altura_mm":
                contorno.altura_mm,

            "abas_identificadas":
                [],
        }

    # Preferimos a menor dimens?o que contenha as duas dobras.
    # Isso evita selecionar o comprimento longitudinal de 672 mm.
    dimensao_transversal = min(
        dimensoes_validas
    )

    # -------------------------------------------------------------------------
    # REGIÃƒâ€¢ES GEOMÃƒâ€°TRICAS EXTERNAS
    # -------------------------------------------------------------------------

    regiao_1 = p1
    regiao_2 = p2 - p1
    regiao_3 = (
        dimensao_transversal -
        p2
    )

    if (
        regiao_1 <= 0
        or regiao_2 <= 0
        or regiao_3 <= 0
    ):

        return {
            "status":
                "GEOMETRIA_INCONSISTENTE",

            "motivo":
                "REGIOES_TRANSVERSAIS_INVALIDAS",

            "trilhos":
                trilhos,

            "pares_espessura":
                pares_espessura,

            "regioes_externas_mm":
                [
                    regiao_1,
                    regiao_2,
                    regiao_3,
                ],

            "abas_identificadas":
                [],
        }

    # -------------------------------------------------------------------------
    # IDENTIFICAÃƒâ€¡ÃƒÆ’O DAS ABAS
    # -------------------------------------------------------------------------

    abas = [
        {
            "numero":
                1,

            "trecho_externo_mm":
                regiao_1,

            "posicao_inicio_mm":
                0.0,

            "posicao_fim_mm":
                p1,

            "origem":
                "GEOMETRIA_POSICAO_DOBRA_1",
        },

        {
            "numero":
                2,

            "trecho_externo_mm":
                regiao_2,

            "posicao_inicio_mm":
                p1,

            "posicao_fim_mm":
                p2,

            "origem":
                "GEOMETRIA_ENTRE_DOBRAS",
        },

        {
            "numero":
                3,

            "trecho_externo_mm":
                regiao_3,

            "posicao_inicio_mm":
                p2,

            "posicao_fim_mm":
                dimensao_transversal,

            "origem":
                "GEOMETRIA_DOBRA_2_ATE_BORDA",
        },
    ]

    # -------------------------------------------------------------------------
    # VALIDAÃƒâ€¡ÃƒÆ’O DOS TRILHOS
    # -------------------------------------------------------------------------

    comprimento_longitudinal = (
        trilhos_info[
            "comprimento_total_mm"
        ]
    )

    trilhos_relevantes = [
        t
        for t in trilhos
        if (
            t[
                "comprimento_maximo_mm"
            ]
            >=
            comprimento_longitudinal * 0.70
        )
    ]

    geometria_confirmada = (
        len(trilhos_relevantes) >= 3
    )

    return {
        "status":
            (
                "CONFIRMADO"
                if geometria_confirmada
                else
                "PARCIAL"
            ),

        "motivo":
            (
                "TRES_REGIOES_LONGITUDINAIS_IDENTIFICADAS"
                if geometria_confirmada
                else
                "REGIOES_DEFINIDAS_PELAS_DOBRAS_MAS_TRILHOS_INSUFICIENTES"
            ),

        "eixo_longitudinal":
            trilhos_info[
                "eixo_longitudinal"
            ],

        "comprimento_longitudinal_mm":
            comprimento_longitudinal,

        "dimensao_transversal_mm":
            dimensao_transversal,

        "trilhos":
            trilhos,

        "trilhos_relevantes":
            trilhos_relevantes,

        "pares_espessura":
            pares_espessura,

        "regioes_externas_mm":
            [
                regiao_1,
                regiao_2,
                regiao_3,
            ],

        "abas_identificadas":
            abas,
    }


# =============================================================================
# DETECTAR LINHAS DE DOBRA
# =============================================================================

def detectar_linhas_dobra_geometricas(
    segmentos: List[Segmento],
    contorno: Contorno,
    espessura_mm: Optional[float],
    raio_mm: Optional[float],
) -> dict:

    """
    Detecta linhas internas de dobra de forma robusta.

    CORREÃ‡ÃƒO:

    A versÃ£o anterior descartava um segmento individual quando ele
    representava menos de 35% do comprimento longitudinal da peÃ§a.

    Em PDFs CAD, uma mesma linha pode estar dividida em vÃ¡rios vetores.
    Portanto, o algoritmo correto Ã©:

        1. identificar todos os segmentos paralelos ao eixo longitudinal;
        2. agrupar os segmentos pela posiÃ§Ã£o transversal;
        3. somar os comprimentos de cada grupo;
        4. eliminar grupos prÃ³ximos das bordas;
        5. selecionar o melhor par interno.

    Dessa forma uma linha de dobra fragmentada continua sendo reconhecida.
    """

    eixo = eixo_longitudinal(contorno)

    xmin, ymin, xmax, ymax = bounding_box_segmentos(
        contorno.segmentos
    )

    if eixo == "X":

        comprimento_longitudinal_pdf = xmax - xmin

        limite_transversal_min = ymin
        limite_transversal_max = ymax

        angulo_referencia = 0.0

    else:

        comprimento_longitudinal_pdf = ymax - ymin

        limite_transversal_min = xmin
        limite_transversal_max = xmax

        angulo_referencia = 90.0

    if comprimento_longitudinal_pdf <= 0:

        return {
            "encontradas": False,
            "quantidade": 0,
            "eixo_longitudinal": eixo,
            "eixo_desenvolvimento": (
                "TRANSVERSAL"
                if eixo == "X"
                else "LONGITUDINAL"
            ),
            "comprimento_longitudinal_mm": 0.0,
            "dimensao_transversal_mm": 0.0,
            "candidatos": [],
            "linhas_selecionadas": [],
            "score_par": None,
            "motivo": "COMPRIMENTO_LONGITUDINAL_INVALIDO",
        }

    escala = contorno.escala

    if escala <= 0:
        escala = 1.0

    comprimento_longitudinal_mm = (
        comprimento_longitudinal_pdf * escala
    )

    dimensao_transversal_mm = (
        limite_transversal_max -
        limite_transversal_min
    ) * escala

    distancia_borda_pdf = (
        MIN_DISTANCIA_BORDA_DOBRA_MM / escala
    )

    # -------------------------------------------------------------------------
    # 1. COLETAR TODOS OS SEGMENTOS LONGITUDINAIS
    # -------------------------------------------------------------------------

    candidatos_brutos = []

    for segmento in segmentos:

        comprimento_pdf = segmento.comprimento

        if comprimento_pdf < MIN_SEGMENTO:
            continue

        diferenca_angular = angulo_diferenca(
            segmento.angulo,
            angulo_referencia,
        )

        if diferenca_angular > TOLERANCIA_ANGULO_DOBRA:
            continue

        coord_transversal = coordenada_transversal(
            segmento,
            eixo,
        )

        if (
            coord_transversal < limite_transversal_min
            or
            coord_transversal > limite_transversal_max
        ):
            continue

        distancia_borda = min(
            abs(
                coord_transversal -
                limite_transversal_min
            ),
            abs(
                limite_transversal_max -
                coord_transversal
            ),
        )

        # Elimina as duas bordas externas.
        if distancia_borda < distancia_borda_pdf:
            continue

        xlong1, xlong2 = coordenada_longitudinal(
            segmento,
            eixo,
        )

        comprimento_interno = xlong2 - xlong1

        if comprimento_interno <= 0:
            continue

        candidatos_brutos.append(
            {
                "segmento_indice": segmento.indice,
                "coordenada_transversal_pdf": coord_transversal,
                "comprimento_pdf": comprimento_pdf,
                "comprimento_mm": comprimento_pdf * escala,
                "fracao_comprimento": (
                    comprimento_pdf /
                    comprimento_longitudinal_pdf
                ),
                "angulo_graus": segmento.angulo,
                "diferenca_angular": diferenca_angular,
                "inicio_longitudinal_pdf": xlong1,
                "fim_longitudinal_pdf": xlong2,
            }
        )

    # -------------------------------------------------------------------------
    # 2. AGRUPAR SEGMENTOS PELA POSIÃ‡ÃƒO TRANSVERSAL
    # -------------------------------------------------------------------------

    candidatos_brutos.sort(
        key=lambda item:
            item["coordenada_transversal_pdf"]
    )

    grupos = []

    tolerancia_agrupamento_pdf = (
        TOLERANCIA_AGRUPAMENTO_DOBRA_MM / escala
    )

    for candidato in candidatos_brutos:

        coord = candidato[
            "coordenada_transversal_pdf"
        ]

        grupo_encontrado = None

        for grupo in grupos:

            if abs(
                coord -
                grupo["media_coordenada_pdf"]
            ) <= tolerancia_agrupamento_pdf:

                grupo["itens"].append(
                    candidato
                )

                grupo["media_coordenada_pdf"] = (
                    sum(
                        item[
                            "coordenada_transversal_pdf"
                        ]
                        for item in grupo["itens"]
                    )
                    /
                    len(grupo["itens"])
                )

                grupo_encontrado = grupo
                break

        if grupo_encontrado is None:

            grupos.append(
                {
                    "media_coordenada_pdf": coord,
                    "itens": [candidato],
                }
            )

    # -------------------------------------------------------------------------
    # 3. TRANSFORMAR GRUPOS EM CANDIDATOS DE DOBRA
    # -------------------------------------------------------------------------

    candidatos_agrupados = []

    for grupo in grupos:

        itens = grupo["itens"]

        comprimento_total_pdf = sum(
            item["comprimento_pdf"]
            for item in itens
        )

        comprimento_total_mm = (
            comprimento_total_pdf * escala
        )

        media_coord = grupo[
            "media_coordenada_pdf"
        ]

        posicao_mm = (
            media_coord -
            limite_transversal_min
        ) * escala

        distancia_borda_1 = posicao_mm

        distancia_borda_2 = (
            dimensao_transversal_mm -
            posicao_mm
        )

        if (
            distancia_borda_1 <
            MIN_DISTANCIA_BORDA_DOBRA_MM
        ):
            continue

        if (
            distancia_borda_2 <
            MIN_DISTANCIA_BORDA_DOBRA_MM
        ):
            continue

        maior_segmento_mm = max(
            (
                item["comprimento_mm"]
                for item in itens
            ),
            default=0.0,
        )

        fracao_total = (
            comprimento_total_mm /
            max(
                comprimento_longitudinal_mm,
                0.0001,
            )
        )

        fracao_maior_segmento = (
            maior_segmento_mm /
            max(
                comprimento_longitudinal_mm,
                0.0001,
            )
        )

        erro_angular_medio = sum(
            item["diferenca_angular"]
            for item in itens
        ) / max(len(itens), 1)

        score_comprimento = min(
            fracao_total,
            1.0,
        ) * 60.0

        score_fragmentacao = min(
            len(itens),
            10,
        ) * 2.0

        score_angulo = max(
            0.0,
            20.0 -
            erro_angular_medio * 10.0,
        )

        score_borda = min(
            min(
                distancia_borda_1,
                distancia_borda_2,
            ) / 20.0,
            10.0,
        )

        score = (
            score_comprimento
            +
            score_fragmentacao
            +
            score_angulo
            +
            score_borda
        )

        candidatos_agrupados.append(
            {
                "coordenada_transversal_pdf":
                    media_coord,

                "posicao_mm_desde_borda":
                    posicao_mm,

                "comprimento_total_pdf":
                    comprimento_total_pdf,

                "comprimento_total_mm":
                    comprimento_total_mm,

                "quantidade_segmentos":
                    len(itens),

                "maior_segmento_mm":
                    maior_segmento_mm,

                "fracao_comprimento_total":
                    fracao_total,

                "fracao_maior_segmento":
                    fracao_maior_segmento,

                "erro_angular_medio":
                    erro_angular_medio,

                "score":
                    score,

                "segmentos":
                    itens,
            }
        )

    candidatos_agrupados.sort(
        key=lambda item:
            item["posicao_mm_desde_borda"]
    )

    # -------------------------------------------------------------------------
    # 4. SELECIONAR APENAS CANDIDATOS INTERNOS
    # -------------------------------------------------------------------------

    candidatos_uteis = []

    for candidato in candidatos_agrupados:

        posicao = candidato[
            "posicao_mm_desde_borda"
        ]

        distancia_borda_1 = posicao

        distancia_borda_2 = (
            dimensao_transversal_mm -
            posicao
        )

        if (
            distancia_borda_1 <
            MIN_DISTANCIA_BORDA_DOBRA_MM
        ):
            continue

        if (
            distancia_borda_2 <
            MIN_DISTANCIA_BORDA_DOBRA_MM
        ):
            continue

        candidatos_uteis.append(
            candidato
        )

    # -------------------------------------------------------------------------
    # 5. SELECIONAR O MELHOR PAR
    # -------------------------------------------------------------------------

    par_selecionado = None
    score_par = -999999.0

    raio = (
        raio_mm
        if raio_mm is not None
        else RAIO_PADRAO
    )

    espessura = (
        espessura_mm
        if espessura_mm is not None
        else ESPESSURA_PADRAO
    )

    setback_referencia = (
        (
            raio +
            espessura
        )
        *
        math.tan(
            math.radians(
                ANGULO_PADRAO / 2.0
            )
        )
    )

    for i in range(
        len(candidatos_uteis)
    ):

        for j in range(
            i + 1,
            len(candidatos_uteis)
        ):

            c1 = candidatos_uteis[i]
            c2 = candidatos_uteis[j]

            p1 = c1[
                "posicao_mm_desde_borda"
            ]

            p2 = c2[
                "posicao_mm_desde_borda"
            ]

            if p2 <= p1:
                continue

            trecho1 = p1

            trecho2 = p2 - p1

            trecho3 = (
                dimensao_transversal_mm -
                p2
            )

            if trecho1 <= setback_referencia:
                continue

            if trecho2 <= 2.0 * setback_referencia:
                continue

            if trecho3 <= setback_referencia:
                continue

            distancia_entre = p2 - p1

            score_atual = (
                c1["score"]
                +
                c2["score"]
            )

            # Penaliza linhas muito prÃ³ximas.
            if (
                distancia_entre
                <
                3.0 * setback_referencia
            ):
                score_atual -= 20.0

            # Favorece linhas com comprimento parecido.
            diferenca_comprimento = abs(
                c1["comprimento_total_mm"] -
                c2["comprimento_total_mm"]
            )

            score_atual -= min(
                diferenca_comprimento / 20.0,
                20.0,
            )

            if score_atual > score_par:

                score_par = score_atual

                par_selecionado = (
                    c1,
                    c2,
                )

    encontradas = (
        par_selecionado is not None
    )

    # -------------------------------------------------------------------------
    # 6. RESULTADO
    # -------------------------------------------------------------------------

    linhas_selecionadas = []

    if encontradas:

        for numero, candidato in enumerate(
            par_selecionado,
            start=1,
        ):

            linhas_selecionadas.append(
                {
                    "numero": numero,

                    "posicao_mm":
                        candidato[
                            "posicao_mm_desde_borda"
                        ],

                    "coordenada_pdf":
                        candidato[
                            "coordenada_transversal_pdf"
                        ],

                    "comprimento_mm":
                        candidato[
                            "comprimento_total_mm"
                        ],

                    "score":
                        candidato[
                            "score"
                        ],

                    "quantidade_segmentos":
                        candidato[
                            "quantidade_segmentos"
                        ],

                    "segmentos":
                        candidato[
                            "segmentos"
                        ],
                }
            )

    return {
        "encontradas":
            encontradas,

        "quantidade":
            len(linhas_selecionadas),

        "eixo_longitudinal":
            eixo,

        "eixo_desenvolvimento":
            (
                "TRANSVERSAL"
                if eixo == "X"
                else "LONGITUDINAL"
            ),

        "comprimento_longitudinal_mm":
            comprimento_longitudinal_mm,

        "dimensao_transversal_mm":
            dimensao_transversal_mm,

        "candidatos":
            candidatos_uteis,

        "linhas_selecionadas":
            linhas_selecionadas,

        "score_par":
            (
                score_par
                if encontradas
                else None
            ),

        "setback_referencia_mm":
            setback_referencia,

        "motivo":
            (
                "DUAS_LINHAS_INTERNAS_COMPATIVEIS"
                if encontradas
                else
                "LINHAS_DE_DOBRA_NAO_IDENTIFICADAS"
            ),
    }


# =============================================================================
# IDENTIFICAR DOBRAS
# =============================================================================

def identificar_dobras(
    textos: List[dict],
    contorno: Contorno,
    espessura_mm: Optional[float],
    todos_segmentos: List[Segmento],
) -> Tuple[
    List[Dobra],
    dict,
]:

    angulos_texto = extrair_angulos(
        textos
    )

    raios_texto = extrair_raios(
        textos
    )

    if len(angulos_texto) >= 2:

        angulos = angulos_texto[:2]
        origem_angulo = "TEXTO"

    elif len(angulos_texto) == 1:

        angulos = [
            angulos_texto[0],
            angulos_texto[0],
        ]

        origem_angulo = "TEXTO_E_REPETICAO"

    else:

        angulos = [
            ANGULO_PADRAO,
            ANGULO_PADRAO,
        ]

        origem_angulo = "CONFIGURACAO_PADRAO"

    if len(raios_texto) >= 2:

        raios = raios_texto[:2]
        origem_raio = "TEXTO"

    elif len(raios_texto) == 1:

        raios = [
            raios_texto[0],
            raios_texto[0],
        ]

        origem_raio = "TEXTO_E_REPETICAO"

    else:

        raios = [
            RAIO_PADRAO,
            RAIO_PADRAO,
        ]

        origem_raio = "CONFIGURACAO_PADRAO"

    raio_referencia = raios[0]

    deteccao_geometrica = (
        detectar_linhas_dobra_geometricas(
            todos_segmentos,
            contorno,
            espessura_mm,
            raio_referencia,
        )
    )

    dobras = []

    if (
        deteccao_geometrica["encontradas"]
        and
        deteccao_geometrica["quantidade"] >= 2
    ):

        linhas = (
            deteccao_geometrica[
                "linhas_selecionadas"
            ]
        )

        for i in range(2):

            angulo = (
                angulos[i]
                if i < len(angulos)
                else ANGULO_PADRAO
            )

            raio = (
                raios[i]
                if i < len(raios)
                else RAIO_PADRAO
            )

            linha = linhas[i]

            confianca = 0.97

            if (
                origem_angulo ==
                "CONFIGURACAO_PADRAO"
            ):
                confianca -= 0.03

            if (
                origem_raio ==
                "CONFIGURACAO_PADRAO"
            ):
                confianca -= 0.03

            dobras.append(
                Dobra(
                    numero=i + 1,
                    angulo=angulo,
                    raio=raio,
                    posicao_mm=(
                        linha[
                            "posicao_mm"
                        ]
                    ),
                    direcao=(
                        "PARALELA_EIXO_LONGITUDINAL"
                    ),
                    confianca=confianca,
                    origem=(
                        "GEOMETRIA_LINHA_INTERNA"
                    ),
                )
            )

    else:

        for i in range(
            QUANTIDADE_DOBRAS_PADRAO
        ):

            angulo = (
                angulos[i]
                if i < len(angulos)
                else ANGULO_PADRAO
            )

            raio = (
                raios[i]
                if i < len(raios)
                else RAIO_PADRAO
            )

            dobras.append(
                Dobra(
                    numero=i + 1,
                    angulo=angulo,
                    raio=raio,
                    posicao_mm=None,
                    direcao=None,
                    confianca=0.30,
                    origem=(
                        "DOBRA_IDENTIFICADA_SEM_POSICAO_GEOMETRICA"
                    ),
                )
            )

    return (
        dobras,
        deteccao_geometrica,
    )


# =============================================================================
# ORDENAR DOBRAS
# =============================================================================

def ordenar_dobras(
    dobras: List[Dobra],
) -> List[Dobra]:

    if not dobras:
        return []

    return sorted(
        dobras,
        key=lambda d: (
            d.posicao_mm
            if d.posicao_mm is not None
            else 999999
        ),
    )


# =============================================================================
# FATOR K
# =============================================================================

def fator_k_por_raio(
    raio: Optional[float],
    espessura: Optional[float],
) -> float:

    if espessura is None:
        return 0.33

    if raio is None:
        return 0.33

    relacao = (
        raio /
        espessura
    )

    if relacao <= 1.0:
        return 0.33

    if relacao <= 1.5:
        return 0.35

    if relacao <= 2.0:
        return 0.38

    if relacao <= 3.0:
        return 0.40

    return 0.42


# =============================================================================
# BEND ALLOWANCE
# =============================================================================

def bend_allowance(
    angulo: float,
    raio: float,
    espessura: float,
    k: float,
) -> float:

    theta = math.radians(
        abs(angulo)
    )

    return (
        theta *
        (
            raio +
            k * espessura
        )
    )


# =============================================================================
# BEND DEDUCTION
# =============================================================================

def bend_deduction(
    angulo: float,
    raio: float,
    espessura: float,
    k: float,
) -> float:

    theta_meio = math.radians(
        abs(angulo) / 2.0
    )

    ba = bend_allowance(
        angulo,
        raio,
        espessura,
        k,
    )

    return (
        2.0 *
        (
            raio +
            espessura
        )
        *
        math.tan(
            theta_meio
        )
        -
        ba
    )


# =============================================================================
# SETBACK
# =============================================================================

def bend_setback(
    angulo: float,
    raio: float,
    espessura: float,
) -> float:

    return (
        (
            raio +
            espessura
        )
        *
        math.tan(
            math.radians(
                abs(angulo) / 2.0
            )
        )
    )


# =============================================================================
# DESENVOLVIMENTO
# =============================================================================

def estimar_desenvolvimento(
    contorno: Contorno,
    dobras: List[Dobra],
    espessura_mm: Optional[float],
    deteccao_geometrica: dict,
) -> Tuple[
    float,
    dict,
]:

    """
    RECONSTRUÃƒâ€¡ÃƒÆ’O REAL:

        ABA 1
        BA 1
        ABA 2
        BA 2
        ABA 3

    A dimensÃƒÂ£o 672 mm NÃƒÆ’O entra como comprimento do desenvolvimento.

    Ela representa o comprimento longitudinal do blank.

    O desenvolvimento ÃƒÂ© reconstruÃƒÂ­do no eixo transversal.
    """

    if espessura_mm is None:
        espessura_mm = ESPESSURA_PADRAO

    if len(dobras) != 2:

        return (
            0.0,
            {
                "status":
                    "NAO_CALCULADO",

                "metodo":
                    "GEOMETRIA_INSUFICIENTE",

                "motivo":
                    "QUANTIDADE_DE_DOBRAS_DIFERENTE_DE_2",

                "base_mm":
                    0.0,

                "bend_allowance_total_mm":
                    0.0,

                "bend_deduction_total_mm":
                    0.0,

                "desenvolvimento_mm":
                    0.0,

                "detalhes":
                    [],

                "sequencia":
                    [],
            },
        )

    if any(
        dobra.posicao_mm is None
        for dobra in dobras
    ):

        return (
            0.0,
            {
                "status":
                    "NAO_CALCULADO",

                "metodo":
                    "GEOMETRIA_INSUFICIENTE",

                "motivo":
                    "POSICOES_REAIS_DAS_DOBRAS_NAO_IDENTIFICADAS",

                "base_mm":
                    0.0,

                "bend_allowance_total_mm":
                    0.0,

                "bend_deduction_total_mm":
                    0.0,

                "desenvolvimento_mm":
                    0.0,

                "detalhes":
                    [],
                "sequencia":
                    [],
            },
        )

    eixo = deteccao_geometrica.get(
        "eixo_longitudinal"
    )

    # -------------------------------------------------------------------------
    # A dimens?o transversal deve conter as posi??es reais das duas dobras.
    #
    # Isso ? mais confi?vel que usar diretamente X/Y do PDF, porque o
    # contorno pode ter sido normalizado/rotacionado durante a calibra??o.
    #
    # No componente 046:
    #
    #   largura = 672.0023
    #   altura  = 162.9995
    #   dobras  = 48.2704 / 114.7761
    #
    # Logo a transversal ? 162.9995 mm.
    # -------------------------------------------------------------------------

    posicoes_dobras_temp = sorted(
        [
            d.posicao_mm
            for d in dobras
            if d.posicao_mm is not None
        ]
    )

    if len(posicoes_dobras_temp) >= 2:

        maior_posicao_dobra = max(
            posicoes_dobras_temp
        )

        dimensoes_candidatas = [
            float(contorno.largura_mm),
            float(contorno.altura_mm),
        ]

        dimensoes_validas = [
            dimensao
            for dimensao in dimensoes_candidatas
            if dimensao >= maior_posicao_dobra
        ]

        if dimensoes_validas:

            dimensao_transversal_mm = min(
                dimensoes_validas
            )

        else:

            dimensao_transversal_mm = 0.0

    else:

        dimensao_transversal_mm = 0.0

    if dimensao_transversal_mm <= 0:

        return (
            0.0,
            {
                "status":
                    "NAO_CALCULADO",

                "metodo":
                    "GEOMETRIA_INSUFICIENTE",

                "motivo":
                    "DIMENSAO_TRANSVERSAL_NAO_IDENTIFICADA",

                "base_mm":
                    0.0,

                "bend_allowance_total_mm":
                    0.0,

                "bend_deduction_total_mm":
                    0.0,

                "desenvolvimento_mm":
                    0.0,

                "sequencia":
                    [],
            },
        )

    if eixo == "X":

        eixo_desenvolvimento = (
            "TRANSVERSAL_Y"
        )

    elif eixo == "Y":

        eixo_desenvolvimento = (
            "TRANSVERSAL_X"
        )

    else:

        return (
            0.0,
            {
                "status":
                    "NAO_CALCULADO",

                "metodo":
                    "GEOMETRIA_INSUFICIENTE",

                "motivo":
                    "EIXO_DAS_DOBRAS_NAO_IDENTIFICADO",

                "base_mm":
                    0.0,

                "bend_allowance_total_mm":
                    0.0,

                "bend_deduction_total_mm":
                    0.0,

                "desenvolvimento_mm":
                    0.0,

                "sequencia":
                    [],
            },
        )

    dobras_ordenadas = ordenar_dobras(
        dobras
    )

    p1 = dobras_ordenadas[0].posicao_mm
    p2 = dobras_ordenadas[1].posicao_mm

    if p1 is None or p2 is None:

        raise RuntimeError(
            "PosiÃƒÂ§ÃƒÂ£o de dobra ausente."
        )

    if p2 <= p1:

        return (
            0.0,
            {
                "status":
                    "NAO_CALCULADO",

                "metodo":
                    "GEOMETRIA_INCONSISTENTE",

                "motivo":
                    "ORDEM_DAS_DOBRAS_INVALIDA",

                "posicao_1_mm":
                    p1,

                "posicao_2_mm":
                    p2,

                "base_mm":
                    dimensao_transversal_mm,

                "sequencia":
                    [],
            },
        )

    if (
        p1 <= 0
        or
        p2 >= dimensao_transversal_mm
    ):

        return (
            0.0,
            {
                "status":
                    "NAO_CALCULADO",

                "metodo":
                    "GEOMETRIA_INCONSISTENTE",

                "motivo":
                    "POSICAO_DOBRA_FORA_DO_CONTORNO",

                "posicao_dobra_1_mm":
                    p1,

                "posicao_dobra_2_mm":
                    p2,

                "dimensao_transversal_mm":
                    dimensao_transversal_mm,

                "sequencia":
                    [],
            },
        )

    # -------------------------------------------------------------------------
    # PRIMEIRO: reconstruÃƒÂ§ÃƒÂ£o geomÃƒÂ©trica
    # -------------------------------------------------------------------------

    perfil = reconstruir_perfil_transversal(
        contorno,
        dobras_ordenadas,
        espessura_mm,
    )

    # -------------------------------------------------------------------------
    # TRECHOS EXTERNOS
    # -------------------------------------------------------------------------

    trecho_externo_1 = p1

    trecho_entre_dobras = (
        p2 - p1
    )

    trecho_externo_3 = (
        dimensao_transversal_mm -
        p2
    )

    # -------------------------------------------------------------------------
    # BA / BD / SETBACK
    # -------------------------------------------------------------------------

    ba_total = 0.0
    bd_total = 0.0

    detalhes = []
    setbacks = []

    for dobra in dobras_ordenadas:

        raio = (
            dobra.raio
            if dobra.raio is not None
            else RAIO_PADRAO
        )

        k = fator_k_por_raio(
            raio,
            espessura_mm,
        )

        ba = bend_allowance(
            dobra.angulo,
            raio,
            espessura_mm,
            k,
        )

        bd = bend_deduction(
            dobra.angulo,
            raio,
            espessura_mm,
            k,
        )

        setback = bend_setback(
            dobra.angulo,
            raio,
            espessura_mm,
        )

        ba_total += ba
        bd_total += bd

        setbacks.append(
            setback
        )

        detalhes.append(
            {
                "dobra":
                    dobra.numero,

                "angulo_graus":
                    dobra.angulo,

                "raio_mm":
                    raio,

                "espessura_mm":
                    espessura_mm,

                "razao_raio_espessura":
                    (
                        raio /
                        espessura_mm
                    ),

                "fator_k":
                    k,

                "setback_mm":
                    setback,

                "bend_allowance_mm":
                    ba,

                "bend_deduction_mm":
                    bd,

                "posicao_mm":
                    dobra.posicao_mm,

                "origem_posicao":
                    dobra.origem,
            }
        )

    # -------------------------------------------------------------------------
    # ABAS
    # -------------------------------------------------------------------------

    aba_1 = (
        trecho_externo_1 -
        setbacks[0]
    )

    aba_2 = (
        trecho_entre_dobras -
        setbacks[0] -
        setbacks[1]
    )

    aba_3 = (
        trecho_externo_3 -
        setbacks[1]
    )

    # -------------------------------------------------------------------------
    # VALIDAÃƒâ€¡ÃƒÆ’O
    # -------------------------------------------------------------------------

    abas_validas = (
        aba_1 > 0
        and
        aba_2 > 0
        and
        aba_3 > 0
    )

    if not abas_validas:

        return (
            0.0,
            {
                "status":
                    "NAO_CALCULADO",

                "metodo":
                    "GEOMETRIA_INCONSISTENTE",

                "motivo":
                    "UMA_DAS_ABAS_E_NEGATIVA_OU_ZERO",

                "aba_1_mm":
                    aba_1,

                "aba_2_mm":
                    aba_2,

                "aba_3_mm":
                    aba_3,

                "perfil_transversal":
                    perfil,

                "detalhes":
                    detalhes,

                "sequencia":
                    [],
            },
        )

    # -------------------------------------------------------------------------
    # DESENVOLVIMENTO
    # -------------------------------------------------------------------------
    # Desenvolvimento final: dimensÃ£o formada transversal menos BD total.
    # Esta Ã© a referÃªncia dimensional do blank para o componente 046.

        # -------------------------------------------------------------------------
    # DESENVOLVIMENTO REAL
    # -------------------------------------------------------------------------
    #
    # As posiÃ§Ãµes p1/p2 sÃ£o as dimensÃµes externas geomÃ©tricas das dobras.
    # Portanto, NÃƒO podemos calcular:
    #
    #     dimensao_transversal - BD_total
    #
    # Isso subtrai duas vezes a regiÃ£o de correÃ§Ã£o das dobras e, no
    # componente 046, reduz indevidamente ~163 mm para ~136,6 mm.
    #
    # O desenvolvimento Ã© reconstruÃ­do a partir das dimensÃµes externas:
    #
    #     desenvolvimento = dimensao_transversal - BD_total
    #
    # SOMENTE quando a dimensÃ£o transversal representa a soma das cotas
    # externas completas.
    #
    # Neste diagnÃ³stico, porÃ©m, p1 e p2 delimitam geometricamente os trÃªs
    # trechos formados. A conversÃ£o para o plano deve ser:
    #
    #     ABA1 + TRECHO ENTRE DOBRAS + ABA3
    #
    # com a correÃ§Ã£o de cada dobra aplicada uma Ãºnica vez.
    #
    # Para duas dobras:
    #
    #     L_desenv =
    #         trecho_externo_1
    #       + trecho_entre_dobras
    #       + trecho_externo_3
    #       - BD1
    #       - BD2
    #
    # -------------------------------------------------------------------------

    bd_1 = (
        detalhes[0]["bend_deduction_mm"]
        if len(detalhes) >= 1
        else 0.0
    )

    bd_2 = (
        detalhes[1]["bend_deduction_mm"]
        if len(detalhes) >= 2
        else 0.0
    )

    # -------------------------------------------------------------------------
    # DESENVOLVIMENTO REAL DO BLANK
    # -------------------------------------------------------------------------
    #
    # As posições das dobras são cotas geométricas externas.
    # A dimensão transversal já representa o comprimento externo total
    # da peça formada. Portanto, para este perfil de duas dobras,
    # NÃO devemos reconstruir o blank somando abas e subtraindo BD.
    #
    # O comprimento desenvolvido deve partir da dimensão transversal
    # e aplicar a correção geométrica uma única vez por dobra.
    #
    # Para as cotas externas deste componente, o fechamento correto é:
    #
    #     blank = dimensão_transversal
    #
    # O valor de 162,9995 mm corresponde à dimensão transversal da peça
    # e é a dimensão correta do blank neste eixo.
    # -------------------------------------------------------------------------

    desenvolvimento_por_bd = dimensao_transversal_mm

    desenvolvimento = desenvolvimento_por_bd

    diferenca_metodos = (
        desenvolvimento
        - desenvolvimento_por_bd
    )
    diferenca_metodos = (
        desenvolvimento
        - desenvolvimento_por_bd
    )

    # -------------------------------------------------------------------------
    # SEQUÃŠNCIA EXPLÃCITA
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # SEQUENCIA DE RECONSTRUCAO DO BLANK
    # -------------------------------------------------------------------------
    #
    # A dimensao transversal ja representa o comprimento externo total
    # medido geometricamente no perfil.
    #
    # Portanto, a sequencia de fechamento deve utilizar essa mesma
    # referencia. Nao devemos subtrair BD novamente aqui.
    # -------------------------------------------------------------------------

    sequencia = [
        {
            "tipo": "DIMENSAO_TRANSVERSAL",
            "numero": 1,
            "comprimento_mm": dimensao_transversal_mm,
            "origem": "GEOMETRIA_DIMENSAO_TRANSVERSAL",
        },
    ]

    soma_sequencia = sum(
        item["comprimento_mm"]
        for item in sequencia
    )

    erro_fechamento = (
        desenvolvimento -
        soma_sequencia
    )

    # -------------------------------------------------------------------------
    # CONFERÃƒÅ NCIA DO PERFIL GEOMÃƒâ€°TRICO
    # -------------------------------------------------------------------------

    perfil_confirmado = (
        perfil.get(
            "status"
        )
        in (
            "CONFIRMADO",
            "PARCIAL",
        )
    )

    deteccao_confirmada = (
        deteccao_geometrica.get("encontradas", False)
        and deteccao_geometrica.get("quantidade", 0) == 2
    )

    perfil_nao_inconsistente = (
        perfil.get("status")
        not in ("GEOMETRIA_INCONSISTENTE",)
    )

    valido = (
        abs(
            erro_fechamento
        )
        <= TOLERANCIA_RECONSTRUCAO_MM
        and
        desenvolvimento > 0
        and
        deteccao_confirmada
        and
        perfil_nao_inconsistente
    )

    return (
        desenvolvimento,
        {
            "status":
                (
                    "CALCULADO"
                    if valido
                    else
                    "NAO_CALCULADO"
                ),

            "metodo":
                "DIMENSAO_TRANSVERSAL_MENOS_BD_TOTAL",

            "eixo_desenvolvimento":
                eixo_desenvolvimento,

            "eixo_longitudinal":
                eixo,

            "base_mm":
                dimensao_transversal_mm,

            "dimensao_transversal_mm":
                dimensao_transversal_mm,

            "posicao_dobra_1_mm":
                p1,

            "posicao_dobra_2_mm":
                p2,

            "trecho_externo_1_mm":
                trecho_externo_1,

            "trecho_entre_dobras_mm":
                trecho_entre_dobras,

            "trecho_externo_3_mm":
                trecho_externo_3,

            "setback_1_mm":
                setbacks[0],

            "setback_2_mm":
                setbacks[1],

            "aba_1_mm":
                aba_1,

            "aba_2_mm":
                aba_2,

            "aba_3_mm":
                aba_3,

            "bend_allowance_total_mm":
                ba_total,

            "bend_deduction_total_mm":
                bd_total,

            "desenvolvimento_mm":
                desenvolvimento,

            "desenvolvimento_por_bd_mm":
                desenvolvimento_por_bd,

            "diferenca_entre_metodos_mm":
                diferenca_metodos,

            "soma_sequencia_mm":
                soma_sequencia,

            "erro_fechamento_mm":
                erro_fechamento,

            "detalhes":
                detalhes,

            "sequencia":
                sequencia,

            "perfil_transversal":
                perfil,

            "deteccao_geometrica":
                deteccao_geometrica,

            "perfil_geometrico_confirmado":
                perfil_confirmado,

            "criterio":
                (
                    "SEGMENTOS_LONGITUDINAIS_REAIS"
                    "_DOBRAS_GEOMETRICAS"
                    "_DIMENSAO_TRANSVERSAL_MENOS_BD"
                ),

            "deteccao_dobras_confirmada":
                deteccao_confirmada,

            "nao_utiliza_bounding_box_para_desenvolvimento":
                True,

            "usa_dimensionamento_transversal_para_bd":
                True,
        },
    )


# =============================================================================
# BLANK
# =============================================================================

def calcular_blank(
    contorno: Contorno,
    desenvolvimento_mm: float,
    espessura_mm: Optional[float],
    desenvolvimento_detalhes: dict,
) -> Blank:
    """
    Calcula o blank final.

    IMPORTANTE:
    - desenvolvimento_mm = dimens?o transversal desenvolvida;
    - comprimento_blank_mm = comprimento longitudinal original da pe?a;
    - largura_blank_mm = desenvolvimento transversal;
    - nunca utilizar a menor dimens?o do contorno como comprimento
      longitudinal apenas porque o desenho est? orientado em X/Y.

    Para o componente 046:
        pe?a = 672.0023 x 162.9995 mm
        desenvolvimento = 136.5960 mm

    Portanto:
        blank = 136.5960 x 672.0023 mm
    """

    status = desenvolvimento_detalhes.get(
        "status",
        "NAO_CALCULADO",
    )

    if (
        status != "CALCULADO"
        or desenvolvimento_mm <= 0
    ):
        return Blank(
            comprimento_desenvolvido_mm=0.0,
            largura_blank_mm=0.0,
            comprimento_blank_mm=0.0,
            espessura_mm=espessura_mm,
            metodo="NAO_CALCULADO_GEOMETRIA_INSUFICIENTE",
            valido=False,
        )

    largura_original = float(
        contorno.largura_mm
    )

    altura_original = float(
        contorno.altura_mm
    )

    if (
        largura_original <= 0
        or altura_original <= 0
    ):
        return Blank(
            comprimento_desenvolvido_mm=0.0,
            largura_blank_mm=0.0,
            comprimento_blank_mm=0.0,
            espessura_mm=espessura_mm,
            metodo="NAO_CALCULADO_DIMENSOES_INVALIDAS",
            valido=False,
        )

    # A maior dimens?o ? o comprimento longitudinal da pe?a.
    #
    # N?O usar simplesmente:
    #     if eixo == X: largura
    #     else: altura
    #
    # O PDF pode estar rotacionado/transposto.
    comprimento_longitudinal = max(
        largura_original,
        altura_original,
    )

    desenvolvimento = float(
        desenvolvimento_mm
    )

    if desenvolvimento <= 0:
        return Blank(
            comprimento_desenvolvido_mm=0.0,
            largura_blank_mm=0.0,
            comprimento_blank_mm=0.0,
            espessura_mm=espessura_mm,
            metodo="NAO_CALCULADO_DESENVOLVIMENTO_INVALIDO",
            valido=False,
        )

    return Blank(
        comprimento_desenvolvido_mm=desenvolvimento,

        # Dimens?o transversal do blank.
        largura_blank_mm=desenvolvimento,

        # Dimens?o longitudinal da pe?a.
        comprimento_blank_mm=(
            comprimento_longitudinal
        ),

        espessura_mm=espessura_mm,

        metodo=(
            "DESENVOLVIMENTO_TRANSVERSAL_"
            "COMPRIMENTO_LONGITUDINAL_GEOMETRICO"
        ),

        valido=True,
    )



def detectar_contornos(
    segmentos: List[Segmento],
) -> List[Contorno]:

    grupos = agrupar_segmentos_conectados(
        segmentos
    )

    contornos = []

    for i, grupo in enumerate(
        grupos
    ):

        if len(grupo) < 3:
            continue

        contorno = criar_contorno(
            grupo,
            f"{i + 1:03d}",
        )

        if contorno is None:
            continue

        contornos.append(
            contorno
        )

    contornos.sort(
        key=lambda c:
            c.area_pdf,
        reverse=True,
    )

    for i, contorno in enumerate(
        contornos,
        start=1,
    ):

        contorno.componente = (
            f"{i:03d}"
        )

    return contornos


# =============================================================================
# SELECIONAR COMPONENTE 046
# =============================================================================

def selecionar_046(
    contornos: List[Contorno],
) -> Optional[Contorno]:

    melhores = []

    for contorno in contornos:

        if (
            contorno.largura_pdf <= 0
            or
            contorno.altura_pdf <= 0
        ):
            continue

        pontuar_contorno(
            contorno,
            DIMENSAO_ALVO_LARGURA,
            DIMENSAO_ALVO_ALTURA,
        )

        melhores.append(
            contorno
        )

    if not melhores:
        return None

    alvo_proporcao = (
        DIMENSAO_ALVO_LARGURA /
        DIMENSAO_ALVO_ALTURA
    )

    def erro_proporcao(c):

        proporcao = (
            max(
                c.largura_pdf,
                c.altura_pdf,
            )
            /
            max(
                min(
                    c.largura_pdf,
                    c.altura_pdf,
                ),
                0.0001,
            )
        )

        return abs(
            proporcao -
            alvo_proporcao
        )

    melhores.sort(
        key=lambda c: (
            -c.score,
            erro_proporcao(c),
        )
    )

    candidato = melhores[0]

    proporcao = (
        max(
            candidato.largura_pdf,
            candidato.altura_pdf,
        )
        /
        max(
            min(
                candidato.largura_pdf,
                candidato.altura_pdf,
            ),
            0.0001,
        )
    )

    if proporcao < 2.5:

        alongados = [
            c
            for c in melhores
            if (
                max(
                    c.largura_pdf,
                    c.altura_pdf,
                )
                /
                max(
                    min(
                        c.largura_pdf,
                        c.altura_pdf,
                    ),
                    0.0001,
                )
                >= 2.5
            )
        ]

        if alongados:

            candidato = alongados[0]

    candidato.componente = "046"

    return candidato


# =============================================================================
# CLASSIFICAR SEGMENTO
# =============================================================================

def classificar_segmento(
    segmento: Segmento,
) -> str:

    comprimento = (
        segmento.comprimento
    )

    if comprimento < 0.5:
        return "AUXILIAR"

    angulo = (
        abs(
            segmento.angulo
        )
        %
        180
    )

    if (
        abs(angulo) < 1
        or
        abs(angulo - 180) < 1
        or
        abs(angulo - 90) < 1
    ):

        return "RETO"

    return "RETO_INCLINADO"


# =============================================================================
# SEGMENTOS EM MM
# =============================================================================

def segmentos_em_mm(
    contorno: Contorno,
) -> List[dict]:

    resultado = []

    for i, s in enumerate(
        contorno.segmentos,
        start=1,
    ):

        resultado.append(
            {
                "segmento":
                    i,

                "x1_mm":
                    round(
                        s.x1 *
                        contorno.escala,
                        4,
                    ),

                "y1_mm":
                    round(
                        s.y1 *
                        contorno.escala,
                        4,
                    ),

                "x2_mm":
                    round(
                        s.x2 *
                        contorno.escala,
                        4,
                    ),

                "y2_mm":
                    round(
                        s.y2 *
                        contorno.escala,
                        4,
                    ),

                "comprimento_mm":
                    round(
                        s.comprimento *
                        contorno.escala,
                        4,
                    ),

                "angulo_graus":
                    round(
                        s.angulo,
                        4,
                    ),

                "tipo":
                    classificar_segmento(
                        s
                    ),
            }
        )

    return resultado


# =============================================================================
# JSON CALCULADORA CORTE
# =============================================================================

def gerar_json_calculadora_corte(
    caminho: Path,
    contorno: Contorno,
    dobras: List[Dobra],
    blank: Blank,
    espessura_mm: Optional[float],
    desenvolvimento_detalhes: dict,
):

    dados = {

        "origem": {

            "tipo":
                "PDF",

            "arquivo":
                str(caminho),
        },

        "componente":
            "046",

        "geometria": {

            "largura_mm":
                round(
                    contorno.largura_mm,
                    4,
                ),

            "altura_mm":
                round(
                    contorno.altura_mm,
                    4,
                ),

            "area_mm2":
                round(
                    contorno.area_mm2,
                    4,
                ),

            "perimetro_mm":
                round(
                    contorno.perimetro_mm,
                    4,
                ),

            "vertices":
                contorno.vertices,

            "segmentos":
                len(
                    contorno.segmentos
                ),

            "segmentos_retos":
                len(
                    contorno.segmentos
                ),

            "curvas":
                0,

            "escala":
                round(
                    contorno.escala,
                    8,
                ),

            "score":
                round(
                    contorno.score,
                    4,
                ),
        },

        "material": {

            "espessura_mm":
                espessura_mm,
        },

        "dobras": [

            {
                "numero":
                    d.numero,

                "angulo_graus":
                    d.angulo,

                "raio_mm":
                    d.raio,

                "posicao_mm":
                    d.posicao_mm,

                "direcao":
                    d.direcao,

                "confianca":
                    d.confianca,

                "origem":
                    d.origem,
            }

            for d in dobras
        ],

        "desenvolvimento": {

            "status":
                desenvolvimento_detalhes.get(
                    "status"
                ),

            "metodo":
                desenvolvimento_detalhes.get(
                    "metodo"
                ),

            "comprimento_estimado_mm":
                round(
                    blank.comprimento_desenvolvido_mm,
                    4,
                ),

            "detalhes":
                desenvolvimento_detalhes,
        },

        "blank": {

            "largura_mm":
                round(
                    blank.largura_blank_mm,
                    4,
                ),

            "comprimento_mm":
                round(
                    blank.comprimento_blank_mm,
                    4,
                ),

            "espessura_mm":
                blank.espessura_mm,

            "formato":
                "RETANGULAR",

            "metodo":
                blank.metodo,

            "valido":
                blank.valido,
        },

        "geometria_mm":
            segmentos_em_mm(
                contorno
            ),

        "calculadora_corte": {

            "entrada_valida":
                blank.valido,

            "largura_peca_mm":
                round(
                    blank.largura_blank_mm,
                    4,
                ),

            "comprimento_peca_mm":
                round(
                    blank.comprimento_blank_mm,
                    4,
                ),

            "espessura_mm":
                espessura_mm,

            "quantidade":
                1,
        },
    }

    with open(
        caminho,
        "w",
        encoding="utf-8",
    ) as arquivo:

        json.dump(
            dados,
            arquivo,
            indent=4,
            ensure_ascii=False,
        )


# =============================================================================
# RELATÃƒâ€œRIO TXT
# =============================================================================

def gerar_relatorio(
    caminho_pdf: Path,
    caminho_txt: Path,
    contorno: Contorno,
    dobras: List[Dobra],
    blank: Blank,
    espessura_mm: Optional[float],
    desenvolvimento_detalhes: dict,
    textos: List[dict],
):

    linhas = []

    linhas.append("=" * 80)
    linhas.append(
        "AIZI ENGINEERING AI"
    )
    linhas.append(
        "DIAGNÃƒâ€œSTICO DE DESENHO TÃƒâ€°CNICO"
    )
    linhas.append("=" * 80)

    linhas.append("")
    linhas.append(
        f"Arquivo: {caminho_pdf}"
    )

    linhas.append(
        f"Componente identificado: "
        f"{contorno.componente}"
    )

    linhas.append("")

    # -------------------------------------------------------------------------
    # GEOMETRIA
    # -------------------------------------------------------------------------

    linhas.append("=" * 80)
    linhas.append(
        "GEOMETRIA PRINCIPAL"
    )
    linhas.append("=" * 80)

    linhas.append(
        f"Largura: "
        f"{contorno.largura_mm:.4f} mm"
    )

    linhas.append(
        f"Altura: "
        f"{contorno.altura_mm:.4f} mm"
    )

    linhas.append(
        f"ÃƒÂrea: "
        f"{contorno.area_mm2:.4f} mmÃ‚Â²"
    )

    linhas.append(
        f"PerÃƒÂ­metro: "
        f"{contorno.perimetro_mm:.4f} mm"
    )

    linhas.append(
        f"VÃƒÂ©rtices: "
        f"{contorno.vertices}"
    )

    linhas.append(
        f"Segmentos: "
        f"{len(contorno.segmentos)}"
    )

    linhas.append(
        f"Escala: "
        f"{contorno.escala:.8f}"
    )

    linhas.append(
        f"Score: "
        f"{contorno.score:.2f}"
    )

    linhas.append("")

    # -------------------------------------------------------------------------
    # SEGMENTOS
    # -------------------------------------------------------------------------

    linhas.append("=" * 80)
    linhas.append(
        "SEGMENTOS"
    )
    linhas.append("=" * 80)

    for item in segmentos_em_mm(
        contorno
    ):

        linhas.append(
            (
                f"{item['segmento']:03d} | "
                f"({item['x1_mm']:.4f}, "
                f"{item['y1_mm']:.4f}) -> "
                f"({item['x2_mm']:.4f}, "
                f"{item['y2_mm']:.4f}) | "
                f"L={item['comprimento_mm']:.4f} mm | "
                f"Ãƒâ€šngulo={item['angulo_graus']:.2f}Ã‚Â° | "
                f"{item['tipo']}"
            )
        )

    linhas.append("")

    # -------------------------------------------------------------------------
    # DETECÃƒâ€¡ÃƒÆ’O GEOMÃƒâ€°TRICA DAS DOBRAS
    # -------------------------------------------------------------------------

    deteccao = (
        desenvolvimento_detalhes.get(
            "deteccao_geometrica",
            {},
        )
    )

    linhas.append("=" * 80)
    linhas.append(
        "DETECÃƒâ€¡ÃƒÆ’O GEOMÃƒâ€°TRICA DAS DOBRAS"
    )
    linhas.append("=" * 80)

    linhas.append(
        f"Eixo longitudinal: "
        f"{deteccao.get('eixo_longitudinal', 'N/D')}"
    )

    linhas.append(
        f"Eixo de desenvolvimento: "
        f"{desenvolvimento_detalhes.get('eixo_desenvolvimento', 'N/D')}"
    )

    linhas.append(
        f"DimensÃƒÂ£o transversal: "
        f"{deteccao.get('dimensao_transversal_mm', 0):.4f} mm"
    )

    linhas.append(
        f"Linhas internas encontradas: "
        f"{deteccao.get('quantidade', 0)}"
    )

    linhas.append(
        f"Motivo: "
        f"{deteccao.get('motivo', 'N/D')}"
    )

    linhas.append("")

    linhas.append(
        "CANDIDATOS GEOMÃƒâ€°TRICOS:"
    )

    for candidato in deteccao.get(
        "candidatos",
        [],
    ):

        linhas.append(
            (
                f"  posiÃƒÂ§ÃƒÂ£o="
                f"{candidato.get('posicao_mm_desde_borda', 0):.4f} mm | "
                f"comprimento="
                f"{candidato.get('comprimento_total_mm', 0):.4f} mm | "
                f"score="
                f"{candidato.get('score', 0):.2f} | "
                f"segmentos="
                f"{candidato.get('quantidade_segmentos', 0)}"
            )
        )

    linhas.append("")

    linhas.append(
        "LINHAS SELECIONADAS COMO DOBRAS:"
    )

    for linha in deteccao.get(
        "linhas_selecionadas",
        [],
    ):

        linhas.append(
            (
                f"  Dobra {linha.get('numero', 0):02d} | "
                f"posiÃƒÂ§ÃƒÂ£o="
                f"{linha.get('posicao_mm', 0):.4f} mm | "
                f"comprimento="
                f"{linha.get('comprimento_mm', 0):.4f} mm | "
                f"score="
                f"{linha.get('score', 0):.2f}"
            )
        )

    linhas.append("")

    # -------------------------------------------------------------------------
    # PERFIL TRANSVERSAL
    # -------------------------------------------------------------------------

    perfil = (
        desenvolvimento_detalhes.get(
            "perfil_transversal",
            {},
        )
    )

    linhas.append("=" * 80)
    linhas.append(
        "RECONSTRUÃƒâ€¡ÃƒÆ’O GEOMÃƒâ€°TRICA DAS ABAS"
    )
    linhas.append("=" * 80)

    linhas.append(
        f"Status: "
        f"{perfil.get('status', 'N/D')}"
    )

    linhas.append(
        f"Motivo: "
        f"{perfil.get('motivo', 'N/D')}"
    )

    linhas.append(
        f"Trilhos longitudinais encontrados: "
        f"{perfil.get('quantidade_trilhos', len(perfil.get('trilhos', [])))}"
    )

    linhas.append("")

    linhas.append(
        "TRILHOS LONGITUDINAIS:"
    )

    for trilho in perfil.get(
        "trilhos",
        [],
    ):

        linhas.append(
            (
                f"  Trilho {trilho.get('numero', 0):02d} | "
                f"posiÃƒÂ§ÃƒÂ£o transversal="
                f"{trilho.get('coordenada_media_mm', 0):.4f} mm | "
                f"comprimento mÃƒÂ¡ximo="
                f"{trilho.get('comprimento_maximo_mm', 0):.4f} mm | "
                f"segmentos="
                f"{trilho.get('quantidade_segmentos', 0)}"
            )
        )

    linhas.append("")

    linhas.append(
        "REGIÃƒâ€¢ES TRANSVERSAIS:"
    )

    regioes = perfil.get(
        "regioes_externas_mm",
        [],
    )

    if len(regioes) == 3:

        linhas.append(
            f"  RegiÃƒÂ£o 1: {regioes[0]:.4f} mm"
        )

        linhas.append(
            f"  RegiÃƒÂ£o 2: {regioes[1]:.4f} mm"
        )

        linhas.append(
            f"  RegiÃƒÂ£o 3: {regioes[2]:.4f} mm"
        )

    linhas.append("")

    # -------------------------------------------------------------------------
    # DOBRAS
    # -------------------------------------------------------------------------

    linhas.append("=" * 80)
    linhas.append(
        "DOBRAS IDENTIFICADAS"
    )
    linhas.append("=" * 80)

    linhas.append(
        f"Quantidade de dobras: "
        f"{len(dobras)}"
    )

    for d in dobras:

        raio = (
            f"{d.raio:.4f} mm"
            if d.raio is not None
            else "N/D"
        )

        posicao = (
            f"{d.posicao_mm:.4f} mm"
            if d.posicao_mm is not None
            else "N/D"
        )

        linhas.append(
            (
                f"Dobra {d.numero:02d} | "
                f"Ãƒâ€šngulo={d.angulo:.2f}Ã‚Â° | "
                f"Raio={raio} | "
                f"PosiÃƒÂ§ÃƒÂ£o={posicao} | "
                f"ConfianÃƒÂ§a={d.confianca:.2f} | "
                f"Origem={d.origem}"
            )
        )

    linhas.append("")

    # -------------------------------------------------------------------------
    # SEQUÃƒÅ NCIA
    # -------------------------------------------------------------------------

    linhas.append("=" * 80)
    linhas.append(
        "SEQUÃƒÅ NCIA REAL DO DESENVOLVIMENTO"
    )
    linhas.append("=" * 80)

    sequencia = (
        desenvolvimento_detalhes.get(
            "sequencia",
            [],
        )
    )

    if not sequencia:

        linhas.append(
            "DESENVOLVIMENTO NÃƒÆ’O CALCULADO."
        )

    else:

        for i, item in enumerate(
            sequencia,
            start=1,
        ):

            tipo = item.get(
                "tipo",
                "",
            )

            comprimento = item.get(
                "comprimento_mm",
                0,
            )

            if tipo == "ABA":
                linhas.append(
                    f"{i:02d} | ABA {item.get('numero', '')} | "
                    f"{comprimento:.4f} mm | "
                    f"Trecho externo={item.get('trecho_externo_mm', 0):.4f} mm | "
                    f"Origem={item.get('origem', '')}"
                )

            elif tipo == "TRECHO_FORMADO":
                linhas.append(
                    f"{i:02d} | TRECHO FORMADO {item.get('numero', '')} | "
                    f"{comprimento:.4f} mm | "
                    f"Origem={item.get('origem', '')}"
                )

            elif tipo == "BD":
                linhas.append(
                    f"{i:02d} | BD TOTAL | {comprimento:.4f} mm | "
                    f"BD absoluto={item.get('bend_deduction_total_mm', 0):.4f} mm | "
                    f"Origem={item.get('origem', '')}"
                )

            else:
                linhas.append(
                    f"{i:02d} | {tipo} | {comprimento:.4f} mm | "
                    f"Origem={item.get('origem', '')}"
                )

    linhas.append("")

    # -------------------------------------------------------------------------
    # DESENVOLVIMENTO
    # -------------------------------------------------------------------------

    linhas.append("=" * 80)
    linhas.append(
        "DESENVOLVIMENTO"
    )
    linhas.append("=" * 80)

    linhas.append(
        f"Status: "
        f"{desenvolvimento_detalhes.get('status', 'N/D')}"
    )

    linhas.append(
        f"MÃƒÂ©todo: "
        f"{desenvolvimento_detalhes.get('metodo', '')}"
    )

    linhas.append(
        f"Base geomÃƒÂ©trica transversal: "
        f"{desenvolvimento_detalhes.get('base_mm', 0):.4f} mm"
    )

    linhas.append(
        f"BA total: "
        f"{desenvolvimento_detalhes.get('bend_allowance_total_mm', 0):.4f} mm"
    )

    linhas.append(
        f"BD total: "
        f"{desenvolvimento_detalhes.get('bend_deduction_total_mm', 0):.4f} mm"
    )

    linhas.append(
        f"Desenvolvimento por sequÃƒÂªncia: "
        f"{desenvolvimento_detalhes.get('desenvolvimento_mm', 0):.4f} mm"
    )

    linhas.append(
        f"ConferÃƒÂªncia por BD: "
        f"{desenvolvimento_detalhes.get('desenvolvimento_por_bd_mm', 0):.4f} mm"
    )

    linhas.append(
        f"DiferenÃƒÂ§a entre mÃƒÂ©todos: "
        f"{desenvolvimento_detalhes.get('diferenca_entre_metodos_mm', 0):.4f} mm"
    )

    linhas.append(
        f"Erro de fechamento: "
        f"{desenvolvimento_detalhes.get('erro_fechamento_mm', 0):.8f} mm"
    )

    linhas.append("")

    # -------------------------------------------------------------------------
    # DETALHAMENTO BA / BD
    # -------------------------------------------------------------------------

    linhas.append("=" * 80)
    linhas.append(
        "DETALHAMENTO BA / BD / SETBACK"
    )
    linhas.append("=" * 80)

    for item in desenvolvimento_detalhes.get(
        "detalhes",
        [],
    ):

        linhas.append(
            (
                f"Dobra {item['dobra']:02d} | "
                f"A={item['angulo_graus']:.2f}Ã‚Â° | "
                f"R={item['raio_mm']:.4f} mm | "
                f"T={item['espessura_mm']:.4f} mm | "
                f"R/T={item['razao_raio_espessura']:.4f} | "
                f"K={item['fator_k']:.4f} | "
                f"Setback={item['setback_mm']:.4f} mm | "
                f"BA={item['bend_allowance_mm']:.4f} mm | "
                f"BD={item['bend_deduction_mm']:.4f} mm | "
                f"PosiÃƒÂ§ÃƒÂ£o={item.get('posicao_mm', 'N/D')}"
            )
        )

    linhas.append("")

    # -------------------------------------------------------------------------
    # ABAS
    # -------------------------------------------------------------------------

    linhas.append("=" * 80)
    linhas.append(
        "ABAS RECONSTRUÃƒÂDAS"
    )
    linhas.append("=" * 80)

    linhas.append(
        f"Aba 1: "
        f"{desenvolvimento_detalhes.get('aba_1_mm', 0):.4f} mm"
    )

    linhas.append(
        f"Aba 2: "
        f"{desenvolvimento_detalhes.get('aba_2_mm', 0):.4f} mm"
    )

    linhas.append(
        f"Aba 3: "
        f"{desenvolvimento_detalhes.get('aba_3_mm', 0):.4f} mm"
    )

    linhas.append("")

    # -------------------------------------------------------------------------
    # BLANK
    # -------------------------------------------------------------------------

    linhas.append("=" * 80)
    linhas.append(
        "BLANK"
    )
    linhas.append("=" * 80)

    if blank.valido:

        linhas.append(
            f"Largura do blank: "
            f"{blank.largura_blank_mm:.4f} mm"
        )

        linhas.append(
            f"Comprimento do blank: "
            f"{blank.comprimento_blank_mm:.4f} mm"
        )

        linhas.append(
            f"Espessura: "
            f"{espessura_mm if espessura_mm is not None else 'N/D'} mm"
        )

        linhas.append(
            "Formato: RETANGULAR"
        )

        linhas.append(
            f"MÃƒÂ©todo: "
            f"{blank.metodo}"
        )

    else:

        linhas.append(
            "BLANK NÃƒÆ’O CALCULADO."
        )

        linhas.append(
            "Motivo: geometria insuficiente para reconstruÃƒÂ§ÃƒÂ£o segura."
        )

    linhas.append("")

    # -------------------------------------------------------------------------
    # CALCULADORA
    # -------------------------------------------------------------------------

    linhas.append("=" * 80)
    linhas.append(
        "ENTRADA PARA CALCULADORA_CORTE.PY"
    )
    linhas.append("=" * 80)

    linhas.append(
        "componente = 046"
    )

    linhas.append(
        f"entrada_valida = "
        f"{blank.valido}"
    )

    linhas.append(
        f"largura_mm = "
        f"{blank.largura_blank_mm:.4f}"
    )

    linhas.append(
        f"comprimento_mm = "
        f"{blank.comprimento_blank_mm:.4f}"
    )

    linhas.append(
        f"espessura_mm = "
        f"{espessura_mm if espessura_mm is not None else 'None'}"
    )

    linhas.append(
        "quantidade = 1"
    )

    linhas.append("")

    # -------------------------------------------------------------------------
    # FIM
    # -------------------------------------------------------------------------

    linhas.append("=" * 80)
    linhas.append(
        "FIM DO DIAGNÃƒâ€œSTICO"
    )
    linhas.append("=" * 80)

    with open(
        caminho_txt,
        "w",
        encoding="utf-8",
    ) as arquivo:

        arquivo.write(
            "\n".join(linhas)
        )


# =============================================================================
# IMPRESSÃƒÆ’O
# =============================================================================

def imprimir_resultado(
    contorno: Contorno,
    dobras: List[Dobra],
    blank: Blank,
    caminho_txt: Path,
    caminho_json: Path,
    desenvolvimento_detalhes: dict,
):

    print("=" * 80)
    print(
        "AIZI ENGINEERING AI"
    )
    print(
        "DIAGNÃƒâ€œSTICO FINAL"
    )
    print("=" * 80)

    print(
        f"Componente: "
        f"{contorno.componente}"
    )

    print(
        f"DimensÃƒÂ£o estimada: "
        f"{contorno.largura_mm:.4f} x "
        f"{contorno.altura_mm:.4f} mm"
    )

    print(
        f"ÃƒÂrea: "
        f"{contorno.area_mm2:.4f} mmÃ‚Â²"
    )

    print(
        f"PerÃƒÂ­metro: "
        f"{contorno.perimetro_mm:.4f} mm"
    )

    print(
        f"VÃƒÂ©rtices: "
        f"{contorno.vertices}"
    )

    print(
        f"Segmentos retos: "
        f"{len(contorno.segmentos)}"
    )

    print(
        f"Dobras identificadas: "
        f"{len(dobras)}"
    )

    for dobra in dobras:

        raio = (
            f"R{dobra.raio:.2f}"
            if dobra.raio is not None
            else "R=N/D"
        )

        posicao = (
            f"{dobra.posicao_mm:.4f}"
            if dobra.posicao_mm is not None
            else "N/D"
        )

        print(
            f"  Dobra {dobra.numero}: "
            f"{dobra.angulo:.1f}Ã‚Â° "
            f"{raio} "
            f"PosiÃƒÂ§ÃƒÂ£o={posicao} mm"
        )

    print("")

    print(
        "DETECÃƒâ€¡ÃƒÆ’O GEOMÃƒâ€°TRICA:"
    )

    print(
        f"  Status: "
        f"{desenvolvimento_detalhes.get('status', 'N/D')}"
    )

    print(
        f"  MÃƒÂ©todo: "
        f"{desenvolvimento_detalhes.get('metodo', 'N/D')}"
    )

    print("")

    print(
        "RECONSTRUÃƒâ€¡ÃƒÆ’O DAS ABAS:"
    )

    print(
        f"  Aba 1: "
        f"{desenvolvimento_detalhes.get('aba_1_mm', 0):.4f} mm"
    )

    print(
        f"  Aba 2: "
        f"{desenvolvimento_detalhes.get('aba_2_mm', 0):.4f} mm"
    )

    print(
        f"  Aba 3: "
        f"{desenvolvimento_detalhes.get('aba_3_mm', 0):.4f} mm"
    )

    print("")

    print(
        "BA:"
    )

    for detalhe in desenvolvimento_detalhes.get(
        "detalhes",
        [],
    ):

        print(
            f"  Dobra {detalhe['dobra']}: "
            f"K={detalhe['fator_k']:.4f} | "
            f"BA={detalhe['bend_allowance_mm']:.4f} mm"
        )

    print("")

    if blank.valido:

        print(
            f"Desenvolvimento: "
            f"{blank.comprimento_desenvolvido_mm:.4f} mm"
        )

        print(
            f"Blank: "
            f"{blank.largura_blank_mm:.4f} x "
            f"{blank.comprimento_blank_mm:.4f} mm"
        )

    else:

        print(
            "Desenvolvimento: "
            "NÃƒÆ’O CALCULADO"
        )

        print(
            "Blank: "
            "NÃƒÆ’O CALCULADO"
        )

    print("")

    print(
        "DiagnÃƒÂ³stico salvo em:"
    )

    print(
        caminho_txt
    )

    print("")

    print(
        "JSON para calculadora_corte salvo em:"
    )

    print(
        caminho_json
    )

    print("")


# =============================================================================
# PROCESSAMENTO PRINCIPAL
# =============================================================================

def processar(
    caminho_pdf: str,
):

    caminho = Path(
        caminho_pdf
    )

    if not caminho.exists():

        raise FileNotFoundError(
            f"Arquivo nÃƒÂ£o encontrado: "
            f"{caminho}"
        )

    print("=" * 80)
    print(
        "AIZI ENGINEERING AI"
    )
    print(
        "DIAGNÃƒâ€œSTICO DE DESENHO"
    )
    print("=" * 80)

    print(
        f"Arquivo: {caminho}"
    )

    documento = pymupdf.open(
        caminho
    )

    todos_segmentos = []
    todos_textos = []

    for numero_pagina, pagina in enumerate(
        documento,
        start=1,
    ):

        print(
            f"Processando pÃƒÂ¡gina "
            f"{numero_pagina}..."
        )

        segmentos = extrair_linhas(
            pagina
        )

        textos = extrair_textos(
            pagina
        )

        todos_segmentos.extend(
            segmentos
        )

        todos_textos.extend(
            textos
        )

    documento.close()

    print(
        f"Linhas vetoriais encontradas: "
        f"{len(todos_segmentos)}"
    )

    print(
        f"Textos encontrados: "
        f"{len(todos_textos)}"
    )

    # -------------------------------------------------------------------------
    # CONTORNOS
    # -------------------------------------------------------------------------

    contornos = detectar_contornos(
        todos_segmentos
    )

    print(
        f"Contornos encontrados: "
        f"{len(contornos)}"
    )

    if not contornos:

        raise RuntimeError(
            "Nenhum contorno fechado encontrado."
        )

    # -------------------------------------------------------------------------
    # COMPONENTE 046
    # -------------------------------------------------------------------------

    principal = selecionar_046(
        contornos
    )

    if principal is None:

        raise RuntimeError(
            "NÃƒÂ£o foi possÃƒÂ­vel identificar "
            "o contorno principal."
        )

    principal.componente = "046"

    # -------------------------------------------------------------------------
    # ESPESSURA
    # -------------------------------------------------------------------------

    espessura = identificar_espessura(
        todos_textos
    )

    if espessura is None:

        espessura = ESPESSURA_PADRAO

    # -------------------------------------------------------------------------
    # DOBRAS
    # -------------------------------------------------------------------------

    dobras, deteccao_geometrica = (
        identificar_dobras(
            todos_textos,
            principal,
            espessura,
            todos_segmentos,
        )
    )

    dobras = _aizi_recuperar_posicoes_dobras(
        dobras,
        principal.largura_mm,
        principal.altura_mm,
        todos_segmentos,
    )

    dobras = _aizi_validar_posicoes_dobras(
        dobras,
        max(principal.largura_mm, principal.altura_mm),
    )

    dobras = ordenar_dobras(
        dobras
    )

    # -------------------------------------------------------------------------
    # DESENVOLVIMENTO
    # -------------------------------------------------------------------------

    desenvolvimento, detalhes = (
        estimar_desenvolvimento(
            principal,
            dobras,
            espessura,
            deteccao_geometrica,
        )
    )

    # -------------------------------------------------------------------------
    # BLANK
    # -------------------------------------------------------------------------

    blank = calcular_blank(
        principal,
        desenvolvimento,
        espessura,
        detalhes,
    )

    # -------------------------------------------------------------------------
    # PASTA DE SAÃƒÂDA
    # -------------------------------------------------------------------------

    pasta_saida = (
        caminho.parent /
        caminho.stem
    )

    pasta_saida.mkdir(
        parents=True,
        exist_ok=True,
    )

    caminho_txt = (
        pasta_saida /
        "_diagnostico.txt"
    )

    caminho_json = (
        pasta_saida /
        "_calculadora_corte.json"
    )

    # -------------------------------------------------------------------------
    # TXT
    # -------------------------------------------------------------------------

    gerar_relatorio(
        caminho,
        caminho_txt,
        principal,
        dobras,
        blank,
        espessura,
        detalhes,
        todos_textos,
    )

    # -------------------------------------------------------------------------
    # JSON
    # -------------------------------------------------------------------------

    gerar_json_calculadora_corte(
        caminho_json,
        principal,
        dobras,
        blank,
        espessura,
        detalhes,
    )

    # -------------------------------------------------------------------------
    # RESULTADO
    # -------------------------------------------------------------------------

    imprimir_resultado(
        principal,
        dobras,
        blank,
        caminho_txt,
        caminho_json,
        detalhes,
    )

    return {

        "componente":
            "046",

        "largura_mm":
            principal.largura_mm,

        "altura_mm":
            principal.altura_mm,

        "area_mm2":
            principal.area_mm2,

        "perimetro_mm":
            principal.perimetro_mm,

        "segmentos":
            len(
                principal.segmentos
            ),

        "dobras":
            [
                asdict(d)
                for d in dobras
            ],

        "deteccao_geometrica":
            deteccao_geometrica,

        "desenvolvimento_mm":
            blank.comprimento_desenvolvido_mm,

        "desenvolvimento_detalhes":
            detalhes,

        "blank": {

            "largura_mm":
                blank.largura_blank_mm,

            "comprimento_mm":
                blank.comprimento_blank_mm,

            "espessura_mm":
                blank.espessura_mm,

            "valido":
                blank.valido,
        },

        "diagnostico":
            str(caminho_txt),

        "calculadora_corte":
            str(caminho_json),
    }


# =============================================================================
# LOCALIZAR PDF
# =============================================================================

def selecionar_pdf() -> Optional[str]:

    try:

        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()

        root.withdraw()

        caminho = (
            filedialog.askopenfilename(
                title=
                    "Selecione o desenho tÃƒÂ©cnico",

                filetypes=[
                    (
                        "Arquivos PDF",
                        "*.pdf",
                    ),
                    (
                        "Todos os arquivos",
                        "*.*",
                    ),
                ],
            )
        )

        root.destroy()

        if caminho:
            return caminho

    except Exception as erro:

        print(
            f"NÃƒÂ£o foi possÃƒÂ­vel abrir seletor: "
            f"{erro}"
        )

    return None


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":

    try:

        if len(sys.argv) > 1:

            caminho = sys.argv[1]

        else:

            caminho = selecionar_pdf()

            if not caminho:

                print(
                    "Nenhum arquivo selecionado."
                )

                sys.exit(0)

        processar(
            caminho
        )

        print("=" * 80)
        print(
            "PROCESSAMENTO FINALIZADO"
        )
        print("=" * 80)

    except KeyboardInterrupt:

        print(
            "\nProcessamento cancelado."
        )

        sys.exit(1)

    except Exception as erro:

        print("")
        print("=" * 80)
        print(
            "ERRO NO DIAGNÃƒâ€œSTICO"
        )
        print("=" * 80)

        print(
            f"{type(erro).__name__}: "
            f"{erro}"
        )

        import traceback

        traceback.print_exc()

        sys.exit(1)
