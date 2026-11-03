"""
Contrôle permanent des fuites du numéro du cycle.

Chaque élève reçoit un jeton unique (« SNT<id><lettre du cycle>XQ ») comme numéro dans chacun des cycles où il a une inscription. Des personnes de
tous les profils (administration, directeurs de cycle, censeur, comptable, gérant de la cantine, enseignants, parents, élèves, école voisine, visiteur)
visitent ensuite toutes les pages qui peuvent afficher un numéro (listes, dossiers, recherches, exports, PDF, finances, cantine, tenues, anciens
élèves, portail du parent, recherches en direct, documents et historiques d'un élève). Un jeton n'apparaît que pour une personne qui voit à la fois
l'élève et une classe de CE cycle : jamais le numéro d'un autre cycle, d'un autre élève, ni d'une autre école. Même un directeur ou un enseignant qui a eu
l'élève dans sa classe ne lit rien du cycle suivant (carte, attestation, certificats, bulletins, absences, discipline, reçus) : voir aussi
`scolarite/test_perimetre_parcours.py`.

Les modules Élèves, Classes, Finances, Cantine, Notes et Absences sont accordés à tous les profils (l'école règle sa matrice) : cela ne doit rien
changer à ce que chacun voit.
"""
import datetime
import html
import io
import re
from types import SimpleNamespace
from unittest import mock

from django.test import Client
from django.urls import reverse
from openpyxl import load_workbook

from cantine import services as services_cantine
from cantine.models import FormuleCantine, InscriptionCantine, ModeCantine
from comptes.roles import Role
from finances import tenues
from finances.models import ArticleTenue, TypeTranche, enregistrer_paiement
from permissions_matrix.models import PermissionMatrix
from permissions_matrix.modules import Module
from scolarite.models import (
    Cycle, Inscription, NumeroCycle, TypeDocumentVerifiable, VerificationDocument, classes_visibles_pour, eleves_visibles_pour,
)
from scolarite.test_dossier_complet import StockageTemporaire
from statistiques.test_education import creer_compte

LETTRE = {Cycle.PREMIER_CYCLE: "A", Cycle.DEUXIEME_CYCLE: "B", Cycle.LYCEE: "C", Cycle.PROFESSIONNEL: "D"}
JETON = re.compile(r"SNT\d+[ABCD]XQ")


def texte_de(reponse) -> str:
    type_contenu = reponse.headers.get("Content-Type", "")
    contenu = b"".join(reponse.streaming_content) if getattr(reponse, "streaming", False) else reponse.content
    if "spreadsheetml" in type_contenu:
        classeur = load_workbook(io.BytesIO(contenu))
        return " ".join(str(c.value) for f in classeur.worksheets for r in f.iter_rows() for c in r if c.value is not None)
    return html.unescape(contenu.decode("utf-8", errors="replace"))


class FuitesDesNumerosTests(StockageTemporaire):
    def setUp(self):
        Inscription.objects.create(eleve=self.e5, classe=self.classe_5a, statut=Inscription.Statut.ADMIS)
        self.eleves = [self.e1, self.e2, self.e3, self.e4, self.e5, self.e6, self.e7, self.e8, self.e9]
        self.jetons = {}
        for inscription in Inscription.objects.filter(eleve__in=self.eleves).select_related("classe"):
            jeton = f"SNT{inscription.eleve_id}{LETTRE[inscription.classe.cycle]}XQ"
            self.jetons[(inscription.eleve_id, inscription.classe.cycle)] = jeton
            NumeroCycle.objects.get_or_create(eleve=inscription.eleve, cycle=inscription.classe.cycle, defaults={"numero": jeton})

        self.dir_2eme = creer_compte(Role.DIRECTEUR_2EME_CYCLE, "dir2@fuite.test", self.ecole)
        self.gerant = creer_compte(Role.PERSONNEL, "gerant@fuite.test", self.ecole)
        self.parent5 = creer_compte(Role.PARENT, "parent5@fuite.test", self.ecole, telephone="70999005")
        self.e5.parents_lies.add(self.parent5)
        PermissionMatrix.objects.update_or_create(
            etablissement=self.ecole, role=Role.PERSONNEL.value, module=Module.CANTINE.value, defaults={"autorise": True},
        )
        self.profils = {
            "fondateur": self.fondateur, "secretaire": self.secretaire, "directeur 1er cycle": self.dir_1er,
            "directeur 2ème cycle": self.dir_2eme, "censeur": self.censeur, "comptable": self.comptable, "gérant de la cantine": self.gerant,
            "enseignant 6A": self.t1, "enseignant 6B et 9A": self.t2, "enseignant TSE": self.t3, "enseignant de l'an dernier": self.t_ancien,
            "parent de e1": self.parent, "parent de e5": self.parent5, "élève e1": self.e1, "élève e5": self.e5,
            "fondateur de l'autre école": self.fondateur_b, "anonyme": None,
        }
        for compte in self.profils.values():
            if compte is not None and compte.etablissement_id == self.ecole.pk:
                for module in (Module.ELEVES, Module.CLASSES, Module.FINANCES, Module.CANTINE, Module.NOTES_BULLETINS, Module.ABSENCES):
                    PermissionMatrix.objects.update_or_create(
                        etablissement=self.ecole, role=compte.role, module=module, defaults={"autorise": True},
                    )

        # Des données dans chaque module, pour que les pages ne soient pas vides.
        self.paiements = [
            enregistrer_paiement(
                eleve=eleve, inscription=self.i[nom], tranche=TypeTranche.VERSEMENT, montant=1000, mode_paiement="especes",
                enregistre_par=self.comptable,
            )
            for nom, eleve in (("e1", self.e1), ("e5", self.e5), ("e7", self.e7))
        ]
        article = ArticleTenue.objects.create(etablissement=self.ecole, libelle="Polo", taille="12", prix=4500)
        ArticleTenue.objects.filter(pk=article.pk).update(stock=20)
        self.ventes = [
            tenues.vendre(quantites={article.pk: 1}, etablissement=self.ecole, eleve=eleve, acheteur="", mode_paiement="especes", acteur=self.comptable)
            for eleve in (self.e1, self.e5)
        ]
        formule = FormuleCantine.objects.create(etablissement=self.ecole, libelle="Midi", mode=ModeCantine.MENSUEL, montant=5000)
        self.paiements_cantine = []
        for eleve in (self.e1, self.e5, self.e7):
            inscription = InscriptionCantine(
                etablissement=self.ecole, eleve=eleve, annee_scolaire=self.annee, formule=formule,
                date_debut=datetime.date(2026, 10, 15), cree_par=self.fondateur,
            )
            inscription.full_clean()
            inscription.save()
            self.paiements_cantine.append(services_cantine.enregistrer_paiement(
                inscription=inscription, montant=5000, mode_paiement="especes", acteur=self.fondateur,
            ))
        self.i["e8"].statut = Inscription.Statut.TRANSFERE  # un ancien élève
        self.i["e8"].save(update_fields=["statut"])

    # ------------------------------------------------------------------------------------------------------------------
    def adresses(self):
        classes = [self.c6a, self.c6b, self.c9a, self.ctse, self.ccap, self.classe_5a]
        adresses = [
            reverse("scolarite:liste_eleves"), reverse("scolarite:recherche_globale") + "?q=SNT", reverse("scolarite:anciens_eleves"),
            reverse("scolarite:anciens_eleves") + "?q=SNT", reverse("finances:liste_paiements"), reverse("finances:suivi_paiements"),
            reverse("finances:arrieres"), reverse("finances:arrieres") + "?q=SNT", reverse("finances:tenues_ventes"),
            reverse("finances:tenues_ventes") + "?q=SNT", reverse("finances:rechercher_eleve_json") + "?q=SNT",
            reverse("assistant:rechercher_eleve_json") + "?q=SNT", reverse("cantine:tableau"), reverse("cantine:tableau") + "?q=SNT",
            reverse("cantine:appel") + "?date=2026-11-02", reverse("comptes:portail_parent"), reverse("scolarite:liste_classes"),
            reverse("pedagogie:conseils"),
        ]
        for classe in classes:
            adresses += [
                reverse("scolarite:liste_eleves") + f"?classe={classe.pk}",
                reverse("scolarite:cartes_classe_pdf", args=[classe.pk]),
                reverse("scolarite:exporter_liste_classe_csv", args=[classe.pk]),
                reverse("scolarite:exporter_liste_classe_xlsx", args=[classe.pk]),
                reverse("scolarite:exporter_liste_classe_pdf", args=[classe.pk]),
                reverse("scolarite:saisir_resultats_examen", args=[classe.pk]),
                reverse("scolarite:saisir_numeros_cycle", args=[classe.pk]),
                reverse("scolarite:modele_numeros_cycle", args=[classe.pk]),
                reverse("scolarite:passage_de_classe", args=[classe.pk]) + f"?annee_destination={self.annee.pk}",
                reverse("scolarite:importer_photos_classe", args=[classe.pk]),
                reverse("pedagogie:exporter_bulletins_classe_pdf", args=[classe.pk]),
                reverse("pedagogie:exporter_releve_notes_xlsx", args=[classe.pk]),
                reverse("pedagogie:exporter_absences_xlsx", args=[classe.pk]),
                reverse("pedagogie:conseil", args=[classe.pk, "trimestre_1"]),
                reverse("pedagogie:saisir_absence", args=[classe.pk]),
                reverse("cantine:inscrire_eleves") + f"?classe={classe.pk}",
            ]
        for eleve in self.eleves:
            adresses += [
                reverse("scolarite:dossier_eleve", args=[eleve.matricule]),
                reverse("scolarite:carte_eleve_pdf", args=[eleve.matricule]),
                reverse("scolarite:generer_attestation_scolarite", args=[eleve.matricule]),
                reverse("scolarite:document_officiel", args=[eleve.matricule, "certificat-scolarite"]),
                reverse("scolarite:corriger_dossier_eleve", args=[eleve.matricule]),
                reverse("pedagogie:bulletin_eleve", args=[eleve.matricule]),
                reverse("pedagogie:exporter_bulletin_pdf", args=[eleve.matricule]),
                reverse("pedagogie:mensuel_eleve", args=[eleve.matricule]),
                reverse("pedagogie:historique_absences", args=[eleve.matricule]),
                reverse("pedagogie:historique_discipline", args=[eleve.matricule]),
                reverse("finances:enregistrer_paiement") + f"?eleve={eleve.matricule}&inscription={Inscription.objects.filter(eleve=eleve).first().pk}",
            ]
        adresses += [reverse("finances:exporter_recu_paiement_pdf", args=[p.pk]) for p in self.paiements]
        adresses += [reverse("finances:tenues_recu_pdf", args=[v.pk]) for v in self.ventes]
        adresses += [reverse("cantine:recu_pdf", args=[p.pk]) for p in self.paiements_cantine]
        return adresses

    def jetons_permis(self, compte) -> set:
        """Le numéro d'un cycle, pour un élève que la personne voit, dans une classe de ce cycle qu'elle voit. Rien pour une autre école."""
        if compte is None or compte.etablissement_id != self.ecole.pk:
            return set()
        classes = set(classes_visibles_pour(compte).values_list("pk", flat=True))
        eleves_vus = set(eleves_visibles_pour(compte).values_list("pk", flat=True)) if compte.role in (Role.PARENT, Role.ELEVE) else None
        permis = set()
        for inscription in Inscription.objects.filter(eleve__in=self.eleves).select_related("classe"):
            if inscription.classe_id in classes and (eleves_vus is None or inscription.eleve_id in eleves_vus):
                permis.add(self.jetons[(inscription.eleve_id, inscription.classe.cycle)])
        return permis

    def parcourir(self, compte):
        """Visite toutes les adresses ; rend ({adresse: jetons lus}, nombre de pages en 200)."""
        client = Client(raise_request_exception=False)
        if compte is not None:
            client.force_login(compte)
        lus, pages = {}, 0
        pdf_vus = []

        def faux_pdf(contenu, *args, **kwargs):
            pdf_vus.append(contenu)
            return SimpleNamespace(err=0)

        with mock.patch("comptes.pdf.pisa.CreatePDF", side_effect=faux_pdf):
            for adresse in self.adresses():
                pdf_vus.clear()
                reponse = client.get(adresse)
                self.assertLess(reponse.status_code, 500, (compte, adresse, reponse.status_code))
                if reponse.status_code != 200:
                    continue
                pages += 1
                lus[adresse] = set(JETON.findall(texte_de(reponse) + " ".join(pdf_vus)))
        return lus, pages

    # ------------------------------------------------------------------------------------------------------------------
    def test_personne_ne_lit_le_numero_d_un_cycle_ou_d_un_eleve_qui_ne_le_concerne_pas(self):
        vus_par_profil = {}
        for nom, compte in self.profils.items():
            lus, pages = self.parcourir(compte)
            vus_par_profil[nom] = set().union(*lus.values()) if lus else set()
            permis = self.jetons_permis(compte)
            for adresse, jetons in lus.items():
                with self.subTest(profil=nom, adresse=adresse):
                    self.assertEqual(jetons - permis, set(), f"{nom} lit un numéro qui ne le concerne pas sur {adresse}")
        # Le contrôle n'est pas vide : l'administration lit bien des numéros, une autre école ou un visiteur n'en lit aucun.
        self.assertGreaterEqual(len(vus_par_profil["fondateur"]), 8)
        self.assertGreaterEqual(len(vus_par_profil["secretaire"]), 8)
        self.assertGreaterEqual(len(vus_par_profil["enseignant 6A"]), 1)
        self.assertGreaterEqual(len(vus_par_profil["parent de e1"]), 1)
        self.assertEqual(vus_par_profil["fondateur de l'autre école"], set())
        self.assertEqual(vus_par_profil["anonyme"], set())

    def test_le_directeur_du_1er_cycle_ne_lit_aucun_numero_des_autres_cycles(self):
        lus, _ = self.parcourir(self.dir_1er)
        vus = set().union(*lus.values())
        self.assertTrue(vus)
        self.assertTrue(all(jeton.endswith("AXQ") for jeton in vus), vus)

    def test_un_parent_ne_lit_que_les_numeros_de_son_enfant(self):
        lus, _ = self.parcourir(self.parent5)
        vus = set().union(*lus.values())
        self.assertTrue(vus)
        self.assertTrue(all(jeton.startswith(f"SNT{self.e5.pk}") for jeton in vus), vus)

    def test_la_page_publique_de_verification_ne_montre_que_le_numero_de_son_document(self):
        verification = VerificationDocument.objects.create(
            type_document=TypeDocumentVerifiable.CARTE_ELEVE, eleve=self.e5, inscription=self.i["e5"],
        )
        client = Client()
        for adresse in (reverse("scolarite:verifier_document", args=[verification.jeton]), reverse("vitrine:verifier") + f"?code={verification.code}"):
            with self.subTest(adresse=adresse):
                vus = set(JETON.findall(texte_de(client.get(adresse))))
                self.assertEqual(vus, {self.jetons[(self.e5.pk, Cycle.DEUXIEME_CYCLE)]})  # le numéro du cycle du document, pas celui de l'an dernier

    def test_le_matricule_d_origine_n_est_pas_devine_par_les_refus_de_la_saisie(self):
        """Le directeur du 1er cycle règle les numéros d'une classe de son cycle : aucun refus ne dit qu'un matricule ou un numéro d'un autre cycle existe."""
        self.client.force_login(self.dir_1er)
        adresse = reverse("scolarite:saisir_numeros_cycle", args=[self.c6a.pk])
        sonde = {
            "matricule d'un élève du 2ème cycle": self.e5.matricule,
            "numéro d'un élève du 2ème cycle": self.jetons[(self.e5.pk, Cycle.DEUXIEME_CYCLE)],
            "numéro d'un élève du lycée": self.jetons[(self.e7.pk, Cycle.LYCEE)],
            "valeur inconnue": "VALEUR-INCONNUE-1",
        }
        reponses = {}
        for nom, valeur in sonde.items():
            NumeroCycle.objects.filter(eleve=self.e1, cycle=Cycle.PREMIER_CYCLE).delete()
            reponse = self.client.post(adresse, {f"numero_{self.e1.pk}": valeur})
            reponses[nom] = (reponse.status_code, reponse["Location"] if reponse.status_code == 302 else "")
        self.assertEqual(len(set(reponses.values())), 1, reponses)  # la même réponse (enregistré) pour une valeur connue ou inconnue
