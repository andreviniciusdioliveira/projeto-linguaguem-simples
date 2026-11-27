"""Testes das salvaguardas determinísticas. Todos os textos são fictícios.

Rodar:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from salvaguardas import (  # noqa: E402
    detectar_segredo_justica_local,
    documento_procedimental,
    validar_prazos_contra_original,
)

CABECALHO = "01/01/2026, 10:00 :: 123 - eproc - ::\nPoder Judiciário\nJUSTIÇA ESTADUAL\nTribunal de Justiça\n"


def doc(juizo, classe, corpo="DESPACHO/DECISÃO\nDesigno audiência. Int. Cumpra-se.\n"):
    return f"{CABECALHO}{juizo}\n{classe} Nº 0000001-11.2025.8.27.0001/TO\n{corpo}"


class TriagemSegredo(unittest.TestCase):
    def bloqueia(self, texto):
        return detectar_segredo_justica_local(texto)["detectado"]

    def test_ato_infracional_bloqueado(self):
        self.assertTrue(self.bloqueia(doc("Juizado Especial da Infância e Juventude de Exemplo",
                                          "PROCESSO DE APURAÇÃO DE ATO INFRACIONAL")))

    def test_medida_socioeducativa_bloqueada(self):
        self.assertTrue(self.bloqueia(doc("Juizado Especial da Infância e Juventude de Exemplo",
                                          "EXECUÇÃO DE MEDIDAS SÓCIO-EDUCATIVAS")))

    def test_classe_de_familia_bloqueada_mesmo_em_vara_civel(self):
        self.assertTrue(self.bloqueia(doc("1ª Vara Cível de Exemplo", "ALIMENTOS - LEI ESPECIAL Nº 5.478/68")))
        self.assertTrue(self.bloqueia(doc("1ª Vara Cível de Exemplo", "DIVÓRCIO LITIGIOSO")))

    def test_vara_de_familia_bloqueada(self):
        self.assertTrue(self.bloqueia(doc("Vara de Família, Sucessões, Infância e Juventude de Exemplo",
                                          "PROCEDIMENTO COMUM CÍVEL")))

    def test_marcacao_explicita_bloqueada(self):
        self.assertTrue(self.bloqueia(doc("2ª Vara Criminal de Exemplo", "INQUÉRITO POLICIAL (SIGILOSO)")))

    def test_cumpra_se_no_corpo_nao_torna_procedimental(self):
        r = detectar_segredo_justica_local(doc("Juizado Especial da Infância e Juventude de Exemplo",
                                               "PROCESSO DE APURAÇÃO DE ATO INFRACIONAL",
                                               "DESPACHO/DECISÃO\nExpeça-se mandado de intimação. Int. Cumpra-se.\n"))
        self.assertFalse(r["procedimental"])
        self.assertTrue(r["detectado"])

    def test_mandado_de_vara_de_familia_segue_para_simplificacao(self):
        texto = doc("Vara de Família, Sucessões, Infância e Juventude de Exemplo", "PROCEDIMENTO COMUM CÍVEL",
                    "MANDADO Nº 123456\nDestinatário: Fulana de Tal\nPROCEDER A INTIMAÇÃO PARA QUE PARTICIPE da audiência.\n")
        r = detectar_segredo_justica_local(texto)
        self.assertTrue(r["procedimental"])
        self.assertTrue(r["indicadores"])
        self.assertFalse(r["detectado"])

    def test_documentos_comuns_nao_bloqueados(self):
        self.assertFalse(self.bloqueia(doc("2º Juizado Especial Cível de Exemplo", "PROCEDIMENTO DO JUIZADO ESPECIAL CÍVEL",
                                           "SENTENÇA\nO autor pediu a guarda do veículo e alimentos não são discutidos.\n")))
        self.assertFalse(self.bloqueia(doc("1ª Vara Criminal de Exemplo", "AÇÃO PENAL - PROCEDIMENTO ORDINÁRIO")))
        self.assertFalse(self.bloqueia(doc("GAB. DA DESA. EXEMPLO", "HABEAS CORPUS CRIMINAL")))

    def test_processo_originario_sigiloso_nao_bloqueia(self):
        self.assertFalse(self.bloqueia(doc("GAB. DA DESA. EXEMPLO",
                                           "AGRAVO DE INSTRUMENTO (PROCESSO ORIGINÁRIO SIGILOSO)")))
        # número quebrado em duas linhas pelo OCR
        texto = (CABECALHO + "GAB. DA DESA. EXEMPLO\nAGRAVO DE INSTRUMENTO (PROCESSO ORIGINÁRIO SIGILOSO) Nº 0000001-\n"
                 "11.2025.8.27.0001/TO\nEMENTA: SERVIDOR PÚBLICO. REAJUSTE.\n")
        self.assertFalse(self.bloqueia(texto))

    def test_titulo_procedimental(self):
        self.assertTrue(documento_procedimental("Vara X\nMANDADO DE INTIMAÇÃO\nFulano"))
        self.assertTrue(documento_procedimental("Vara X\nCARTA DE CITAÇÃO\nFulano"))
        self.assertFalse(documento_procedimental("Vara X\nSENTENÇA\nIntimação das partes. Cumpra-se."))


class ValidacaoPrazos(unittest.TestCase):
    def analise(self, texto, prazo_recurso="15 dias", prazos=None):
        return {
            "texto_simplificado": texto,
            "recursos_cabiveis": {"cabe_recurso": "Sim", "prazo": prazo_recurso},
            "prazos": prazos if prazos is not None else [{"tipo": "recurso", "prazo": prazo_recurso}],
        }

    def test_prazo_inventado_e_removido(self):
        original = "SENTENÇA. Julgo procedente. Fixo a pena em 9 (nove) meses e 10 (dez) dias de detenção. O réu poderá apelar em liberdade."
        a = self.analise("VOCÊ foi condenado a 9 meses e 10 dias. Avalie entrar com apelação no prazo de 15 dias.")
        removidos = validar_prazos_contra_original(a, original)
        self.assertTrue(removidos)
        self.assertIsNone(a["recursos_cabiveis"]["prazo"])
        self.assertEqual(a["prazos"], [])
        self.assertNotIn("15 dias", a["texto_simplificado"])
        self.assertIn("9 meses e 10 dias", a["texto_simplificado"])  # pena escrita no documento permanece
        self.assertIn("no prazo previsto em lei", a["texto_simplificado"])
        self.assertIn("Defensoria Pública", a["texto_simplificado"])

    def test_prazo_escrito_e_mantido(self):
        for trecho in ("no prazo de 15 (quinze) dias", "em quinze dias", "prazo de 15 dias úteis", "em 15\n(quinze) dias"):
            a = self.analise("Você pode recorrer no prazo de 15 dias.")
            self.assertEqual(validar_prazos_contra_original(a, f"Intimem-se para recorrer {trecho}."), [], trecho)
            self.assertEqual(a["recursos_cabiveis"]["prazo"], "15 dias")
            self.assertIn("15 dias", a["texto_simplificado"])

    def test_numero_parecido_nao_conta(self):
        # "15%" e "115 dias" não sustentam "15 dias"
        a = self.analise("O prazo é de 15 dias.")
        self.assertTrue(validar_prazos_contra_original(a, "Honorários de 15% sobre o valor. Afastado por 115 dias."))
        self.assertIn("o previsto em lei", a["texto_simplificado"])

    def test_horas_e_campos_sem_numero(self):
        a = self.analise("Compareça em 48 horas.", prazo_recurso=None, prazos=[{"prazo": "48 horas"}, {"prazo": "imediato"}])
        validar_prazos_contra_original(a, "Deverá comparecer no prazo de 48 (quarenta e oito) horas.")
        self.assertEqual(len(a["prazos"]), 2)
        self.assertIn("48 horas", a["texto_simplificado"])


if __name__ == "__main__":
    unittest.main()
