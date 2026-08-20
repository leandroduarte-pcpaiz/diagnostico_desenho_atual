# -*- coding: utf-8 -*-
"""AIZI Engineering AI - correção do desenvolvimento/blank.

A implementação geométrica original foi preservada em
``diagnostico_desenho_base.py``. Este módulo corrige o fechamento do
cálculo para perfis de duas dobras: desenvolvimento = dimensão transversal
- BD1 - BD2.
"""
from __future__ import annotations

import sys
from typing import Optional, List
import diagnostico_desenho_base as _base

for _nome in dir(_base):
    if not _nome.startswith("__"):
        globals()[_nome] = getattr(_base, _nome)


def estimar_desenvolvimento(
    contorno: Contorno,
    dobras: List[Dobra],
    espessura_mm: Optional[float],
    deteccao_geometrica: dict,
):
    """Calcula corretamente o desenvolvimento de duas dobras.

    Para cotas externas, cada dobra contribui com uma BD. Portanto:
        desenvolvimento = dimensão transversal - BD1 - BD2
    """
    dim = 0.0
    itens = []
    if espessura_mm is None:
        espessura_mm = ESPESSURA_PADRAO

    # Executa a geometria/validações da implementação original.
    original, detalhes = _base.estimar_desenvolvimento(
        contorno, dobras, espessura_mm, deteccao_geometrica
    )
    if len(dobras) != 2:
        return original, detalhes

    pos = sorted(d.posicao_mm for d in dobras if d.posicao_mm is not None)
    if len(pos) != 2:
        return original, detalhes

    dim = float(detalhes.get("dimensao_transversal_mm", 0.0) or 0.0)
    if dim <= 0:
        return original, detalhes

    # Recalcula BA/BD com os mesmos parâmetros usados pelo diagnóstico.
    for dobra in sorted(dobras, key=lambda d: d.posicao_mm):
        raio = float(dobra.raio if dobra.raio is not None else RAIO_PADRAO)
        k = fator_k_por_raio(raio, espessura_mm)
        ba = bend_allowance(dobra.angulo, raio, espessura_mm, k)
        bd = bend_deduction(dobra.angulo, raio, espessura_mm, k)
        itens.append({
            "dobra": dobra.numero,
            "angulo_graus": dobra.angulo,
            "raio_mm": raio,
            "espessura_mm": espessura_mm,
            "razao_raio_espessura": raio / espessura_mm,
            "fator_k": k,
            "setback_mm": bend_setback(dobra.angulo, raio, espessura_mm),
            "bend_allowance_mm": ba,
            "bend_deduction_mm": bd,
            "posicao_mm": dobra.posicao_mm,
            "origem_posicao": dobra.origem,
        })

    bd_total = sum(x["bend_deduction_mm"] for x in itens)
    ba_total = sum(x["bend_allowance_mm"] for x in itens)
    desenvolvimento = dim - bd_total

    p1, p2 = pos
    setback1 = itens[0]["setback_mm"]
    setback2 = itens[1]["setback_mm"]
    aba1 = p1 - setback1
    aba2 = (p2 - p1) - setback1 - setback2
    aba3 = (dim - p2) - setback2

    valido = aba1 > 0 and aba2 > 0 and aba3 > 0 and desenvolvimento > 0
    sequencia = [
        {"tipo": "ABA", "numero": 1, "comprimento_mm": aba1, "trecho_externo_mm": p1, "origem": "GEOMETRIA"},
        {"tipo": "BA", "numero": 1, "comprimento_mm": itens[0]["bend_allowance_mm"], "origem": "DOBRA_1"},
        {"tipo": "ABA", "numero": 2, "comprimento_mm": aba2, "trecho_externo_mm": p2 - p1, "origem": "GEOMETRIA"},
        {"tipo": "BA", "numero": 2, "comprimento_mm": itens[1]["bend_allowance_mm"], "origem": "DOBRA_2"},
        {"tipo": "ABA", "numero": 3, "comprimento_mm": aba3, "trecho_externo_mm": dim - p2, "origem": "GEOMETRIA"},
    ]
    soma = sum(x["comprimento_mm"] for x in sequencia)

    detalhes.update({
        "status": "CALCULADO" if valido else "NAO_CALCULADO",
        "metodo": "DIMENSAO_TRANSVERSAL_MENOS_BD_TOTAL",
        "base_mm": dim,
        "bend_allowance_total_mm": ba_total,
        "bend_deduction_total_mm": bd_total,
        "desenvolvimento_mm": desenvolvimento,
        "desenvolvimento_por_bd_mm": desenvolvimento,
        "diferenca_entre_metodos_mm": 0.0,
        "soma_sequencia_mm": soma,
        "erro_fechamento_mm": desenvolvimento - soma,
        "posicao_dobra_1_mm": p1,
        "posicao_dobra_2_mm": p2,
        "setback_1_mm": setback1,
        "setback_2_mm": setback2,
        "aba_1_mm": aba1,
        "aba_2_mm": aba2,
        "aba_3_mm": aba3,
        "detalhes": itens,
        "sequencia": sequencia,
        "criterio": "DIMENSAO_TRANSVERSAL_MENOS_BD_TOTAL",
        "nao_utiliza_bounding_box_para_desenvolvimento": True,
        "usa_dimensionamento_transversal_para_bd": True,
    })
    return desenvolvimento, detalhes


def processar(caminho_pdf: str):
    # Injeta a função corrigida no pipeline original antes de processar.
    _base.estimar_desenvolvimento = estimar_desenvolvimento
    return _base.processar(caminho_pdf)


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            processar(sys.argv[1])
        else:
            caminho = selecionar_pdf()
            if caminho:
                processar(caminho)
            else:
                print("Nenhum arquivo selecionado.")
                raise SystemExit(0)
        print("=" * 80)
        print("PROCESSAMENTO FINALIZADO")
        print("=" * 80)
    except KeyboardInterrupt:
        print("\nProcessamento cancelado.")
        raise SystemExit(1)
    except Exception as erro:
        print("=" * 80)
        print(f"ERRO NO DIAGNOSTICO: {type(erro).__name__}: {erro}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
