"""
Garde-fou d'isolation des données, sur TOUTES les routes de l'application.

Deux écoles (A et B) avec tous les rôles et des données dans chaque module. Les
routes sont énumérées automatiquement (get_resolver) : une page ajoutée plus tard
est donc testée sans qu'on ait à y penser, et un oubli de filtre par établissement
fait échouer ce test.

Vérifie : (1) aucun rôle de A ne voit ni ne modifie rien de B ; (2) un visiteur
non connecté n'atteint rien hors des pages publiques ; (3) dans une même école,
un élève, un parent, un enseignant, un bibliothécaire ou un membre du personnel
ne voit pas les données d'un autre élève ; (4) les pages de paie, de caisse et
d'administration restent fermées aux rôles sans rapport.
"""
import datetime
import re
import tempfile
import uuid

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from bibliotheque.models import Document
from communication.models import Annonce, Message, Portee
from comptes.models import Notification, Utilisateur, generer_matricule
from comptes.roles import Role, StatutCompte
from etablissement.models import Etablissement
from finances.models import Contrat, DemandeConge, Salaire, TypeConge, TypeContrat, TypeTranche, enregistrer_paiement
from pedagogie.models import Absence, CreneauEmploiDuTemps, Note, Trimestre
from permissions_matrix.models import PermissionMatrix
from scolarite.models import Affectation, AnneeScolaire, Classe, Cycle, Inscription
from tests_niveau.models import Candidat

# Marqueurs volontairement longs et improbables : un marqueur court (3 lettres) apparaît par
# hasard dans la clé 2FA ou le QR code (texte base32/base64 aléatoire) et ferait un faux positif.
PREFIXE = {"a": "zqxa", "b": "zqxb"}
TOUS_LES_ROLES = list(Role)
TELEPHONES = iter(range(70000000, 79999999))

PAGES_PUBLIQUES = (
    "vitrine:", "sante", "manifeste_pwa", "service_worker", "comptes:connexion", "comptes:inscription",
    "comptes:mot_de_passe_oublie", "comptes:reinitialiser_mot_de_passe", "comptes:verifier_email",
    "comptes:renvoyer_code", "comptes:verifier_2fa", "pedagogie:verifier_bulletin", "scolarite:verifier_document",
)


def creer_compte(role, tag, suffixe, etablissement, statut=StatutCompte.ACTIF):
    nom = f"{PREFIXE[tag]}{role.value}{suffixe}".replace("_", "")
    compte = Utilisateur(
        email=f"{nom}@t.test", prenom="Zq", nom=nom, role=role, etablissement=etablissement, statut=statut,
        is_active=(statut == StatutCompte.ACTIF), email_verifie=True,
        telephone=str(next(TELEPHONES)) if role == Role.PARENT else None,
    )
    if role == Role.ELEVE:
        compte.matricule = generer_matricule()
    compte.set_unusable_password()
    compte.save()
    return compte


def toutes_les_routes():
    """(nom, route, paramètres) de chaque route applicative, hors admin Django et fichiers statiques."""
    trouvees = []

    def parcourir(patterns, prefixe, espace):
        for p in patterns:
            if isinstance(p, URLResolver):
                sous_espace = (espace + ":" if espace else "") + p.namespace if p.namespace else espace
                parcourir(p.url_patterns, prefixe + str(p.pattern), sous_espace)
            elif isinstance(p, URLPattern):
                nom = f"{espace}:{p.name}" if espace and p.name else (p.name or prefixe + str(p.pattern))
                trouvees.append((nom, prefixe + str(p.pattern)))

    parcourir(get_resolver().url_patterns, "", "")
    resultat = []
    for nom, route in trouvees:
        if route.startswith(("admin/", "static", "media")):
            continue
        resultat.append((nom, route, re.findall(r"<(?:\w+:)?(\w+)>", route)))
    return resultat


def instancier(route, valeurs):
    return "/" + re.sub(r"<(?:\w+:)?(\w+)>", lambda m: str(valeurs.get(m.group(1), "1")), route)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class IsolationCompleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ecoles = {}
        for tag in ("a", "b"):
            ecole = Etablissement.objects.create(nom=f"Ecole{PREFIXE[tag]}")
            PermissionMatrix.seed_pour(ecole)
            cls.ecoles[tag] = ecole

    def setUp(self):
        self.d = {tag: self.creer_ecole(tag, ecole) for tag, ecole in self.ecoles.items()}
        self.routes = toutes_les_routes()

    def creer_ecole(self, tag, ecole):
        p = PREFIXE[tag]
        d = {"ecole": ecole, "comptes": {}}
        annee = AnneeScolaire.objects.create(
            etablissement=ecole, libelle=f"{p}-annee", date_debut=datetime.date(2026, 10, 1),
            date_fin=datetime.date(2027, 7, 31), est_active=True,
        )
        d["annee"] = annee
        classes = [
            Classe.objects.create(nom=f"{p}-classe{i}", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee) for i in (1, 2)
        ]
        for role in TOUS_LES_ROLES:
            d["comptes"][role] = creer_compte(role, tag, "", ecole)
        comptable = d["comptes"][Role.COMPTABLE]
        for i, classe in zip((1, 2), classes):
            eleve = creer_compte(Role.ELEVE, tag, f"x{i}", ecole)
            parent = creer_compte(Role.PARENT, tag, f"x{i}", ecole)
            eleve.parents_lies.add(parent)
            prof = creer_compte(Role.ENSEIGNANT, tag, f"x{i}", ecole)
            inscription = Inscription.objects.create(eleve=eleve, classe=classe)
            affectation = Affectation.objects.create(enseignant=prof, classe=classe, matiere=f"{p}mat{i}", coefficient=2)
            Note.objects.create(
                eleve=eleve, affectation=affectation, trimestre=list(Trimestre)[0], note_classe=12,
                note_composition=28, valeur=13, enregistre_par=prof,
            )
            Absence.objects.create(
                eleve=eleve, classe=classe, date_absence=datetime.date(2026, 11, 3), motif=f"{p}motif{i}",
                enregistre_par=prof,
            )
            Message.objects.create(
                etablissement=ecole, eleve=eleve, expediteur=parent, destinataire=prof, contenu=f"{p}secret{i}",
            )
            d[f"x{i}"] = {
                "eleve": eleve, "parent": parent, "prof": prof, "classe": classe, "affectation": affectation,
                "paiement": enregistrer_paiement(
                    eleve=eleve, inscription=inscription, tranche=TypeTranche.VERSEMENT, montant=15000,
                    mode_paiement="especes", enregistre_par=comptable,
                ),
                "salaire": Salaire.objects.create(employe=prof, periode=f"2026-1{i}", montant=100000, enregistre_par=comptable),
                "contrat": Contrat.objects.create(
                    employe=prof, etablissement=ecole, type_contrat=TypeContrat.CDI, poste=f"{p}poste{i}",
                    date_debut=datetime.date(2026, 1, 1), salaire_base=90000, cree_par=comptable,
                ),
                "creneau": CreneauEmploiDuTemps.objects.create(
                    classe=classe, affectation=affectation, jour_semaine=1, heure_debut=datetime.time(8),
                    heure_fin=datetime.time(9), salle=f"{p}salle{i}",
                ),
                "candidat": Candidat.objects.create(prenom="Zq", nom=f"{p}candidat{i}", classe_visee=classe, cree_par=comptable),
            }
            DemandeConge.objects.create(
                employe=prof, etablissement=ecole, type_conge=TypeConge.PAYE, date_debut=datetime.date(2026, 12, 1),
                date_fin=datetime.date(2026, 12, 5), enregistre_par=comptable,
            )
        Document.objects.create(titre=f"{p}-doc", etablissement=ecole, fichier=ContentFile(b"x", name=f"{p}.pdf"), ajoute_par=comptable)
        Annonce.objects.create(titre=f"{p}-annonce", etablissement=ecole, contenu="c", portee=Portee.TOUTE_ECOLE, auteur=comptable)
        d["notification"] = Notification.objects.create(
            destinataire=d["comptes"][Role.SECRETAIRE], etablissement=ecole, titre=f"{p}-notif", message="m", url="/",
        )
        d["en_attente"] = creer_compte(Role.ENSEIGNANT, tag, "attente", ecole, statut=StatutCompte.EN_ATTENTE_VALIDATION)
        return d

    # --- outils ---------------------------------------------------------------------------
    def valeurs(self, tag, n=1):
        x, d = self.d[tag][f"x{n}"], self.d[tag]
        return {
            "matricule": x["eleve"].matricule, "classe_id": x["classe"].id, "paiement_id": x["paiement"].id,
            "salaire_id": x["salaire"].id, "contrat_id": x["contrat"].id, "affectation_id": x["affectation"].id,
            "creneau_id": x["creneau"].id, "candidat_id": x["candidat"].id, "eleve_id": x["eleve"].id,
            "autre_id": x["prof"].id, "annee_id": d["annee"].id, "utilisateur_id": d["en_attente"].id,
            "notification_id": d["notification"].id, "jeton": uuid.uuid4(), "decision": "admis",
            "slug": d["ecole"].slug, "etablissement_id": d["ecole"].id, "uidb64": "x", "token": "y",
        }

    def appeler(self, compte, methode, url):
        if compte is None:
            self.client.logout()
        else:
            self.client.force_login(compte)
        return getattr(self.client, methode)(url, follow=False)

    @staticmethod
    def texte(reponse):
        if reponse.status_code != 200 or any(t in reponse.get("Content-Type", "") for t in ("pdf", "zip", "image")):
            return ""
        return reponse.content.decode("utf-8", errors="ignore").lower()

    @staticmethod
    def ignorer(nom, route):
        return nom.endswith(("deconnexion", "quitter_acces_delegue")) or "verifier" in route or nom.startswith("vitrine")

    # --- 1. entre écoles ------------------------------------------------------------------
    def test_aucun_role_de_lecole_a_ne_voit_ni_ne_modifie_lecole_b(self):
        marqueurs_b = [PREFIXE["b"], f"ecole{PREFIXE['b']}", *(str(self.d["b"][f"x{i}"]["eleve"].matricule) for i in (1, 2))]
        valeurs_b = self.valeurs("b")
        fuites = []
        for role, compte in self.d["a"]["comptes"].items():
            for nom, route, params in self.routes:
                if self.ignorer(nom, route) or nom.startswith("comptes:reinitialiser"):
                    continue
                if not params:
                    url = "/" + route + ("?q=zqx" if "json" in route or "recherche" in route else "")
                    methodes = ("get",)
                else:
                    url, methodes = instancier(route, valeurs_b), ("get", "post")
                for methode in methodes:
                    reponse = self.appeler(compte, methode, url)
                    texte = self.texte(reponse)
                    trouves = [m for m in marqueurs_b if m in texte]
                    if trouves:
                        fuites.append(f"{role.value} {methode.upper()} {nom} montre {trouves}")
                    if params and methode == "post" and reponse.status_code == 200:
                        fuites.append(f"{role.value} POST {nom} accepté sur un objet de l'autre école")
        self.assertEqual(fuites, [], "\n".join(fuites))

        b = self.d["b"]
        for i in (1, 2):
            x = b[f"x{i}"]
            for objet in (x["paiement"], x["salaire"], x["candidat"]):
                objet_avant = type(objet).objects.get(pk=objet.pk)
                self.assertEqual(objet_avant.__dict__.get("est_supprime", False), False)
            self.assertEqual(Candidat.objects.get(pk=x["candidat"].pk).decision, "en_attente")
            self.assertTrue(Affectation.objects.filter(pk=x["affectation"].pk).exists())
            self.assertTrue(CreneauEmploiDuTemps.objects.filter(pk=x["creneau"].pk).exists())
            self.assertTrue(Classe.objects.filter(pk=x["classe"].pk).exists())
        self.assertEqual(Utilisateur.objects.get(pk=b["en_attente"].pk).statut, StatutCompte.EN_ATTENTE_VALIDATION)
        self.assertIsNone(Notification.objects.get(pk=b["notification"].pk).lue_le)
        for role, compte in b["comptes"].items():
            rafraichi = Utilisateur.objects.get(pk=compte.pk)
            self.assertEqual((rafraichi.role, rafraichi.statut), (role, StatutCompte.ACTIF), f"compte B {role.value} modifié")

    # --- 2. visiteur non connecté ---------------------------------------------------------
    def test_visiteur_anonyme_naccede_quaux_pages_publiques(self):
        valeurs = self.valeurs("a")
        ouvertes = []
        for nom, route, _ in self.routes:
            for methode in ("get", "post"):
                reponse = self.appeler(None, methode, instancier(route, valeurs))
                renvoi = reponse.get("Location", "")
                vers_connexion = reponse.status_code in (301, 302) and ("/connexion" in renvoi or renvoi in ("/", ""))
                if reponse.status_code == 200 and not nom.startswith(PAGES_PUBLIQUES):
                    ouvertes.append(f"{methode.upper()} {nom} -> 200")
                elif reponse.status_code in (301, 302) and not vers_connexion and not nom.startswith(PAGES_PUBLIQUES):
                    ouvertes.append(f"{methode.upper()} {nom} -> {reponse.status_code} {renvoi}")
        self.assertEqual(ouvertes, [], "\n".join(ouvertes))

    # --- 3. dans une même école -----------------------------------------------------------
    def test_eleve_parent_enseignant_personnel_ne_voient_pas_un_autre_eleve(self):
        valeurs_2 = self.valeurs("a", 2)
        x2 = self.d["a"]["x2"]
        marqueurs_2 = [
            str(x2["eleve"].matricule), x2["eleve"].nom.lower(), x2["prof"].nom.lower(), x2["parent"].nom.lower(),
            f"{PREFIXE['a']}mat2", f"{PREFIXE['a']}secret2", f"{PREFIXE['a']}motif2", f"{PREFIXE['a']}salle2",
        ]
        acteurs = {
            "élève": self.d["a"]["x1"]["eleve"], "parent": self.d["a"]["x1"]["parent"],
            "enseignant": self.d["a"]["x1"]["prof"], "bibliothécaire": self.d["a"]["comptes"][Role.BIBLIOTHECAIRE],
            "personnel": self.d["a"]["comptes"][Role.PERSONNEL],
        }
        fuites = []
        for libelle, compte in acteurs.items():
            for nom, route, params in self.routes:
                if self.ignorer(nom, route) or nom.startswith("comptes:reinitialiser"):
                    continue
                url = instancier(route, valeurs_2) if params else "/" + route + ("?q=zqx" if "json" in route or "recherche" in route else "")
                for methode in ("get", "post") if params else ("get",):
                    reponse = self.appeler(compte, methode, url)
                    trouves = sorted({m for m in marqueurs_2 if m in self.texte(reponse)})
                    if trouves:
                        fuites.append(f"{libelle} {methode.upper()} {nom} montre {trouves}")
        self.assertEqual(fuites, [], "\n".join(fuites))

    # --- 4. moindre privilège -------------------------------------------------------------
    def test_paie_caisse_et_administration_fermees_aux_roles_sans_rapport(self):
        valeurs = self.valeurs("a")
        pages = [
            "finances:liste_salaires", "finances:liste_contrats", "finances:liste_conges", "finances:registre_caisse",
            "finances:journal_caisse_syscohada", "finances:journal_caisse_syscohada_csv", "finances:bulletin_paie_pdf",
            "finances:exporter_recu_paiement_pdf", "comptes:comptes_en_attente", "espace_developpeur:journal_audit",
            "espace_developpeur:liste_comptes", "espace_developpeur:matrice_permissions",
        ]
        routes = {nom: route for nom, route, _ in self.routes}
        sans_rapport = (Role.ENSEIGNANT, Role.PARENT, Role.ELEVE, Role.BIBLIOTHECAIRE, Role.PERSONNEL)
        ouvertes = []
        for nom in pages:
            for role in sans_rapport:
                reponse = self.appeler(self.d["a"]["comptes"][role], "get", instancier(routes[nom], valeurs))
                if reponse.status_code != 403:
                    ouvertes.append(f"{role.value} -> {nom}: {reponse.status_code}")
        self.assertEqual(ouvertes, [], "\n".join(ouvertes))
