"""L'Assistant IA répond dans la langue de la page : en arabe quand la personne a choisi l'arabe."""
from unittest.mock import patch

from django.test import SimpleTestCase

from assistant import services


class LangueDeLaReponseTests(SimpleTestCase):
    def instructions_pour(self, fonction, langue, **kwargs):
        with patch.object(services, "_interroger_groq", return_value="ok") as appel:
            fonction(langue=langue, **kwargs)
        return appel.call_args.kwargs["instructions"]

    def test_la_consigne_de_langue_suit_la_page(self):
        for fonction, kwargs in (
            (services.repondre_avec_ia, {"donnees_autorisees": {"a": 1}, "question": "q"}),
            (services.repondre_question_generale_avec_ia, {"donnees_autorisees": {"a": 1}, "question": "q"}),
            (services.resumer_alertes_avec_ia, {"alertes": [{"titre": "t", "description": "d"}]}),
        ):
            with self.subTest(fonction=fonction.__name__):
                self.assertIn("Réponds en français", self.instructions_pour(fonction, "fr", **kwargs))
                arabe = self.instructions_pour(fonction, "ar", **kwargs)
                self.assertIn("Réponds en arabe", arabe)
                self.assertNotIn("Réponds en français", arabe)

    def test_le_francais_est_la_langue_par_defaut(self):
        with patch.object(services, "_interroger_groq", return_value="ok") as appel:
            services.repondre_avec_ia(donnees_autorisees={}, question="q")
        self.assertIn("Réponds en français", appel.call_args.kwargs["instructions"])
