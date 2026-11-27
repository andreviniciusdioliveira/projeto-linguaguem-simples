"""Testes das conferências feitas sem IA após a resposta do modelo. Textos fictícios.

Rodar:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from salvaguardas import (  # noqa: E402
    anexar_bloco,
    bloco_data_e_prazos,
    corrigir_datas_incompletas,
    detectar_peca_nao_judicial,
    extrair_data_assinatura,
    extrair_numero_processo,
    extrair_prazos_escritos,
    normalizar_titulos,
    validar_gratuidade,
)

MP = ("SEEU - Processo: 0000001-11.2025.8.27.0001 - Assinado digitalmente por Fulano de Tal\n"
      "[29.1] JUNTADA DE MANIFESTAÇÃO - manifestação em 04/08/2025\n\nSenhor Juiz,\n\n"
      "É inviável o requerimento de substituição da pena. " + "Fundamentação. " * 80 +
      "\nPelo indeferimento do pedido.\n\nCidade/UF, 4 de agosto de 2025.\n\nFulano de Tal\nPromotor de Justiça\n")
DESPACHO_SEEU = ("SEEU - Processo: 0000001-11.2025.8.27.0001\n\nDESPACHO\n\nVista ao Ministério Público, que opinou pelo indeferimento. "
                 "Intime-se a defesa para se manifestar no prazo de 5 (cinco) dias.\n\nCidade/UF, 10 de agosto de 2025.\n\n"
                 "Beltrano de Tal\nJuiz de Direito\n")
SENTENCA = ("Poder Judiciário\n1ª Vara Cível de Exemplo\nPROCEDIMENTO COMUM CÍVEL Nº 0000002-22.2025.8.27.0001/TO\n\nSENTENÇA\n\n"
            + "Relatório e fundamentação. O réu contestou no prazo de 15 dias. " * 40 +
            "\nIII - DISPOSITIVO\nAnte o exposto, JULGO PROCEDENTE o pedido. Intime-se a parte ré para pagar em 15 (quinze) dias, "
            "sob pena de multa. Sem custas e sem honorários.\n\nDocumento eletrônico assinado por BELTRANO, Juiz de Direito.\n"
            "Informações adicionais da assinatura:\nSignatário (a): BELTRANO\nData e Hora: 28/10/2025, às 10:24:28\n")


class PecaNaoJudicial(unittest.TestCase):
    def test_manifestacao_do_ministerio_publico_bloqueada(self):
        r = detectar_peca_nao_judicial(MP)
        self.assertTrue(r["detectado"])
        self.assertIn("Ministério Público", r["razao"])

    def test_ato_de_magistrado_no_mesmo_sistema_passa(self):
        # documento do SEEU assinado por juiz, mesmo citando o parecer do MP
        self.assertFalse(detectar_peca_nao_judicial(DESPACHO_SEEU)["detectado"])

    def test_sentenca_que_cita_promotor_passa(self):
        self.assertFalse(detectar_peca_nao_judicial(SENTENCA + "\nCiência ao Promotor de Justiça.\n")["detectado"])


class DataEPrazos(unittest.TestCase):
    def test_data_da_assinatura(self):
        self.assertEqual(extrair_data_assinatura(SENTENCA), "28/10/2025")
        self.assertEqual(extrair_data_assinatura(DESPACHO_SEEU), "10/08/2025")
        self.assertIsNone(extrair_data_assinatura("Texto sem data."))

    def test_prazo_escrito_so_da_parte_decisoria(self):
        prazos = extrair_prazos_escritos(SENTENCA)
        self.assertEqual([p["prazo"] for p in prazos], ["15 dias"])
        self.assertIn("Intime-se a parte ré", prazos[0]["trecho"])

    def test_bloco_com_e_sem_prazo(self):
        bloco, dados = bloco_data_e_prazos(SENTENCA)
        self.assertIn("assinado em 28/10/2025", bloco)
        self.assertIn("15 dias", bloco)
        self.assertIn("intimação", bloco)
        self.assertEqual(dados["data_assinatura"], "28/10/2025")
        bloco2, dados2 = bloco_data_e_prazos("DECISÃO\nMantenho a decisão. Cumpra-se.\nData e Hora: 01/02/2026, às 10:00", truncado=True)
        self.assertEqual(dados2["prazos_documento"], [])
        self.assertIn("não informa prazo em dias", bloco2)
        self.assertIn("não foi analisada", bloco2)

    def test_bloco_entra_antes_da_dica(self):
        texto = "CONSEGUIU O QUE PEDIU\n\nCorpo.\n\n---\n\n*💡 Dica: procure ajuda.*"
        final = anexar_bloco(texto, "**DATA E PRAZOS QUE CONSTAM NO DOCUMENTO**")
        self.assertLess(final.index("DATA E PRAZOS"), final.index("Dica"))

    def test_numero_do_processo_quebrado_em_duas_linhas(self):
        self.assertEqual(extrair_numero_processo("AGRAVO Nº 0011307-\n98.2025.8.27.2700/TO\n... MS nº 5000024-38.2008.8.27.0000"),
                         "0011307-98.2025.8.27.2700")
        self.assertEqual(extrair_numero_processo("AGRAVO Nº 001130798.2025.8.27.2700/TO"), "0011307-98.2025.8.27.2700")
        self.assertIsNone(extrair_numero_processo("sem número"))


class Gratuidade(unittest.TestCase):
    def analise(self):
        return {"tem_justica_gratuita": True,
                "valores_principais": {"custas": "Isento (justiça gratuita)", "honorarios": "Isento (justiça gratuita)"},
                "texto_simplificado": "Você NÃO vai pagar custas e honorários porque tem justiça gratuita.\n\nOutro parágrafo."}

    def test_juizado_sem_custas_por_lei(self):
        a = self.analise()
        self.assertTrue(validar_gratuidade(a, "Sem custas e sem honorários, nos termos dos arts. 54 e 55 da Lei 9.099/95."))
        self.assertFalse(a["tem_justica_gratuita"])
        self.assertNotIn("gratuita", a["texto_simplificado"])
        self.assertIn("conforme consta do documento", a["texto_simplificado"])
        self.assertEqual(a["valores_principais"]["custas"], "Sem cobrança, conforme o documento")

    def test_documento_que_nao_fala_de_custas(self):
        a = self.analise()
        validar_gratuidade(a, "Julgo procedente o pedido.")
        self.assertIn("não informa quem paga", a["texto_simplificado"])
        self.assertIsNone(a["valores_principais"]["custas"])

    def test_gratuidade_escrita_e_mantida(self):
        a = self.analise()
        self.assertFalse(validar_gratuidade(a, "A parte autora é beneficiária da assistência judiciária gratuita."))
        self.assertTrue(a["tem_justica_gratuita"])
        self.assertIn("justiça gratuita", a["texto_simplificado"])


class Titulos(unittest.TestCase):
    def test_titulos_de_secao_fixos(self):
        t = normalizar_titulos("🟡 **CONSEGUIU PARTE DO QUE PEDIU**\n\n**VALORES E O QUE VOCÊ PRECISA HABILITAR**\n\n**PALAVRAS QUE APARECEM NO DOCUMENTO**")
        self.assertIn("**VALORES E O QUE VOCÊ PRECISA FAZER**", t)
        self.assertIn("**PALAVRAS QUE PODEM APARECER NO DOCUMENTO**", t)

    def test_rotulo_com_erro_de_digitacao(self):
        self.assertTrue(normalizar_titulos("🟡 CONSEGUIU PARTE DO QUE PEDIDU\n\nCorpo").startswith("🟡 CONSEGUIU PARTE DO QUE PEDIU"))
        self.assertTrue(normalizar_titulos("🟡 **CONSEGUIR PARTE DO QUE PEDIU**\n\nCorpo").startswith("🟡 **CONSEGUIU PARTE DO QUE PEDIU**"))

    def test_rotulo_negativo_nao_vira_positivo(self):
        self.assertTrue(normalizar_titulos("❌ NÃO CONSEGUIU O QUE PEDIU\n\nCorpo").startswith("❌ NÃO CONSEGUIU O QUE PEDIU"))

    def test_condenacao_integral_nao_e_parcial(self):
        t = normalizar_titulos("🟡 CONDENAÇÃO PARCIAL\n\nCorpo", "Diante do exposto, julgo procedente o pedido estampado na denúncia.")
        self.assertTrue(t.startswith("🟡 CONDENAÇÃO\n"))
        t2 = normalizar_titulos("🟡 CONDENAÇÃO PARCIAL\n\nCorpo", "Julgo parcialmente procedente a denúncia.")
        self.assertTrue(t2.startswith("🟡 CONDENAÇÃO PARCIAL"))

    def test_rotulo_livre_e_preservado(self):
        self.assertTrue(normalizar_titulos("📋 **ORDEM JUDICIAL PARA COMPARECER À AUDIÊNCIA**\n\nCorpo").startswith("📋 **ORDEM JUDICIAL PARA COMPARECER"))


class DatasIncompletas(unittest.TestCase):
    ORIGINAL = "audiência designada para o dia 26 DE MAIO DE 205, ÀS 09H00MIN. Tempo: 26/05/2025 09:00 ~ 26/05/2025 22:00"

    def test_ano_com_erro_de_digitacao_e_corrigido(self):
        a = {"texto_simplificado": "A audiência será no dia 26 de maio de 205. Compareça em 26/05/205.\n\n---\n\n*💡 Dica.*",
             "audiencia": {"data": "26/05/205"}}
        self.assertTrue(corrigir_datas_incompletas(a, self.ORIGINAL))
        self.assertIn("26 de maio de 2025", a["texto_simplificado"])
        self.assertIn("26/05/2025", a["texto_simplificado"])
        self.assertNotIn("de 205.", a["texto_simplificado"])
        self.assertIn("ATENÇÃO À DATA", a["texto_simplificado"])
        self.assertEqual(a["audiencia"]["data"], "26/05/2025")

    def test_sem_data_completa_correspondente_nao_mexe(self):
        a = {"texto_simplificado": "A audiência será no dia 26 de maio de 205."}
        self.assertFalse(corrigir_datas_incompletas(a, "audiência em 26 de maio de 205"))
        self.assertIn("de 205", a["texto_simplificado"])

    def test_data_correta_nao_e_alterada(self):
        a = {"texto_simplificado": "Em 21/06/2017 e no dia 3 de novembro de 2025."}
        self.assertFalse(corrigir_datas_incompletas(a, self.ORIGINAL))
        self.assertEqual(a["texto_simplificado"], "Em 21/06/2017 e no dia 3 de novembro de 2025.")


if __name__ == "__main__":
    unittest.main()
