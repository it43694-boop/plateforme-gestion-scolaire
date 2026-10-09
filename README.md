# Nexora Éducation — plateforme de gestion scolaire

**Toute votre école. Une seule vision.** Nexora est le logiciel de gestion scolaire
multi-établissement développé ici, en Django.
Le cahier des charges d'Omega Académie (Mali) a servi de spécification
fonctionnelle de référence pour construire l'application, mais **le
logiciel lui-même est générique** : chaque établissement qui le déploie
configure son propre nom, son propre logo et sa propre devise — rien
n'est codé en dur pour un établissement en particulier.

## Configurer l'identité de votre établissement

Après la première connexion avec un compte `developpeur`, rendez-vous sur
`/espace-developpeur/etablissement/` pour renseigner :
- le nom de l'établissement (affiché partout : connexion, barre latérale,
  emails automatiques) ;
- un logo (facultatif — à défaut, l'initiale du nom est utilisée) ;
- une devise ou un slogan (facultatif).

Ces informations sont stockées dans un enregistrement unique
(`etablissement.Etablissement`) et injectées automatiquement dans toutes
les pages et tous les emails via un processeur de contexte
(`comptes/context_processors.py`) — aucun autre fichier n'a besoin d'être
modifié pour personnaliser l'identité visuelle d'un déploiement.

## Versionner l'application

Le fichier `VERSION` à la racine contient le numéro de version actuel
(format [semver](https://semver.org/lang/fr/) : `MAJOR.MINOR.PATCH`).
Ce système démarre à la version `1.0.0`, **à partir de maintenant** — il
ne couvre pas rétroactivement les phases déjà livrées avant sa mise en
place (voir les sections "État du projet : Phase N" ci-dessous, qui
restent l'historique informel de ce qui a été construit avant).

Pour publier une nouvelle version :
1. Mettre à jour le fichier `VERSION` (`1.0.0` → `1.1.0` pour une
   nouvelle fonctionnalité, `1.0.1` pour un correctif, `2.0.0` pour un
   changement qui casse quelque chose, ex. une migration de données
   lourde ou un comportement existant modifié).
2. Committer ce changement, puis créer un tag git annoté :
   `git tag -a v1.1.0 -m "Description courte"` et `git push --tags`.
3. Le tag apparaît automatiquement dans l'onglet *Releases* du dépôt
   GitHub et permet de revenir précisément à cet état si besoin.

Le numéro de version est lu depuis ce fichier au démarrage de Django
(`settings.APP_VERSION`) et affiché discrètement dans la barre latérale
pour le rôle `developpeur` uniquement — utile pour savoir en un coup
d'œil quelle version tourne sur un déploiement donné.

## État du projet : Phase 8 — Modules manquants, sécurité, pagination, page d'accueil

En plus de la Phase 7, cette livraison ajoute :

- **Page d'accueil publique** (`/`), inspirée d'une maquette fournie par
  l'utilisateur : hero avec icônes flottantes, bandeau défilant des
  modules, grille de fonctionnalités, bloc sécurité — construite avec le
  système de design du logiciel, pas une copie de la maquette
- **Nom du logiciel** : voir « Phase 49 — Identité Nexora » plus bas. Distinct
  du nom de chaque établissement (ancien nom : « L'éducation du Mali au
  service de l'avenir »)
- **Deux modules du cahier des charges qui n'avaient aucune vue réelle**
  sont maintenant construits :
  - **Suivi des cours** : vue d'ensemble direction par classe (affectations,
    notes saisies, absences saisies, dernière activité), cloisonnée par cycle
  - **Tests de niveau** : suivi des candidats, décision admis/refusé,
    cloisonné par cycle, avec raccourci vers l'inscription une fois admis
  - **Assistant** : recherche d'un élève par matricule, restituant
    uniquement les données que le rôle courant est déjà autorisé à voir
    (mêmes règles de visibilité que le reste de l'application — pas de
    raccourci qui les contournerait). Sans IA générative, conformément au
    mode par défaut du cahier des charges
- **Failles de sécurité corrigées** : validateurs de taille sur tous les
  fichiers uploadés (documents, pièces jointes, logo), limites anti-abus
  sur l'import zip (nombre de fichiers, taille totale), et surtout un
  **verrou anti-force-brute sur le code de vérification email** qui
  n'existait pas (le code s'invalide après 5 tentatives incorrectes)
- **Pagination** ajoutée à toutes les listes qui pouvaient devenir longues
  (paiements, salaires, comptes, documents, annonces, historique d'absences)
- **Bulletin** : calcule désormais une moyenne par trimestre et une
  moyenne générale, plutôt qu'une liste brute de notes
- **Historique d'absences** : affiche le total, les justifiées et les
  non-justifiées
- 217 tests au total, tous passent

### Deux nouveaux bugs de matrice de permissions trouvés en écrivant les tests

En construisant « Suivi des cours », j'ai découvert que le rôle
`enseignant` y avait accès par défaut — alors que le cahier des charges le
décrit explicitement comme une « vue d'ensemble **direction** ». Corrigé
par une migration dédiée
(`permissions_matrix/migrations/0004_correction_suivi_cours_enseignant.py`),
selon le même principe que la correction précédente sur les absences.

### Ce qui reste ouvert

- Les tests de charge et la recette utilisateur formelle restent à faire
- L'Assistant est volontairement minimal (recherche par matricule) ; le
  cahier des charges prévoit une activation future avec clé API pour un
  mode génératif, non implémentée ici

## Démarrage rapide (développement local)

Le projet est livré prêt à l'emploi : un fichier `.env` de développement
et une base SQLite avec un compte développeur de test sont déjà inclus.

```bash
python -m venv venv
source venv/bin/activate          # Windows : venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py runserver
```

Rendez-vous sur http://127.0.0.1:8000/comptes/connexion/

**Compte développeur de test déjà créé :**
- Email : `developpeur@example.com`
- Mot de passe : `DevAdmin#2026!`

Pour explorer avec des données réalistes (année scolaire, classes,
comptes secrétariat/comptable, et un établissement de démonstration
nommé « École Démonstration ») :

```bash
python manage.py seed_donnees_demo
```

⚠️ Ce compte et la base SQLite fournie sont uniquement destinés à explorer
le projet en local. Pour un déploiement réel, repartez de `.env.example`,
générez une nouvelle `DJANGO_SECRET_KEY`, laissez `python manage.py
migrate` créer une base neuve (PostgreSQL en production), puis configurez
l'identité de votre établissement comme décrit plus haut.

En développement, les emails (code de vérification, réinitialisation de
mot de passe) s'affichent dans la console plutôt que d'être réellement
envoyés (`EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`).

## Lancer les tests

```bash
python manage.py test
```

## Assistant — mode génératif optionnel (Groq)

L'Assistant fonctionne par défaut en mode recherche simple (aucune IA
générative), conformément au cahier des charges de référence. Pour
activer le mode génératif :

1. Créez une clé sur [console.groq.com](https://console.groq.com)
2. Renseignez `GROQ_API_KEY` dans votre `.env` (jamais dans le code, jamais commité)
3. Optionnel : ajustez `ASSISTANT_MODELE_IA` (par défaut `llama-3.3-70b-versatile`)

**Garantie de sécurité** (`assistant/services.py`) : la fonction qui
appelle l'API ne reçoit et n'envoie **que** le dictionnaire de données déjà
filtré par la matrice de permissions — jamais un accès à la base, jamais
d'outil, jamais de requête que l'IA pourrait construire elle-même. Le
filtrage a lieu **avant** l'appel, pas sur la promesse que le modèle se
limitera de lui-même face à une question qui sort du rôle de la personne.
Vérifié par des tests qui inspectent directement ce qui part réellement
vers l'API (`assistant/tests.py::AssistantModeGeneratifTests`) : un
enseignant qui interroge l'Assistant n'envoie jamais de données
financières, un comptable n'envoie jamais de notes — quelle que soit la
question posée.

## Structure du projet

```
config/                  Paramètres Django, URLs racine
vitrine/                 Page d'accueil publique
etablissement/           Identité configurable (nom, logo, devise) d'un déploiement
comptes/                 Utilisateurs, rôles, authentification, audit
permissions_matrix/      Matrice de permissions modulaire
scolarite/               Années scolaires, classes, élèves, enseignants
tests_niveau/            Candidats, tests de niveau, décision admis/refusé
finances/                Paiements, Caisse, Salaires
pedagogie/               Notes, absences, emploi du temps, suivi des cours
assistant/               Recherche d'élève à partir des données autorisées
bibliotheque/            Documents (ajout unitaire, import/export zip)
communication/           Annonces avec notification email
statistiques/            Tableaux de bord agrégés
espace_developpeur/      Gestion des comptes/rôles, matrice de permissions, identité
templates/               Templates HTML (Bootstrap 5 + système de design maison)
static/css/toumai.css    Système de design (jetons, composants, mise en page)
```

## Points clés d'architecture

### Rôles et matrice de permissions
Les rôles sont fixes (définis dans `comptes/roles.py`), conformément au
cahier des charges de référence. La matrice de permissions
(`permissions_matrix`), elle, est modifiable sans redéploiement : c'est
elle qui décide, module par module, si un rôle y a accès. Les rôles
`développeur`, `fondateur` et `administrateur_general` ont un accès total
inconditionnel, qui ne passe jamais par la matrice.

La matrice par défaut (`permissions_matrix/matrice_par_defaut.py`) est une
**interprétation documentée** du tableau de rôles du cahier des charges de
référence, là où celui-ci ne précise pas explicitement chaque module (ex.
accès à l'Assistant ou à la Bibliothèque pour tel rôle). Elle reste
ajustable à tout moment depuis `/espace-developpeur/matrice-permissions/`
ou l'admin Django, sans toucher au code.

### Identité de l'établissement
Le modèle `etablissement.Etablissement` accepte plusieurs établissements
dans une même base. Les comptes et objets métier portent leur établissement
et les vues, l'admin et les permissions filtrent ce périmètre. Une
installation mono-établissement reste possible, mais n'est plus une
contrainte d'architecture.

### Sécurité
- Mots de passe : 10 caractères minimum, majuscule + chiffre + caractère
  spécial obligatoires (`comptes/validators.py`)
- Verrouillage automatique après 5 échecs de connexion (15 minutes)
- Session expirée après 30 minutes d'inactivité
- Journal d'audit en base (`comptes.JournalAudit`) : ajout seul, aucune
  vue d'édition ou de suppression n'est exposée, y compris pour les
  superutilisateurs
- En production (`DEBUG=False`) : redirection HTTPS forcée, cookies
  sécurisés, HSTS activé

### Déploiement
Le fichier `render.yaml` déploie l'application sur Render avec une base
PostgreSQL managée — personnalisez le nom du service et les domaines
avant de déployer. Pour un autre hébergeur (AWS, GCP, VPS...), le
`Procfile` fonctionne avec n'importe quel buildpack compatible gunicorn ;
seules les variables d'environnement de `.env.example` doivent être
renseignées côté plateforme. Le nom et le logo affichés dans
l'application se configurent ensuite depuis l'espace développeur, pas
dans les fichiers de déploiement.

## État du projet : Phase 9 — Audit de sécurité expert et finitions

- **Limite de débit** (django-ratelimit) sur le renvoi de code, le mot de
  passe oublié, la connexion, et l'Assistant IA (20 questions/heure) —
  protège contre le spam et contre une facture Groq incontrôlée. ⚠️
  Nécessite Redis en production multi-workers (voir commentaire dans
  `config/settings.py`, section CACHES) : avec le cache mémoire local,
  chaque worker gunicorn a ses propres compteurs.
- **Validation du type de fichier** sur les documents et pièces jointes
  (extension autorisée), en plus de la taille déjà vérifiée
- **Course critique corrigée** sur la génération de matricule : réessai
  automatique en cas de collision entre deux inscriptions simultanées
- **Bulletin exportable en PDF**, **statistiques exportables en CSV**
  (encodage UTF-8 + BOM pour un affichage correct des accents dans Excel)
- **Deux bugs multi-établissement supplémentaires trouvés et corrigés** :
  l'inscription d'élève n'attribuait jamais d'établissement au nouveau
  compte ; le sélecteur d'année scolaire des statistiques n'était pas
  filtré par établissement
- 217 tests au total, tous passent

### Ce qui reste ouvert après cet audit

- Emails en texte brut uniquement (pas de gabarit HTML habillé)
- Les fournisseurs SMS, WhatsApp et Mobile Money restent des connecteurs à
  configurer selon le prestataire choisi
- Les tests de charge et la recette utilisateur formelle restent à faire

### Fonctionnalités métier livrées

- Tableau de bord opérationnel avec indicateurs et actions rapides par rôle
- Portail parent limité aux enfants liés, avec absences, moyenne et solde
- Bourses, réductions et exonérations rattachées aux inscriptions
- Relances d'impayés via `python manage.py relancer_impayes`
- Notifications internes persistantes et file email avec reprise
- Historique des corrections de notes
- Présence du personnel, transferts détaillés et archivage des années scolaires
- Vérification publique des bulletins par jeton et QR code si `qrcode` est installé
- Import Excel transactionnel des élèves avec aperçu :
  `python manage.py importer_eleves_excel fichier.xlsx --etablissement ID --dry-run`
- Centre de notifications avec lecture individuelle et marquage global
- Présence, aides et transferts accessibles dans l'administration Django cloisonnée

## État du projet : Phase 10 — Sécurité renforcée, différenciation métier, design

- **IP de confiance** (`comptes/utils.py::ip_client_fiable`) : le journal
  d'audit et le rate-limiting s'appuient désormais sur le dernier maillon de
  `X-Forwarded-For` (celui ajouté par le proxy de la plateforme, pas celui
  déclaré par le client) - `NB_PROXYS_CONFIANCE` ajuste le nombre de sauts.
- **Attribution des rôles à accès total restreinte** : développeur, fondateur
  et administrateur général ne sont plus attribuables depuis l'espace
  développeur (uniquement en console), pour limiter la portée d'un compte
  développeur compromis.
- **Authentification à deux facteurs (TOTP)**, activable en self-service
  (`/comptes/2fa/activer/`) pour tout compte, recommandée pour les rôles à
  privilège élevé. Non forcée à l'activation - une politique d'obligation par
  rôle reste à décider séparément.
- **Content-Security-Policy** avec nonce par requête (`comptes/middleware.py`),
  `/healthz` pour la supervision, pages d'erreur 400/403/404/500
  personnalisées, Dockerfile et `docker-compose.yml` pour un environnement
  reproductible, couverture de tests mesurée en CI.
- **Coefficients et classement** : `Affectation.coefficient` (1 par défaut)
  pondère désormais le calcul des moyennes du bulletin ; le rang de l'élève
  dans sa classe s'affiche à côté de la moyenne générale (web et PDF).
  Le rattrapage/repêchage n'est volontairement pas couvert.
- **Devise réellement configurable par établissement**
  (`Etablissement.code_devise`, `Etablissement.pas_montant`) : le FCFA n'est
  plus codé en dur, chaque établissement fixe sa monnaie et son pas de
  saisie des frais de scolarité depuis `/espace-developpeur/etablissement/`.
- **Numérotation séquentielle des reçus** (`finances.SequenceReference`) :
  remplace un tirage aléatoire dont la vérification d'unicité portait par
  erreur sur la mauvaise table pour les reçus et les salaires. La séquence
  est désormais par établissement, sous verrou de ligne, sans trou possible.
- **Messagerie directe parent ↔ enseignant** (`communication.Message`), à
  propos d'un élève précis, avec les mêmes règles de visibilité que le reste
  de l'application (le parent doit être lié à l'élève, l'enseignant doit
  réellement lui enseigner).
- **Mode sombre** suivant la préférence système, polices auto-hébergées
  (Fraunces/Public Sans, fini la dépendance à Google Fonts au chargement),
  jeu d'icônes SVG en ligne dans la coquille applicative, bulletin PDF refait
  aux couleurs de la plateforme avec logo et bloc signature.
- 256 tests au total, tous passent (hors 5 erreurs propres à Windows sans
  rapport avec cette phase - verrou de fichier temporaire Excel dans
  `ImporterElevesExcelTests`, absentes sous Linux/macOS et en CI).

### Ce qui reste ouvert après cette phase

- 2FA non obligatoire pour l'instant, même pour les rôles à privilège élevé
- Le jeu d'icônes couvre la coquille applicative (barre latérale, barre
  supérieure), pas chaque page individuellement
- CSP : `style-src` reste en `'unsafe-inline'` (de nombreux gabarits utilisent
  des attributs `style=""` ; les retirer un par un est un chantier séparé)

## État du projet : Phase 11 — 2FA obligatoire, emails habillés, audit de la matrice de permissions

- **2FA désormais obligatoire** pour les rôles à privilège élevé
  (`comptes.roles.ROLES_2FA_OBLIGATOIRE` : développeur, fondateur,
  administrateur général, super administrateur, comptable) via
  `comptes.middleware.ForcerActivation2FAMiddleware` : tant que la 2FA
  n'est pas activée, seules la page d'activation, la déconnexion et
  `/healthz` restent joignables - jamais de verrouillage définitif, la
  personne peut toujours terminer l'activation ou se déconnecter. Un
  drapeau `settings.TESTING` (détecté depuis `sys.argv`) désactive ce
  middleware pendant `manage.py test`, pour ne pas exiger la 2FA sur
  chaque compte de test créé ailleurs dans la suite ; le comportement réel
  du middleware, lui, est vérifié explicitement avec
  `@override_settings(TESTING=False)`.
- **`permissions_matrix` (le moteur de permissions fail-closed) a maintenant
  sa propre suite de tests directs** (accès total inconditionnel, refus par
  défaut en l'absence de règle, cloisonnement strict entre établissements,
  fidélité et idempotence de `seed_pour`, contrainte d'unicité) - jusqu'ici
  il n'était exercé qu'indirectement par les tests des autres apps.
- **Emails habillés en HTML** (`templates/emails/base_email.html`, couleurs
  de la plateforme) avec repli en texte brut, sur les deux chemins d'envoi
  (synchrone et file différée `EmailOutbox`) via un unique point de
  construction (`comptes/mail.py::construire_corps_html`) pour qu'ils
  restent identiques.
- **Assistant IA** : le modèle Groq par défaut (`llama-3.3-70b-versatile`,
  décommissionné par Groq mi-2026) est remplacé par `openai/gpt-oss-120b` ;
  ajout d'un mode « vue d'ensemble » sans matricule, qui répond sur
  l'établissement à partir d'agrégats scopés aux modules du rôle
  (`assistant/views.py::construire_donnees_generales`), en plus du mode
  existant centré sur un élève précis.
- **Badges d'icônes colorés et micro-animations** étendus du tableau de
  bord à l'ensemble des listes principales (élèves, paiements, classes,
  absences, salaires, caisse, annonces, bibliothèque).
- 282 tests au total, tous passent (hors erreurs propres à Windows sans
  rapport avec cette phase, absentes sous Linux/macOS et en CI).

### Ce qui reste ouvert après cette phase

- SMS, WhatsApp et Mobile Money restent des connecteurs à configurer selon
  le prestataire choisi - aucun n'est câblé dans le code (nécessite un
  compte et des clés chez le prestataire retenu, aucune voie sans compte
  n'existe côté opérateurs/Meta)
- CSP : `style-src` reste en `'unsafe-inline'` (chantier séparé, inchangé)
- Les tests de charge et la recette utilisateur formelle restent à faire
- Rattrapage/repêchage toujours volontairement non couvert

## État du projet : Phase 12 — Sauvegardes locales planifiables, Sentry vérifié en conditions réelles

- **`SENTRY_DSN` vérifié en conditions réelles** : un événement de test
  envoyé depuis ce dépôt est bien apparu dans le tableau de bord Sentry -
  la supervision d'erreurs est confirmée active sur le déploiement.
- **Commande `manage.py sauvegarder_donnees`** : sauvegarde la base de
  données (SQLite en local, `pg_dump` en PostgreSQL) et les médias (copie
  locale, ou téléchargement complet du bucket S3/Supabase Storage si
  `AWS_STORAGE_BUCKET_NAME` est renseigné) vers `--destination DOSSIER`,
  avec purge des sauvegardes de plus de `--garder-jours` jours (30 par
  défaut). Volontairement **jamais automatique côté serveur** : le plan
  gratuit utilisé n'a ni disque persistant ni tâches planifiées - la
  commande est conçue pour tourner depuis un poste local, sur la base et
  le bucket de production via les mêmes variables d'environnement
  (`DATABASE_URL`, `AWS_*`) que celles déjà utilisées pour Render, jamais
  de secret codé en dur. Voir la section « Sauvegardes locales »
  ci-dessous pour la planifier avec les Tâches planifiées Windows.
- 288 tests au total, tous passent (hors erreurs Windows connues et sans
  rapport, absentes sous Linux/macOS et en CI).

### Ce qui reste ouvert après cette phase

- La sauvegarde reste manuelle à planifier (Tâches planifiées Windows ou
  cron) - rien ne la déclenche tant que l'administrateur ne l'a pas configurée
- Aucune restauration n'a encore été testée à partir d'une sauvegarde produite
  par cette commande - une sauvegarde jamais restaurée n'est pas considérée
  comme fiable
- SMS, WhatsApp, Mobile Money, CSP `unsafe-inline`, tests de charge et
  rattrapage : toujours ouverts, inchangés depuis la phase précédente

## État du projet : Phase 13 — Confirmations, recherche globale, emploi du temps visuel, CSP durcie

- **Confirmation avant suppression** (`data-confirmer` sur les formulaires
  POST, géré dans `app.js` sans JS en ligne) sur les suppressions de
  paiement/salaire et le refus d'une demande de compte.
- **Blocage anti-double-soumission** : tout formulaire POST de
  l'application désactive son bouton d'envoi (avec un repère de
  chargement animé) dès la soumission.
- **Relance WhatsApp manuelle** (`comptes/utils.py::lien_whatsapp`) sur la
  page Suivi des paiements - un lien `wa.me` pré-rempli, sans clé API ni
  compte prestataire, pour les rôles n'ayant pas de solution SMS/WhatsApp
  automatisée.
- **Recherche globale** : une barre de recherche dans la barre supérieure
  (visible seulement pour les rôles ayant le module Élèves) trouve un
  élève par nom, prénom ou matricule, avec le même cloisonnement que la
  liste des élèves.
- **Emploi du temps en grille hebdomadaire** (une colonne par jour, Lundi
  à Samedi, y compris les jours vides) à la place du tableau plat.
- **CSP `style-src` sans `unsafe-inline`** : les 170 attributs `style=""`
  des gabarits web ont été déplacés vers des classes CSS. Vérifié avec
  l'événement navigateur `securitypolicyviolation` (pas seulement une
  relecture du code) sur 39 pages couvrant 3 rôles : aucune violation.
  Les gabarits PDF (xhtml2pdf) et l'email HTML restent inline par
  nécessité - ils ne sont jamais servis au navigateur avec cet en-tête.
- 303 tests au total, tous passent (hors erreurs Windows connues et sans
  rapport).

### Ce qui reste ouvert après cette phase

- SMS, WhatsApp et Mobile Money automatisés (connecteur prestataire),
  tests de charge, restauration de sauvegarde jamais testée, et
  rattrapage : toujours ouverts
- La grille visuelle de l'emploi du temps ne détecte pas les conflits de
  salle (la classe et l'enseignant, si)
- Pas encore d'indicateur de chargement pour les actions longues (export
  PDF, question à l'Assistant IA) au-delà du bouton d'envoi

## État du projet : Phase 14 — Conflits de salle, indicateurs de chargement, notifications, transition de thème

- **Détection des conflits de salle** dans l'emploi du temps
  (`CreneauEmploiDuTemps.clean()`) : impossible d'enregistrer un créneau
  si la même salle est déjà occupée sur un horaire chevauchant, le même
  jour, dans le même établissement - à côté du contrôle existant sur
  l'enseignant. Un champ salle vide n'ajoute jamais de conflit, et deux
  établissements différents ne se gênent jamais entre eux.
- **Indicateur de chargement** sur les liens d'export PDF/CSV (attribut
  `data-telechargement`, ajouté aux 6 gabarits concernés : bibliothèque,
  paiements, bulletin, emploi du temps, statistiques finances, vue
  d'ensemble) et sur la recherche de l'Assistant IA (formulaire GET) : le
  lien ou bouton affiche un repère animé le temps du téléchargement, sans
  bloquer de nouveaux clics au-delà du nécessaire.
- **Notifications "toast"** : les messages Django (succès, erreur, info)
  s'affichent désormais en superposition en haut à droite (bas de l'écran
  en mobile), avec disparition automatique après 6 secondes ou fermeture
  manuelle, au lieu d'un bandeau statique en haut du contenu.
- **Transition douce entre les modes clair et sombre** : le changement de
  thème anime les couleurs de fond, de texte et de bordure sur les
  éléments principaux (page, cartes, tableaux, formulaires, boutons) au
  lieu d'un changement instantané. Neutralisée automatiquement par
  `prefers-reduced-motion`, comme toutes les autres animations de
  l'application.
- Vérifié en conditions réelles au navigateur (Playwright) : conflit de
  salle refusé côté formulaire, superposition du toast avec la barre
  supérieure corrigée après une première position incorrecte, repère de
  chargement posé puis retiré sur l'export PDF, transition de thème
  visible sans accroc.
- **Cycle sauvegarde → restauration vérifié en local** : `manage.py
  sauvegarder_donnees` exécuté sur la base SQLite de développement, puis
  la copie produite comparée à l'originale (39/39 tables, même nombre de
  lignes sur une table de référence, `PRAGMA integrity_check` = `ok` sur
  les deux fichiers). La restauration d'une sauvegarde SQLite consiste à
  recopier ce fichier à la place de la base active, ce qui est
  exactement ce que ce contrôle valide.

### Ce qui reste ouvert après cette phase

- SMS, WhatsApp et Mobile Money automatisés (connecteur prestataire) et
  tests de charge : toujours bloqués en attente d'un choix de prestataire
  et de clés d'accès côté commanditaire - aucune tentative de simulation
  n'a été faite pour ces deux points.
- Rattrapage : toujours hors périmètre tant que non redemandé
  explicitement.
- Le cycle sauvegarde → restauration n'a été vérifié qu'en local sur
  SQLite. En production (PostgreSQL + bucket S3/R2), la même vérification
  (restaurer un `pg_dump` sur une base de test et comparer) reste à faire
  par le commanditaire, avec ses vraies données et sa politique de
  rétention - je n'ai pas accès à cet environnement depuis ici.

## État du projet : Phase 15 — Application installable, accessibilité, sécurité des dépendances, mobile

- **Application installable (PWA)** : manifeste (`/manifest.webmanifest`,
  généré dynamiquement - le nom affiché sur l'écran d'accueil est celui
  de l'établissement de l'utilisateur connecté) et service worker
  (`/sw.js`) permettant d'installer l'application sur téléphone comme
  une app native. Le service worker ne met en cache **que** les fichiers
  statiques (CSS/JS/icônes) - jamais les pages ou données dynamiques -
  pour qu'aucune note, paiement ou emploi du temps ne risque d'être
  affiché à partir d'une copie obsolète.
- **Accessibilité (a11y)** :
  - Lien d'évitement (« Aller au contenu principal ») pour sauter la
    barre latérale au clavier, avant tout le reste de la navigation.
  - 12 formulaires (répartis sur 11 gabarits) affichaient un `<label>`
    non relié à son champ (`for` manquant) - invisible pour un
    utilisateur voyant à la souris, mais un vrai obstacle au clavier et
    au lecteur d'écran, qui n'annonçait aucun nom de champ. Corrigé
    partout avec le même attribut déjà utilisé correctement ailleurs
    dans l'application.
  - Attributs `alt` ajoutés aux deux images qui n'en avaient pas
    (logo et QR code du bulletin PDF).
- **Comportement mobile** : les tableaux (listes d'élèves, paiements,
  audit, etc.) débordaient silencieusement de leur carte sur petit
  écran. Ils défilent désormais horizontalement à l'intérieur de leur
  propre carte au lieu de casser la mise en page de la page entière -
  un seul correctif CSS a suffi car 27 des 31 gabarits concernés
  partageaient déjà le même conteneur (`.card-body`).
- **Sécurité des dépendances** : `pip-audit` intégré à la CI (le build
  échoue si une dépendance a une faille connue) et Dependabot activé
  (alerte hebdomadaire GitHub). Premier scan réel : Pillow 12.1.1 avait
  35 failles connues, corrigées en mettant à jour vers la version 12.3.0
  - deuxième scan confirmé propre.
- Vérifié réellement, pas seulement relu : absence de défilement
  horizontal de page sur mobile (375 px) avec des données réelles,
  lien d'évitement fonctionnel au clavier, manifeste et service worker
  effectivement chargés par le navigateur, suite complète (307 tests)
  toujours au vert après la mise à jour de Pillow.

### Ce qui reste ouvert après cette phase

- SMS, WhatsApp et Mobile Money automatisés, tests de charge,
  restauration testée uniquement en local, rattrapage : toujours
  ouverts (voir phases précédentes).
- L'icône de l'application installée reste la même pour tous les
  établissements (comme le favicon existant) ; seul le nom affiché est
  personnalisé par établissement. Utiliser le logo propre à chaque école
  comme icône demanderait un redimensionnement fiable d'images
  arbitraires envoyées par les écoles, non fait ici pour rester sûr.
- Audit d'accessibilité fait par relecture ciblée (labels, alt, lien
  d'évitement, contraste des styles de focus déjà en place) - pas par
  un outil automatisé (ex. axe-core) ni par un test avec un vrai lecteur
  d'écran.

## État du projet : Phase 16 — Versionnement, récupération de compte (2FA perdue)

- **Versionnement** : voir la section "Versionner l'application"
  ci-dessus - démarre à `1.0.0` à partir de cette phase, sans toucher
  rétroactivement à l'historique des phases précédentes.
- **Codes de secours pour la 2FA** : jusqu'ici, un compte ayant activé
  la double authentification et perdu son téléphone n'avait *aucun*
  moyen de récupérer son compte lui-même (`desactiver_2fa` exige
  justement un code TOTP valide) - la seule issue était une intervention
  manuelle en base de données. Corrigé :
  - 10 codes de secours à usage unique sont générés et affichés **une
    seule fois** à l'activation de la 2FA (jamais par email, jamais
    reconsultables ensuite - seul leur hachage est conservé, comme un
    mot de passe).
  - L'écran de connexion à deux facteurs accepte maintenant un code de
    secours à la place du code TOTP. L'utiliser désactive
    automatiquement la 2FA du compte (l'ancien secret étant sur
    l'appareil perdu) et le renvoie vers la page d'activation pour une
    reconfiguration complète avec un nouvel appareil.
  - Régénération possible à tout moment (« Codes de secours » dans la
    barre supérieure), en confirmant avec un code TOTP actuel - invalide
    immédiatement les anciens codes.
  - **Filet de secours supplémentaire**, réservé au rôle `developpeur` :
    un bouton dans l'espace développeur permet de réinitialiser
    entièrement la 2FA d'un compte qui aurait perdu à la fois son
    téléphone et ses codes de secours (impossible de le faire sur son
    propre compte, pour éviter un contournement trivial).
  - Le mot de passe oublié fonctionnait déjà correctement (lien à usage
    unique par email, ou par matricule vers le(s) parent(s) pour un
    élève) - vérifié, aucun changement nécessaire de ce côté.
- 17 nouveaux tests (modèle, connexion par code de secours, usage
  unique, régénération, réinitialisation par le développeur, restriction
  de rôle) - tous au vert, suite complète revérifiée derrière.

### Ce qui reste ouvert après cette phase

- SMS, WhatsApp et Mobile Money automatisés, tests de charge,
  restauration testée uniquement en local, rattrapage : toujours
  ouverts (voir phases précédentes).
- Si un compte perd son téléphone ET ses codes de secours ET n'a accès
  à aucun `developpeur` de son établissement (cas d'un développeur
  unique qui se retrouve lui-même dans cette situation), le retour à une
  intervention manuelle en base reste la seule issue - c'est un choix
  assumé : permettre à un rôle de réinitialiser sa propre 2FA sans
  aucune preuve de possession ouvrirait une faille bien plus grave.

## État du projet : Phase 17 — Identité visuelle générique, guide par rôle sur l'accueil

- **Symbole Ω remplacé** : le logo générique de la plateforme (favicon,
  icônes PWA, emblèmes de l'accueil et de l'annuaire) utilisait le
  symbole grec Ω, hérité du cahier des charges de référence (Omega
  Académie) mais sans rapport avec un logiciel volontairement générique.
  Remplacé par l'icône livre ouvert déjà utilisée ailleurs dans
  l'application pour la pédagogie - cohérent et immédiatement lisible.
- **Guide par rôle sur la page d'accueil publique** : une section
  dépliable (`<details>`/`<summary>`, sans JavaScript) présente, pour
  chacun des 9 rôles côté école, une description concrète de ce à quoi
  il donne accès - dérivée de la matrice de permissions par défaut
  réelle plutôt que d'un texte marketing générique, avec une mention
  claire que chaque établissement peut ajuster ce périmètre.

## État du projet : Phase 18 — Alertes proactives, attestations vérifiables, correctif de sécurité

- **Correctif de sécurité (pré-existant, pas introduit cette phase)** :
  `scolarite.models.eleve_visible_pour` - la fonction centrale qui décide
  si un utilisateur peut consulter le dossier, le bulletin ou les
  absences d'un élève - laissait passer n'importe quel rôle qui n'était
  ni l'élève lui-même, ni un parent lié, ni un enseignant affecté : un
  autre élève, un(e) bibliothécaire ou un compte « Personnel » du même
  établissement pouvait donc consulter le dossier de n'importe quel
  élève. Trouvé en écrivant les tests de la fonctionnalité ci-dessous
  (qui réutilise cette même fonction), pas signalé par un audit dédié.
  Corrigé par une liste explicite des rôles habilités (direction,
  secrétariat, comptabilité, pédagogie) plutôt qu'un repli implicite ;
  87 tests `scolarite`/`pedagogie` revérifiés au vert après le correctif.
- **Attestation de scolarité vérifiable par QR code** : même principe que
  le bulletin (`pedagogie.models.VerificationBulletin`), généralisé en un
  modèle `scolarite.models.VerificationDocument` réutilisable pour de
  futurs types de documents. Accessible depuis le dossier de l'élève.
- **Alertes proactives sur le tableau de bord** : calculées par requête
  déterministe (jamais par l'IA, qui ne fait que reformuler des chiffres
  déjà exacts en une phrase de synthèse, mise en cache 1h, avec
  dégradation silencieuse si l'API est indisponible) :
  - élèves dont la moyenne générale pondérée est sous 10/20 ;
  - élèves avec un solde dû alors que l'année scolaire est déjà avancée
    (au moins 40% du temps écoulé).

  Visibilité par liste explicite de rôles, volontairement distincte
  d'une simple vérification de module : un parent ou un élève ont le
  module notes/finances dans leur propre matrice, mais pour leurs
  propres données uniquement (portail parent) - jamais une vue agrégée
  sur d'autres élèves ou familles. Un enseignant ne voit que ses propres
  classes affectées, jamais tout l'établissement.
- 24 nouveaux tests (attestation, vérification publique, alertes par
  rôle - y compris les cas de non-fuite vers parent/élève/enseignant
  hors périmètre -, synthèse IA avec mise en cache et dégradation),
  tous au vert, suite complète revérifiée derrière.

### Ce qui reste ouvert après cette phase

- SMS, WhatsApp et Mobile Money automatisés, tests de charge,
  restauration testée uniquement en local, rattrapage : toujours
  ouverts (voir phases précédentes).
- Le seuil de retard de paiement (40% de l'année écoulée) est une
  approximation assumée : `EcheancierFrais` n'a pas de date d'échéance
  par tranche, donc impossible de calculer un retard exact sans ajouter
  ce champ - non fait ici pour ne pas imposer un calendrier de paiement
  arbitraire aux établissements.
- Les alertes ne couvrent que deux signaux (risque académique, impayés) ;
  d'autres pistes évoquées (absentéisme récurrent, etc.) restent à
  construire sur le même principe si besoin.

## État du projet : Phase 19 — Audit de sécurité ciblé, deux correctifs

À la demande explicite d'une vérification complète du code (pas seulement
des nouvelles fonctionnalités), passage systématique de toutes les vues de
toutes les applications : décorateurs de permission, cloisonnement par
établissement sur chaque vue prenant un identifiant en paramètre (risque
IDOR), upload de fichiers (zip-slip, types autorisés), injection SQL,
exemptions CSRF, secrets/`DEBUG` codés en dur. Deux problèmes réels trouvés
et corrigés ; tout le reste (près de 60 vues relues) était déjà correct.

- **`TransfertEleve.justificatif`** (document justifiant un transfert
  d'élève) n'avait aucun validateur - seul champ fichier de toute
  l'application dans ce cas, alors que la bibliothèque, les pièces
  jointes d'annonces et le logo d'établissement sont tous validés (taille,
  extension, contenu). Risque limité en pratique (champ accessible
  seulement depuis l'admin Django, zone déjà réservée aux comptes
  techniques), corrigé par cohérence et défense en profondeur avec les
  mêmes validateurs que la bibliothèque.
- **Inscription d'un élève avec un email de parent d'un autre
  établissement** : le formulaire cherchait ce compte sans filtrer par
  établissement, et l'erreur n'apparaissait qu'ensuite dans
  `lier_parent_a_eleve` (qui, lui, vérifie bien l'établissement) - après
  que l'élève avait déjà été créé en base, sans transaction englobante.
  Résultat concret : une erreur 500 non gérée et un élève orphelin (sans
  classe ni parent) laissé en base. Corrigé à deux niveaux : le
  formulaire filtre maintenant par établissement (même message d'erreur
  que « email inconnu », pour ne jamais révéler l'existence d'un compte
  dans un autre établissement), et toute l'opération d'inscription est
  désormais atomique.
- **Scan automatisé** (`bandit`, l'outil standard pour Python) passé en
  complément de la relecture manuelle : 16 signalements, tous relus
  individuellement et confirmés sans danger (mots de passe de tests,
  vérification du `SECRET_KEY` par défaut, remise à vide de
  `totp_secret` lors d'une réinitialisation 2FA - mal interprétée par
  l'outil comme un « mot de passe codé en dur », contenu SVG figé sans
  entrée utilisateur, endpoint de supervision qui avale volontairement
  ses erreurs pour rapporter un état plutôt que de planter). Aucun
  changement de code nécessaire de ce côté.
- Suite complète revérifiée au vert après les deux correctifs.

### Ce qui reste ouvert après cette phase

- SMS, WhatsApp et Mobile Money automatisés, tests de charge,
  restauration testée uniquement en local, rattrapage, traduction
  bambara : toujours ouverts (voir phases précédentes).
- Cet audit a porté sur les vues et l'autorisation - pas une relecture
  ligne par ligne de chaque template ni un test d'intrusion formel.
  (Mise à jour : `bandit` a finalement été lancé peu après - voir Phase 20.)

## État du projet : Phase 20 — Erreur 502 corrigée, cycle Lycée ajouté

- **Correctif urgent, découvert en production** : l'activation de la 2FA
  provoquait une erreur 502 (signalée par l'utilisateur avec capture
  d'écran). Cause confirmée par mesure : les 10 codes de secours générés
  à l'activation étaient hachés avec le hacheur de mot de passe par
  défaut de Django (~1,5 million d'itérations PBKDF2, réglé pour un mot
  de passe choisi par un humain) - 15,7 secondes pour les 10 hachages en
  local, largement de quoi dépasser le délai d'attente du serveur sur
  l'instance Render gratuite. Un hacheur dédié à 30 000 itérations
  (toujours PBKDF2 salé, juste proportionné à des codes générés
  aléatoirement côté serveur) ramène ça à 0,44s. Rétrocompatible sans
  migration de données : le format du hachage encode son propre nombre
  d'itérations.
- **`bandit`** (scanner de sécurité Python standard) lancé en complément
  de l'audit de la phase précédente : 16 signalements, tous relus et
  confirmés sans danger.
- **Cycle Lycée** (10ème à 12ème année - Seconde à Terminale, menant au
  baccalauréat malien) ajouté à côté du 1er et du 2ème cycle de
  l'enseignement fondamental, avec un rôle `Directeur du lycée` cloisonné
  au même principe que les deux rôles de direction de cycle existants.
  Migration de données pour les établissements déjà créés (le nouveau
  rôle n'existait pas dans leur matrice de permissions). Au passage,
  deux ensembles de constantes dupliqués et jamais utilisés nulle part
  dans le code (`ROLES_DIRECTION_CYCLE`/`ROLES_DIRECTION_TOTALE` dans
  `comptes/roles.py`, `ROLES_VISION_TOUS_CYCLES` dans
  `scolarite/models.py`) ont été retirés plutôt que laissés devenir plus
  trompeurs encore avec un 3ème cycle qu'ils n'auraient pas reflété.

### Ce qui reste ouvert après cette phase

- SMS, WhatsApp et Mobile Money automatisés, tests de charge,
  restauration testée uniquement en local, rattrapage, traduction
  bambara : toujours ouverts (voir phases précédentes).
## État du projet : Phase 21 — Séries du baccalauréat malien

Suite à la Phase 20 (cycle Lycée) : ajout des 6 séries officielles du
baccalauréat malien, administrées par le CNECE (Centre national des
examens et concours de l'éducation) - confirmées par recherche, pas
devinées : Sciences Exactes (TSE), Sciences Expérimentales (TSExp),
Sciences Économiques (TSEco), Sciences Sociales (TSS), Langues et
Littérature (TLL), Arts et Lettres (TAL).

- Champ `serie` sur `Classe`, optionnel, utilisable uniquement avec le
  cycle Lycée (validé à la fois dans `Classe.clean()` et dans
  `CreerClasseForm` - la 10ème année, tronc commun, n'a pas encore de
  série).
- Affichée partout où la classe d'un élève du lycée a un sens concret :
  liste des classes, dossier élève, bulletin PDF, attestation de
  scolarité.
- 6 nouveaux tests (validation modèle + formulaire + vue), tous au vert.

### Ce qui reste ouvert après cette phase

- SMS, WhatsApp et Mobile Money automatisés, tests de charge,
  restauration testée uniquement en local, rattrapage, traduction
  bambara : toujours ouverts (voir phases précédentes).
- Les séries ne sont pour l'instant qu'une étiquette sur la classe, pas
  un filtre dans les statistiques (répartition par série) ni un critère
  de recherche dédié - à ajouter si le besoin se précise.

## État du projet : Phase 22 — Performance (requêtes N+1)

Suite à une question sur la lenteur ressentie de l'application : mesure
réelle (307 à 348 tests ne suffisent pas à détecter un problème de
performance, qui n'empêche aucun test de passer) avec 100 élèves de
test, plutôt qu'une supposition.

- **`assistant.alertes.construire_alertes`** (tableau de bord) : 703
  requêtes SQL et 2,7s mesurées pour 100 élèves - une boucle Python
  appelait une fonction faisant sa propre requête à chaque élève. Réécrit
  en requêtes groupées par classe (moyenne pondérée) et par lot (soldes
  dus). Résultat mesuré : 7 requêtes, 0,042s - mêmes chiffres produits,
  juste calculés différemment.
- **`finances.views.suivi_paiements`** : 140+ requêtes pour 100 élèves,
  un problème préexistant, pas introduit par la phase précédente -
  `calculer_total_du` et la recherche du téléphone d'un parent
  (`Utilisateur.telephone_effectif`) faisaient chacune une requête par
  élève affiché. `calculer_total_du` accepte maintenant un paramètre
  optionnel pour recevoir les aides déjà chargées (compatible : les
  autres appels, à un seul élève, sont inchangés).
- **`scolarite.views.liste_eleves`, `recherche_globale`,
  `liste_matieres`** : même cause plus discrète - `{{ inscription.classe
  }}` déclenche `Classe.__str__`, qui accède à `annee_scolaire` ; ce
  champ n'était pas dans le `select_related`, donc une requête de plus
  par ligne affichée. `liste_eleves` est probablement la page la plus
  consultée de toute l'application.
- 3 tests de régression ajoutés (assertion sur un plafond de requêtes,
  pas un nombre exact - pour ne pas casser au moindre changement mineur),
  conçus pour échouer si le motif « une requête par élève » revient.

### Ce qui reste ouvert après cette phase

- SMS, WhatsApp et Mobile Money automatisés, tests de charge,
  restauration testée uniquement en local, rattrapage, traduction
  bambara : toujours ouverts (voir phases précédentes).
- `finances/management/commands/relancer_impayes.py` (la commande cron
  de relance automatique) a le même motif de requête par élève, non
  corrigé ici : elle tourne en tâche planifiée, jamais pendant qu'un
  utilisateur attend une page, donc hors du périmètre de cette phase
  (lenteur ressentie) - à revoir si le temps d'exécution de la tâche
  elle-même devient un problème concret.
- Cette phase a corrigé les cas trouvés par mesure réelle sur les pages
  les plus probables, pas un audit exhaustif de chaque vue de
  l'application - d'autres motifs similaires pourraient encore exister
  ailleurs.

## État du projet : Phase 23 — Menu mobile : possibilité de le refermer

Signalé par un utilisateur : une fois le menu latéral ouvert sur mobile
(bouton ☰), il n'y avait aucun moyen de le refermer. Confirmé par test
réel (Playwright, viewport 375×667) : la sidebar ouverte (`position:
fixed`, pleine hauteur, `z-index: 40`) recouvre visuellement le bouton
☰ qui l'a ouverte - `elementFromPoint` sur la position du bouton
retournait un élément interne de la sidebar, pas le bouton, et un clic
Playwright sur le bouton expirait sans effet.

- Le bouton ☰ passe à `z-index: 41` (au-dessus de la sidebar) en vue
  mobile : il reste donc cliquable même sidebar ouverte, et un second
  clic referme désormais le menu.
- Ajout d'un rideau (`#sidebar-rideau`, fond semi-transparent, `z-index:
  39`, sous la sidebar mais au-dessus du contenu) qui couvre le reste de
  l'écran quand le menu est ouvert ; un tap n'importe où sur ce rideau
  referme aussi le menu - comportement attendu de tout menu mobile à
  tiroir.
- Les deux mécanismes de fermeture (second tap sur ☰, tap en dehors)
  ont été vérifiés par un scénario Playwright complet avant commit.

### Ce qui reste ouvert après cette phase

- SMS, WhatsApp et Mobile Money automatisés, tests de charge,
  restauration testée uniquement en local, rattrapage, traduction
  bambara : toujours ouverts (voir phases précédentes).

## État du projet : Phase 24 — Erreur 502 à l'inscription (envoi SMTP sans timeout)

Signalé par un utilisateur : page 502 lors d'une création de compte.
Cause identifiée (même famille que le 502 de la Phase 20) : en
production, l'email de vérification part de manière synchrone pendant
la requête (`EMAIL_ASYNC=False` - le plan Render gratuit n'a pas de
tâche planifiée pour traiter une file d'attente). Sans timeout, un
serveur SMTP lent ou injoignable bloquait indéfiniment le worker
gunicorn jusqu'à ce qu'il soit tué par son propre délai - 502 pour
l'utilisateur, alors que son compte était déjà créé en base (le
`save()` a lieu avant l'envoi de l'email).

- `EMAIL_TIMEOUT=10` borne chaque tentative SMTP à 10 secondes.
- `comptes.mail.envoyer_email` capture maintenant un échec SMTP (envoyé
  à Sentry) au lieu de le laisser remonter jusqu'à la requête : un email
  manquant peut toujours être redemandé via « renvoyer le code »,
  contrairement à un compte bloqué sur une page d'erreur.

## État du projet : Phase 25 — Un enseignant ne peut plus créer de classe ni s'auto-affecter

Signalé par un utilisateur : un compte enseignant pouvait créer une
classe et s'affecter lui-même à n'importe quelle classe de l'école.
Cause : le module Classes (création de classe, affectation d'un
enseignant, passage de classe - des actions d'administration de toute
l'école) était accordé par défaut au rôle Enseignant dans la matrice de
permissions, alors que son seul besoin légitime (voir ses propres
classes via « Mes classes ») est déjà couvert séparément par les
modules Notes/bulletins et Absences.

- Module Classes retiré du rôle Enseignant dans la matrice par défaut,
  avec une migration de données pour les établissements déjà créés
  (`seed_pour()` ne couvre que les nouveaux).
- Deux tests de régression : un enseignant reçoit un 403 s'il tente de
  créer une classe ou de s'affecter lui-même.
- Reste personnalisable sans redéploiement depuis l'espace développeur
  si un établissement veut l'autoriser pour certains enseignants.

## État du projet : Phase 26 — Gestion des années scolaires depuis l'espace développeur

Suite à la Phase 25 : jusqu'ici, créer une année scolaire n'était
possible que depuis l'interface d'administration Django (`/admin/`,
réservée à un compte superutilisateur technique), jamais depuis
l'application elle-même. Nouvelle page `espace_developpeur:annees_scolaires`
(réservée au rôle développeur, comme le reste de cet espace) :

- Création (libellé, dates, cocher « active » à la volée) - le modèle
  garantit déjà une seule année active par établissement et valide
  date_fin > date_debut, repris ici pour un message d'erreur clair
  plutôt qu'une `IntegrityError`.
- Activation d'une année existante, et archivage (bloque les nouvelles
  inscriptions, irréversible depuis cette page - confirmation demandée
  avant l'action).
- Isolation testée comme le reste de l'espace développeur : un
  développeur ne voit, n'active ni n'archive que les années de son
  propre établissement (404 sinon).
- Vérifié visuellement (Playwright) : création, badges de statut,
  dialogue de confirmation avant archivage.

## État du projet : Phase 27 — Suppression d'une classe vide

Suite à une question sur la suppression d'une classe : aucun moyen de le
faire depuis l'application (seulement `/admin/`). Bouton « Supprimer »
ajouté sur la liste des classes, visible uniquement quand l'effectif
affiché est à 0, mais la vérification faite par la vue est plus stricte
que ce simple affichage : elle refuse la suppression dès qu'une
inscription existe pour cette classe, même ancienne (admis, redoublant,
transféré) - `effectif` ne compte que les inscriptions EN_COURS, un
historique peut donc exister même à 0. Cohérent avec `Inscription.classe`
qui est en PROTECT au niveau base de données pour la même raison : ne
jamais perdre un historique scolaire par erreur de manipulation.

Même périmètre d'accès que les autres actions de gestion des classes
(module Classes, donc secrétariat/direction - pas les enseignants depuis
la Phase 25). Vérifié visuellement (Playwright) : bouton absent sur une
classe non vide, dialogue de confirmation, suppression effective.

## État du projet : Phase 28 — Emploi du temps : lecture seule pour l'enseignant, suppression d'une matière

Suite à une question sur qui gère l'emploi du temps : confirmation que
seule la direction doit le créer, un enseignant devant seulement
consulter ses propres créneaux (cahier des charges). Corrige au passage
le même défaut que les Phases 25/27 : `classes_visibles_pour` ne
restreint un enseignant ou un élève que par établissement, pas par
affectation/inscription - `gerer_emploi_du_temps` laissait donc
n'importe quel enseignant ajouter des créneaux sur le planning de
n'importe quelle classe de l'école (même la sienne, ce qui contredisait
déjà le cahier des charges), et un élève le consulter via l'URL directe.

- Formulaire d'ajout de créneau retiré pour l'enseignant, quelle que
  soit la classe - seule la direction (cloisonnée par cycle) et les
  rôles à accès total le voient désormais.
- Un enseignant qui consulte une classe où il est affecté ne voit que
  SES propres créneaux (pas tout le planning - les autres matières ne
  le concernent pas) ; sans aucune affectation dans la classe, accès
  refusé (403).
- Un élève reste limité à sa propre classe (Phase 26... correction
  précédente de cette même session).
- 8 tests de régression ; vérifié visuellement (Playwright) : la
  direction voit formulaire + planning complet, l'enseignant voit un
  planning en lecture seule limité à ses créneaux.

Ajout, au même endroit que la Phase 27, de la suppression d'une
matière : une matière n'étant qu'un regroupement d'affectations
enseignant/classe (pas de table dédiée), « supprimer une matière »
revient à retirer la ligne (enseignant, classe) correspondante depuis
*Matières*. Refusé si des notes sont déjà rattachées à cette affectation
(`Note.affectation` en PROTECT) ; les créneaux d'emploi du temps associés
sont supprimés avec (CASCADE, pure logistique). Même périmètre d'accès
que les autres actions de gestion des classes (module Classes). 5 tests,
vérifié visuellement.

## État du projet : Phase 29 — Devoirs, interrogations, bonus ; assistant et emploi du temps ; suppression d'un créneau

Trois ajouts liés à la même conversation :

- **Notation par devoirs/interrogations/bonus.** Jusqu'ici, une seule
  note/20 par matière et par trimestre, saisie directement. Remplacée
  par des évaluations individuelles (plusieurs devoirs/interrogations/
  bonus possibles par trimestre) : la note finale du trimestre se
  recalcule automatiquement, moyennée par type puis pondérée selon les
  poids propres à chaque affectation (`Affectation.poids_devoirs` /
  `poids_interrogations` / `poids_bonus`, 40/40/20 par défaut,
  modifiables à l'affectation). Un type sans évaluation est exclu du
  calcul (poids des autres re-proportionnés) plutôt que de faire chuter
  la note tant qu'il reste vide. `Note` elle-même est inchangée :
  bulletin, classement, alertes et Assistant IA continuent de
  fonctionner sans modification, puisqu'ils ne lisent que `Note`,
  jamais les évaluations individuelles. Vérifié visuellement : devoir
  14 + devoir 16 + interro 12 + bonus 18 (poids 40/40/20) → 14,40/20,
  correctement affiché sur le bulletin.
- **Assistant IA et emploi du temps.** Un enseignant avec plusieurs
  classes peut désormais demander à l'Assistant « quel jour suis-je en
  telle classe ? » au lieu d'ouvrir chaque classe une par une : son
  emploi du temps complet (toutes classes) est ajouté au contexte
  envoyé à l'IA pour une question générale - jamais celui d'un collègue,
  jamais pour un autre rôle.
- **Suppression d'un créneau.** La direction peut désormais retirer un
  créneau d'emploi du temps, pas seulement en ajouter.

19 tests de régression pour le calcul des notes, vérifié visuellement
pour les trois ajouts.

## État du projet : Phase 30 — Parent sans compte préalable, notation alignée sur la pratique malienne

Suite à une question sur l'inscription d'un élève : jusqu'ici, un parent
devait déjà posséder un compte (recherché par email) avant que son
enfant puisse être inscrit - un détour en deux étapes à chaque fois.

- **Lien automatique.** L'email du parent suffit même sans compte
  existant ; nom, prénom et téléphone (optionnels) sont enregistrés en
  attente (`ParentEnAttente`). Dès que ce parent crée son compte et
  vérifie son email avec la même adresse, le lien avec son enfant se
  fait automatiquement (`comptes.views.verifier_email` ->
  `scolarite.models.lier_parents_en_attente`), sans action manuelle.
  Le dossier élève distingue les parents liés des parents « en
  attente ». Toujours cloisonné par établissement : un email d'une
  autre école n'est jamais lié. 19 tests, vérifié de bout en bout
  (navigateur) : inscription avec email inconnu → dossier incomplet →
  inscription et vérification du parent → dossier complet, téléphone
  repris automatiquement.
- **Poids de notation alignés sur la réalité malienne.** Recherche
  effectuée sur le système éducatif malien (aucune formule nationale
  publiée trouvée, mais deux signaux concordants : les décisions de
  passage en classe supérieure reposent officiellement sur la
  composition trimestrielle, et un logiciel scolaire malien réel
  (Scolynx) pondère par matière plutôt que par type d'évaluation).
  Ajout d'un type d'évaluation « Composition » et nouveaux poids par
  défaut (composition 50 %, devoirs 25 %, interrogations 15 %, bonus
  10 %, contre 40/40/20 sans composition à la phase précédente) -
  toujours ajustables par affectation. Migration de données incluse
  pour les affectations déjà créées.

## État du projet : Phase 31 — Bulletin conforme au modèle malien réel, recherche par nom pour les paiements, cycles simplifiés

Suite à l'envoi de deux bulletins maliens authentiques (lycée et 2ème
cycle) et à un retour sur l'utilisabilité des formulaires de paiement :

- **Notation remplacée par le système malien exact.** Les poids
  composition/devoirs/interrogations/bonus de la Phase 30 (déjà un
  compromis, faute de formule nationale publiée) sont abandonnés : les
  deux bulletins réels montrent noir sur blanc deux notes distinctes
  par matière - la **Note de Classe** (contrôle continu, sur 20) et la
  **Note de Composition** (examen trimestriel, sur 40, qui compte donc
  double) - avec la moyenne de la matière calculée par
  `(classe + composition) ÷ 3`. Formule vérifiée chiffre pour chiffre
  sur plus de quatre matières du bulletin du Lycée Fatoumata Haidara
  (ex. Mathématiques : (16,50 + 38,00) ÷ 3 = 18,17 - exact), ainsi que
  les cinq paliers d'appréciation (Excellent ≥17, Très Bien ≥16, Bien
  ≥13, Passable ≥10, Insuffisant en dessous). Faute de pouvoir
  revérifier avec la même certitude chaque chiffre du bulletin de 2ème
  cycle, la même règle s'applique uniformément à tous les cycles (1er
  cycle, 2ème cycle, Lycée) plutôt que de risquer une formule
  différente mal vérifiée. Resaisir une des deux notes ne touche plus
  l'autre (ex. ajouter la composition une fois l'examen passé sans
  perdre la note de classe saisie en cours de trimestre). L'ancien
  système à quatre types d'évaluation (`Evaluation`, `TypeEvaluation`,
  poids par affectation) est supprimé entièrement, y compris sa
  migration de données devenue obsolète.
- **Bulletins (page et PDF) refaits à l'identique de la structure
  réelle** : un bloc par trimestre avec le tableau Matière / Note de
  classe / Note de composition / Coefficient / Moyenne / Moyenne
  coefficiée / Appréciation, une ligne de total (coefficients et
  moyenne coefficiée), puis la Moyenne obtenue, l'Appréciation du
  trimestre et les Moyennes la plus forte/la plus faible de la classe
  à titre de repère - en plus de la moyenne générale et du rang déjà
  affichés. Vérifié par export PDF réel (élève avec cinq matières,
  coefficients différents) : tous les calculs, l'alignement et les
  accents correspondent au document papier.
- **Recherche par nom pour les paiements.** Enregistrer un paiement de
  scolarité imposait de connaître le matricule exact de l'élève ;
  saisir un salaire imposait l'email exact de l'employé - aucun des
  deux n'est mémorisable. Les deux formulaires ont maintenant un champ
  de recherche (nom, prénom, matricule pour un élève ; nom, prénom,
  email pour un employé) avec suggestions cliquables, au lieu d'une
  saisie à l'aveugle.
- **Cycles renommés.** « 1er cycle (1ère à 6ème année) » devient
  simplement « 1er cycle » (et de même pour le 2ème cycle) - le détail
  des années n'apporte rien à la liste des classes et alourdissait
  l'affichage.
- **« Dossier incomplet » : comportement normal, pas un bug.** Ce
  badge s'affiche tant qu'il manque la date de naissance, le
  téléphone, ou qu'aucun parent n'est **effectivement lié** au compte
  de l'élève - un parent seulement renseigné par email en attente
  (Phase 30) ne suffit pas tant qu'il n'a pas lui-même créé son
  compte et vérifié son adresse.

Suite complète (397 tests) verte après ces changements, y compris les
tests réécrits pour la nouvelle signature de `saisir_note` et la
suppression du système `Evaluation`.

## État du projet : Phase 32 — Périodicité des frais de scolarité (mensuel/trimestriel/annuel)

Suite à la Phase 31 : les classes utilisaient encore des tranches fixes
(Inscription / Tranche 1 / Tranche 2) alors que les paiements se font
en pratique par mois, par trimestre ou en une fois selon le choix de
l'établissement.

- **`EcheancierFrais` remplace les deux tranches par une périodicité.**
  Les frais d'inscription restent inchangés (demandé explicitement) ;
  `montant_tranche_1`/`montant_tranche_2` sont remplacés par
  `periodicite` (Mensuel / Trimestriel / Annuel) et `montant_periode`
  (le montant par mois, par trimestre ou pour l'année selon le choix).
  Le nombre de versements est fixé automatiquement par la périodicité
  (3 pour trimestriel, 1 pour annuel) sauf pour le mensuel, où l'école
  choisit 9 ou 10 versements sur l'année scolaire (confirmé). Le
  calcul du total dû (`calculer_total_du`, utilisé par le suivi des
  paiements, les alertes impayés et le dossier élève) n'a pas changé -
  il ne dépend que de `EcheancierFrais.total_annuel`.
- **Migration de données sans impact sur les soldes déjà calculés.**
  Les échéanciers déjà créés (deux tranches) sont fusionnés en un
  versement annuel unique dont le montant est la somme des deux
  anciennes tranches - le total dû par élève, et donc chaque solde déjà
  affiché, reste rigoureusement identique après la migration.
  Vérifié : les six classes de démonstration existantes ont conservé
  leur `total_annuel` exact après migration.
- **`TypeTranche` simplifié à deux choix** (Inscription / Versement de
  scolarité) sur le reçu de paiement - les anciens libellés « Tranche
  1 »/« Tranche 2 » n'avaient plus de sens une fois la périodicité
  détachée d'un nombre de tranches fixe.

Suite complète (397 tests) verte après ces changements. Vérifié de
bout en bout (navigateur) : création d'une classe en périodicité
mensuelle (20 000 d'inscription + 9 × 5 000) donnant bien un total
annuel de 65 000, et formulaire d'enregistrement d'un paiement avec
le nouveau choix Inscription/Versement.

## État du projet : Phase 33 — Formule d'abonnement par cycle, Censeur et Surveillant général

Suite à une question sur la facturation : certaines écoles n'ont que le 1er
cycle, d'autres vont jusqu'au 2ème cycle, d'autres jusqu'au Lycée - de quoi
vendre des formules d'abonnement différentes, à condition qu'une école ne
puisse pas se déclarer « 1er cycle seul » tout en utilisant quand même les
fonctions du Lycée.

- **`Etablissement.plan`** (1er cycle / 1er et 2ème cycle / tous les
  cycles) restreint désormais les cycles de classe créables
  (`scolarite.models.cycles_autorises_pour`, appliqué à la fois dans le
  formulaire - le cycle non couvert n'apparaît même pas dans la liste - et
  dans `Classe.clean()`, pour qu'un contournement du formulaire soit aussi
  refusé) ainsi que les rôles de direction propres à un cycle
  (`role_autorise_pour_plan`, appliqué dans le formulaire d'attribution de
  rôle de l'espace développeur).
- **Modifiable uniquement depuis l'espace plateforme** (le propriétaire de
  la plateforme, compte superutilisateur Django - jamais l'établissement
  lui-même) : volontairement absent du formulaire d'identité de
  l'établissement que le développeur de l'école édite
  (`ParametresEtablissementForm`), pour qu'une école ne puisse jamais
  s'auto-attribuer un cycle non souscrit. Un établissement déjà créé
  démarre sur « tous les cycles » (aucune restriction rétroactive) ;
  seule une formule changée explicitement par la plateforme restreint
  ensuite les cycles.
- **Censeur et Surveillant général** ajoutés comme rôles propres au Lycée,
  après recherche sur l'organisation réelle d'un lycée malien (décret
  n°2011-234/P-RM du 12 mai 2011 : *« Le Proviseur est assisté d'un
  Censeur, d'un Surveillant Général et d'un Econome »* - Proviseur et
  Econome correspondaient déjà à Directeur du Lycée et Comptable). Le
  Censeur (adjoint du proviseur, pédagogie et discipline) a un périmètre
  proche du Directeur du Lycée mais sans la création de classes ni
  l'édition de l'emploi du temps - réservées à la direction. Le
  Surveillant général (discipline et assiduité au quotidien) a un
  périmètre volontairement étroit : élèves, absences, communication.
  Les deux sont cloisonnés au Lycée comme un directeur de cycle (même
  mécanisme de visibilité des classes/élèves), et donc eux aussi soumis
  à la restriction par plan ci-dessus.

Suite complète (420 tests) verte après ces changements. Vérifié de bout en
bout (navigateur) : une école au plan « 1er cycle » ne voit que ce cycle
dans le formulaire de création de classe et ne peut pas attribuer les
rôles Censeur/Directeur du 2ème cycle/Directeur du Lycée, et le
changement de formule depuis l'espace plateforme se répercute
immédiatement.

## État du projet : Phase 34 — Correctif de sécurité : un parent voyait les paiements de toute l'école

Suite à un audit demandé sur les fuites de données possibles dans
l'application : un parent, qui a légitimement accès au module Finances
pour suivre le solde de ses propres enfants, pouvait en réalité accéder
aux paiements de **n'importe quel élève** de l'établissement.

- **Cause.** `suivi_paiements` (la page normalement utilisée par un
  parent) filtre bien par `eleve__parents_lies=request.user`, mais cinq
  autres vues de `finances/views.py` - `liste_paiements`,
  `exporter_recu_paiement_pdf`, `corriger_paiement_vue`,
  `enregistrer_paiement_vue`, `rechercher_eleve_json` - ne vérifiaient
  que l'accès au *module* Finances (partagé avec la comptabilité), pas
  le lien parent-élève. Un parent authentifié pouvait donc voir, dans la
  liste brute des paiements, les montants et références de toutes les
  familles, télécharger le reçu de n'importe quel paiement, et même en
  **créer un faux** ou en **corriger un existant** pour un élève qui
  n'est pas le sien.
- **Correctif.** `liste_paiements` et `exporter_recu_paiement_pdf`
  restent accessibles à un parent mais strictement cloisonnés à ses
  propres enfants (même logique que `suivi_paiements`, et
  `eleve_visible_pour` déjà utilisée ailleurs dans l'application) ;
  `enregistrer_paiement_vue`, `corriger_paiement_vue` et
  `rechercher_eleve_json` sont désormais réservées à la comptabilité/
  direction - un parent n'a jamais de raison d'agir sur un paiement,
  même le sien. Les boutons correspondants disparaissent aussi de
  l'interface pour un parent, pas seulement les routes.
- **Repéré par relecture systématique**, pas par un incident réel :
  toutes les autres zones de l'application vérifiées (pédagogie,
  messagerie, assistant IA, bibliothèque) appliquent déjà correctement
  `eleve_visible_pour`/`classes_visibles_pour`. Un accès en écriture un
  peu trop large dans la bibliothèque (un élève peut y déposer des
  documents, pas seulement le bibliothécaire) a aussi été relevé mais
  laissé en l'état, jugé mineur.

Suite complète (428 tests) verte après ce correctif, avec 8 nouveaux
tests reproduisant précisément la fuite (deux familles de la même école,
chacune ne voyant/pouvant agir que sur son propre enfant) pour qu'elle
ne puisse pas réapparaître sans faire échouer la suite. Vérifié de bout
en bout (navigateur) : un parent connecté voit désormais uniquement le
paiement de son enfant dans la liste, sans les boutons Enregistrer/
Corriger, et un accès direct à l'URL d'enregistrement d'un paiement
renvoie bien une erreur 403.

## État du projet : Phase 35 — Suite de l'audit de sécurité : quatre fuites supplémentaires corrigées

En poursuivant l'audit de la Phase 34 sur le reste de l'application, même
schéma de bug retrouvé à quatre autres endroits : un module de permission
accordé à un rôle pour un usage de LECTURE restreinte (son propre dossier,
consulter un catalogue...) sans que la vue distingue ce rôle d'un rôle
d'ADMINISTRATION ayant le même module pour un usage plus large.

- **Bibliothèque.** Un enseignant ou un élève (accès au module pour
  consulter le catalogue) pouvait déposer des documents au nom de
  l'établissement via `ajouter_document`/`importer_zip`, aucune vérification
  de rôle au-delà du module. Désormais réservé au bibliothécaire et à la
  direction ; les formulaires de dépôt disparaissent aussi de la page pour
  les autres.
- **Liste des élèves.** `liste_eleves` ne filtrait pas par parent,
  contrairement à sa vue sœur `recherche_globale` (qui l'a toujours fait) :
  un parent voyait tous les élèves de l'école, pas seulement les siens. Le
  bouton « Inscrire un élève » était même affiché dans son propre menu et
  directement sur la page - un parent ou un élève pouvait donc créer de
  nouveaux comptes élèves. Les deux sont corrigés : liste cloisonnée au(x)
  enfant(s) du parent, inscription réservée au personnel.
- **Annonces.** Le cas le plus sérieux : `publier_annonce` ne restreignait
  que l'enseignant (à sa classe) ; un parent ou un élève, qui n'a le module
  Communication que pour RECEVOIR les annonces et échanger avec un
  enseignant, pouvait en réalité publier une annonce à « Toute l'école »,
  déclenchant un email à tout le monde - avec un bouton « Publier une
  annonce » directement visible sur la page qu'il consulte normalement.
  Publication désormais réservée au personnel.
- **Robustesse de `PermissionMatrix.a_acces`.** Trouvé en écrivant les
  tests du correctif bibliothèque, sans rapport avec une fuite : sur une
  base reconstruite depuis zéro (migrations de données successives),
  `role="directeur_lycee"` pouvait avoir deux lignes de permission
  « historiques » (`etablissement=None`) pour le même module - SQL ne
  considère pas deux NULL comme égaux, `unique_together` ne peut donc pas
  l'empêcher. La vérification utilisait `.get()`, qui plantait
  (`MultipleObjectsReturned`) au lieu de simplement répondre ; remplacé par
  un `.filter().first()` qui tolère les doublons.

Suite complète (441 tests) verte après ces quatre correctifs, avec un
nouveau test par scénario reproduisant exactement la fuite trouvée (accès
direct ET visibilité du bouton dans la page, pas seulement la route).
Vérifié de bout en bout (navigateur) : un parent et un élève ne voient
plus aucun des boutons concernés, et un accès direct aux URLs renvoie
bien une erreur 403.

## État du projet : Phase 36 — Mois exacts couverts par un versement de scolarité

Suite à une question sur le suivi des paiements : pour le salaire d'un
employé, la période réglée est explicite (champ Période, AAAA-MM) ; pour
un versement de scolarité, rien n'indiquait quel(s) mois il couvrait -
gênant pour une école en périodicité mensuelle, où chaque famille paie
à son propre rythme (certaines un mois à la fois, d'autres plusieurs
mois d'un coup, pas forcément consécutifs).

- **`EcheancierFrais.libelles_periodes()`** calcule les libellés exacts
  couverts par l'abonnement d'une classe : les mois civils depuis le
  début de l'année scolaire pour le mensuel (ex. « Octobre 2026 », «
  Novembre 2026 »... jusqu'au nombre de versements prévu), les trois
  trimestres pour le trimestriel, rien pour l'annuel (un seul versement,
  aucun détail utile).
- **À l'enregistrement d'un paiement**, une fois l'élève choisi (même
  recherche en direct qu'avant), des cases à cocher apparaissent avec
  les mois valides de sa classe - la comptabilité coche exactement ceux
  réglés par ce versement, dans n'importe quelle combinaison (ex.
  Janvier et Mars, sans Février). Les mois choisis sont validés côté
  serveur contre l'échéancier réel de la classe (`Paiement.clean()`),
  pas seulement côté formulaire.
- **Affiché** dans la liste des paiements et sur le reçu PDF, à côté de
  la tranche réglée.

Suite complète (450 tests) verte après ce changement. Vérifié de bout en
bout (navigateur) : les 9 mois d'une classe en mensuel apparaissent dans
l'ordre après sélection de l'élève, un paiement couvrant janvier et mars
(non consécutifs) s'enregistre et s'affiche correctement dans la liste
et sur le reçu.

## État du projet : Phase 37 — Correctif de sécurité critique : un élève pouvait se donner ses propres notes

En poursuivant l'audit de sécurité par rôle : un élève - ou un parent -
pouvait saisir une note ou une absence pour n'importe quel élève de
l'école, y compris lui-même. Le plus sérieux des correctifs trouvés
jusqu'ici.

- **Cause.** `saisir_note_vue`, `saisir_absence_vue` et la fonction
  `pedagogie.models.saisir_note` ne restreignaient que le rôle
  Enseignant (« doit être affecté à cette classe/matière ») - un parent
  ou un élève, qui ont accès aux modules Notes/Bulletins et Absences
  uniquement pour CONSULTER (leur bulletin, celui de leur enfant),
  passaient ce test sans aucune restriction puisqu'ils ne sont pas
  Enseignant. Un élève connecté pouvait ainsi se rendre directement sur
  l'URL de saisie d'une note, pour n'importe quelle matière de
  n'importe quelle classe, et s'attribuer 20/20 - ou modifier/falsifier
  les absences de n'importe qui.
- **Correctif, à double verrou.** Les deux vues refusent désormais
  explicitement un parent ou un élève (403), et `saisir_note()` fait de
  même indépendamment de la vue qui l'appelle - en cas d'un futur appel
  direct à cette fonction ailleurs dans le code, la règle s'applique
  quand même. Par précaution, le même verrou a été ajouté au modèle
  `Annonce` (déjà corrigé en vue à la Phase 35), qui ne restreignait
  que l'enseignant de la même façon.
- **Balayage complet.** Chaque vue de l'application gardée par les
  modules Notes/Bulletins, Absences, Élèves, Communication, Emploi du
  temps, Bibliothèque et Finances (tous ceux qu'un parent ou un élève
  peut avoir) a été relue une à une : plus aucune ne permet d'agir
  au-delà de la consultation de ses propres données.

Suite complète (457 tests) verte après ce correctif, avec de nouveaux
tests reproduisant exactement la faille (un élève tente de se noter
lui-même, un parent tente de saisir une note/absence pour son enfant -
refusés dans les deux cas). Vérifié de bout en bout (navigateur) :
tentative de l'attaque réelle depuis un compte élève - 403 à chaque
fois - pendant que l'enseignant affecté garde un accès normal.

## État du projet : Phase 38 — Saisie des absences disponible hors-ligne, avec synchronisation automatique

Après une étude des plateformes concurrentes au Mali (Scolynx, Novacole,
EduSahel...), l'écart le plus utile à combler après le paiement en ligne :
un enseignant peut désormais prendre les présences même quand le réseau
tombe en plein cours, saisie qui part automatiquement dès que la
connexion revient.

- **Pourquoi les absences d'abord.** C'est le cas réel le plus fréquent
  (salle de classe, signal faible), et `saisir_absence_vue` était déjà
  idempotente (`update_or_create` sur élève+date) - rejouer deux fois la
  même saisie ne crée jamais de doublon, condition nécessaire pour une
  file d'attente hors-ligne sans risque.
- **Comment ça marche.** La page de saisie est mise en cache par le
  service worker dès la première visite en ligne de la journée. Chaque
  soumission part en AJAX ; si le réseau manque, la saisie est stockée
  localement (IndexedDB) au lieu d'échouer, avec un bandeau visible
  (« N saisie(s) en attente ») et un bouton « Synchroniser maintenant ».
  La resynchronisation se déclenche seule dès que la connexion revient
  (évènement `online`), et aussi en tâche de fond via Background Sync sur
  Chrome/Android même application fermée - les deux se complètent sans
  risque de doublon grâce à l'idempotence déjà en place.
- **Cas particuliers traités explicitement.** Session expirée pendant la
  coupure : bandeau distinct demandant de se reconnecter, saisie
  conservée (pas de retentative infinie silencieuse). Vraie erreur
  serveur (validation, etc.) : signalée immédiatement, retirée de la
  file plutôt que retentée indéfiniment.
- **Deux bugs trouvés en vérifiant réellement le scénario (navigateur
  hors-ligne, pas en théorie).** L'écriture de la page dans le cache
  n'était pas protégée par `waitUntil()` - le service worker pouvait
  être arrêté avant la fin de l'écriture, rendant la page indisponible
  hors-ligne malgré un code en apparence correct. Et le bouton
  « Enregistrer » restait grisé indéfiniment après une saisie
  hors-ligne, le gestionnaire générique de désactivation du bouton
  supposant un rechargement de page qui n'arrive jamais dans ce flux.

Suite complète verte après ces ajouts (2 nouveaux tests ciblés sur la
réponse JSON de la vue). Vérifié de bout en bout (navigateur, scénario
hors-ligne réel) : page rechargée sans réseau → toujours utilisable
depuis le cache ; saisie hors-ligne → mise en file, bandeau et bouton de
synchronisation visibles, bouton « Enregistrer » réutilisable
immédiatement ; retour en ligne → synchronisation automatique, file
vidée, bandeau masqué, nouvelle absence visible dans le tableau sans
rechargement.

## État du projet : Phase 39 — Abandon et transfert d'élève en cours d'année

Le statut d'une inscription (`Inscription.statut`) ne changeait
auparavant QUE via l'outil annuel « Passage de classe » - un écran qui
traite toute une classe à la fois en fin d'année (admis / redouble /
transféré). Aucune action n'existait pour sortir un seul élève en cours
d'année, et le modèle `TransfertEleve` (destination, date, motif,
justificatif), déjà présent dans le schéma, n'était en réalité créé par
aucun code de l'application - une vérification exhaustive (recherche de
`TransfertEleve(` et `TransfertEleve.objects.create` sur tout le projet)
n'a trouvé aucun point d'appel.

- **Nouveau statut `Abandon`** ajouté à `Inscription.Statut`, qui
  n'avait jusqu'ici que admis/redouble/transféré/en cours - un élève qui
  cesse de venir sans transfert formel n'avait auparavant aucun moyen
  d'être distingué d'un élève toujours scolarisé.
- **Nouvelle action « Clôturer l'inscription »**, accessible à tout
  moment depuis le dossier de l'élève (pas seulement en fin d'année),
  réservée au personnel (un parent ou un élève ne peut que consulter,
  comme pour l'inscription initiale). Un seul formulaire pour les deux
  cas : abandon (date + motif) ou transfert (date + motif + école de
  destination en texte libre, pas de liste des autres écoles de la
  plateforme pour ne jamais exposer leurs noms à un établissement tiers
  + justificatif optionnel).
- **`TransfertEleve` et le nouveau modèle `Abandon` sont désormais
  réellement créés** par `scolarite.models.cloturer_inscription()`, de
  façon atomique avec le changement de statut. L'historique du dossier
  élève affiche maintenant le motif et la destination pour chaque sortie
  passée.
- **Impossible de clôturer deux fois** : la vue ne trouve l'inscription
  « en cours » que si elle l'est encore (404 sinon) - la fonction métier
  refuse aussi explicitement toute inscription déjà close.
- Les écrans de finances filtraient déjà sur le statut « en cours » :
  dès la clôture, l'élève sort automatiquement des listes de
  recouvrement actif, sans changement nécessaire de ce côté.

6 nouveaux tests (abandon, transfert avec destination, transfert sans
destination refusé, parent bloqué, double clôture impossible, disparition
du dossier actif) - suite complète du module scolarite (114 tests) puis
suite complète de l'application vertes. Vérifié de bout en bout
(navigateur, compte direction réel) : clôture d'un élève en abandon et
d'un autre en transfert, motif et destination visibles dans l'historique,
bouton de clôture qui disparaît une fois l'inscription close, tentative
d'accès direct à l'URL par un compte parent - 403.

### Ce qui reste ouvert après ces phases

- SMS et WhatsApp : automatisation volontairement non construite, geré
  manuellement par choix. Mobile Money automatisé, tests de charge,
  restauration testée uniquement en local, rattrapage, traduction
  bambara : toujours ouverts (voir phases précédentes).

## État du projet : Phase 40 — RH/Paie : contrats, congés, bulletin de paie détaillé

Avant cette phase, `Salaire` n'enregistrait qu'un montant par période,
sans brut/net, sans contrat, sans poste ni ancienneté - aucune donnée RH
sur le personnel. Avant de construire quoi que ce soit, vérification de
la réglementation malienne (INPS, AMO/CANAM) par recherche web : les
taux de cotisation trouvés étaient cohérents sur plusieurs sources
indépendantes, mais le barème complet de l'ITS (impôt sur salaires) ne
l'était pas - décision délibérée de ne jamais coder en dur un calcul
d'impôt dont le barème n'est pas vérifié à 100%, plutôt que de risquer
une erreur sur un document qui engage réellement l'établissement.

- **Dossier employé (`Contrat`).** Poste, type (CDI/CDD), dates, salaire
  de base. Un seul contrat actif à la fois par employé (verrouillé en
  base) - un renouvellement clôture l'ancien plutôt que de le remplacer,
  pour garder l'historique complet.
- **Suivi des congés (`DemandeConge`).** Enregistrés par la
  comptabilité/direction (même logique que `Salaire` : pas de portail
  self-service employé, cohérent avec l'existant). Solde de congés payés
  calculé automatiquement : 2,5 jours ouvrables par mois complet
  travaillé sous le contrat actif (Code du travail malien), moins les
  congés payés déjà approuvés - affiché en direct dès qu'un employé est
  sélectionné.
- **Bulletin de paie détaillé.** Brut saisi, INPS et AMO calculés
  automatiquement selon des **taux configurables dans les paramètres de
  l'établissement** (jamais codés en dur : un décret qui change les taux
  se corrige en un champ, pas un déploiement) ; ITS saisi manuellement,
  faute de barème vérifié. Le net calculé devient `Salaire.montant`,
  exactement comme avant - c'est toujours lui qui part en dépense de
  Caisse une fois le salaire marqué payé, jamais le brut. Les parts
  employeur (INPS/AMO) sont purement informatives (coût réel pour
  l'établissement), n'affectent jamais le net payé à l'employé. Export
  PDF du bulletin, sur le même principe que le reçu de paiement.
- **Totalement additif.** L'ancienne saisie simple d'un salaire
  (`saisir_salaire_vue`) reste inchangée et pleinement fonctionnelle pour
  les écoles qui n'ont pas besoin du détail - les nouveaux champs du
  bulletin détaillé restent vides pour ces lignes-là.

15 nouveaux tests (contrats, congés avec calcul de solde et exclusion du
dimanche, cotisations calculées selon les taux par défaut et des taux
personnalisés, net négatif refusé, génération et export PDF du
bulletin) - suite complète de l'application verte après correction d'une
régression détectée par les tests existants (le formulaire des
paramètres d'établissement, qui a gagné 4 nouveaux champs obligatoires,
n'était plus rempli en entier par un ancien test). Vérifié de bout en
bout (navigateur, compte comptable réel avec 2FA) : création d'un
contrat, affichage du solde de congés en direct au choix de l'employé,
génération d'un bulletin avec calcul correct des cotisations, téléchargement du PDF.

## État du projet : Phase 41 — Saisie des notes hors-ligne, journal de caisse SYSCOHADA

Deux ajouts indépendants, choisis dans la liste des écarts face aux
plateformes concurrentes maliennes.

### Saisie des notes hors-ligne

Même mécanisme que la Phase 38 (saisie des absences), étendu à la saisie
des notes : la page se met en cache après une visite en ligne, la
soumission part en AJAX et file dans la file d'attente locale en cas de
coupure réseau, synchronisation automatique au retour. Pour y arriver
sans dupliquer tout le mécanisme, la fonction JS qui ajoute une ligne au
tableau "déjà saisi" après une synchronisation a été généralisée
(`ajouterLigneResultat`, pilotée par un attribut `data-ligne-champs` sur
le tableau plutôt que des noms de colonnes codés en dur) - réutilisée
telle quelle par les notes, sans rien changer à son comportement pour les
absences. Vérifié explicitement par un test de non-régression dédié
(scénario hors-ligne réel, navigateur) sur les absences après ce
remaniement, en plus du nouveau scénario équivalent pour les notes.

### Journal de caisse SYSCOHADA

Avant de construire quoi que ce soit, cadrage explicite avec l'utilisateur
sur le périmètre : une comptabilité SYSCOHADA complète (plan de comptes,
partie double, grand livre, bilan) est un vrai logiciel de comptabilité à
elle seule - plusieurs semaines de travail, et un risque élevé d'erreur
difficile à corriger une fois des écritures réelles enregistrées. Choix
retenu : un journal de caisse exportable, entièrement dérivé des
`MouvementCaisse` déjà enregistrés - **aucun nouveau modèle, aucune
nouvelle saisie, donc aucun risque sur les données existantes**.

- Une entrée (paiement de scolarité) débite la Caisse (571) et crédite
  les Produits de scolarité (706) ; une sortie (salaire payé) débite les
  Charges de personnel (661) et crédite la Caisse - imputation fixe et
  déterministe, puisqu'un mouvement de Caisse ne peut provenir que d'un
  paiement ou d'un salaire (jamais les deux, contrainte déjà en place).
- Balance des 3 comptes mouvementés (débit/crédit) affichée en tête de
  page.
- Export CSV (point-virgule, BOM UTF-8 pour un affichage correct des
  accents dans Excel) pour transmission directe à un comptable externe.
- Mouvements annulés exclus, comme pour le registre de Caisse existant.

9 nouveaux tests (notes hors-ligne, imputation SYSCOHADA par mouvement,
balance des comptes, exclusion des mouvements annulés, export CSV,
contrôle d'accès). Vérifié de bout en bout (navigateur) : notes et
absences saisies hors-ligne puis synchronisées avec succès chacune de
leur côté ; journal SYSCOHADA affiché avec comptes et balance corrects,
CSV téléchargé et vérifié.

## État du projet : Phase 42 — Enseignement professionnel (CAP/BT)

Ajout demandé pour pouvoir enregistrer une école professionnelle. Recherche
préalable sur la structure réelle malienne (après le DEF, un élève part soit
au Lycée général soit en enseignement technique et professionnel - CAP en 2
ans ou BT en 4 ans - jamais les deux à la suite), puis cadrage avec
l'utilisateur sur deux points avant de coder : un même établissement
peut cumuler fondamental/lycée ET professionnel, et seule la distinction
CAP/BT est structurée pour cette version (le métier exact reste en texte
libre dans le nom de la classe, comme aujourd'hui pour les autres cycles).

- **Nouveau cycle `Professionnel`**, parallèle au Lycée - pas une suite du
  2ème cycle. Nouvelle filière CAP/BT sur la classe, même principe que les
  séries du Bac existantes.
- **Réglage indépendant de la formule** (`Etablissement.inclut_
  professionnel`) plutôt qu'une formule de plus : contrairement au 1er
  cycle/2ème cycle/Lycée qui forment une progression cumulative, le
  professionnel se cumule avec n'importe laquelle. Modifiable uniquement
  depuis l'espace plateforme (propriétaire), comme la formule.
- **Bug pré-existant trouvé et corrigé en vérifiant réellement le scénario
  au navigateur** : le menu déroulant « Formule » de la page Établissements
  utilisait `onchange="this.form.submit()"` - une syntaxe que la politique
  CSP de l'application bloque silencieusement (aucune erreur visible pour
  l'utilisateur, juste un menu qui ne sauvegarde jamais son changement).
  Remplacé par le mécanisme `data-auto-submit` déjà utilisé ailleurs dans
  l'application, qui passe par un fichier JS externe et respecte donc la
  CSP. La nouvelle case à cocher « Professionnel » suit le même principe.

8 nouveaux tests (cycle/filière, cumul avec n'importe quelle formule,
formulaire de création de classe filtré selon le réglage, indépendance entre
formule et case professionnelle). Vérifié de bout en bout (navigateur,
scénario réel) : activation du réglage par le propriétaire de la
plateforme, apparition du cycle dans le formulaire de création de classe
côté école, création d'une classe CAP, filière visible dans la liste des
classes.

## État du projet : Phase 43 — Formules « Lycée seul » et « Professionnel seul »

Constat après la Phase 42 : les trois formules existantes sont
cumulatives à partir du 1er cycle, donc un établissement avait forcément
le 1er cycle et ne pouvait pas être uniquement un lycée ou uniquement une
école professionnelle (le réglage « Professionnel » ne faisait que
s'ajouter).

- Deux formules ajoutées à `PlanEtablissement` : **Lycée seul** (cycle
  Lycée uniquement, cumulable avec le réglage « Professionnel ») et
  **Enseignement professionnel seul** (cycle Professionnel uniquement ; le
  curseur « Professionnel » de la liste des établissements est alors
  remplacé par « Inclus dans la formule »).
- Migration `etablissement/0010` : simple modification des choix du champ,
  aucun changement de schéma ni de données.
- Pas de rôle « Directeur du professionnel » : une école professionnelle
  seule se gère avec les rôles à accès complet (fondateur, administrateur
  général, développeur). À ajouter si le besoin se confirme.
- Repasser un établissement de « Professionnel seul » à une autre formule
  ne supprime pas ses classes professionnelles, mais l'établissement ne
  peut plus en créer tant que le réglage « Professionnel » n'est pas
  activé (même comportement qu'une rétrogradation de formule existante).

3 nouveaux tests (lycée seul, lycée seul + professionnel, professionnel
seul sans activer le réglage). Écran non vérifié au navigateur.

## État du projet : Phase 44 — Le propriétaire de la plateforme n'accède plus aux pages d'une école

Audit demandé après avoir constaté que le propriétaire (superutilisateur sans
établissement) voyait dans sa barre latérale tous les modules d'une école.
Méthode : deux écoles avec données complètes (élèves, paiements, salaires,
documents, annonces, candidats), puis ~70 pages ouvertes avec ce compte.

- **Aucune fuite entre vraies écoles** : les données des écoles A et B
  n'apparaissent jamais, et tout accès direct par identifiant renvoie 404.
- **Faiblesse trouvée** : sans établissement, le filtre `etablissement=...`
  devient `etablissement IS NULL`. Le propriétaire voyait donc (et pouvait
  corriger ou créer) toute ligne orpheline sans établissement, héritée des
  anciennes installations. Rien ne prouve qu'il y en ait en production.
- **Correction** : `ProprietairePlateformeMiddleware` ferme au propriétaire
  toutes les pages métier (liste blanche : refus par défaut, donc une future
  application est fermée tant qu'on ne l'autorise pas). Sa barre latérale est
  réduite à « Compte » et « Plateforme », et son tableau de bord renvoie vers
  la Plateforme. Les pages publiques de vérification de document restent
  ouvertes.
- **Non traité (décision à prendre)** : l'admin Django (`/admin/`) montre au
  propriétaire les données de toutes les écoles, sans filtre. Seuls les
  comptes « staff » y accèdent et aucune page web ne donne ce statut.

7 nouveaux tests ; un test existant ajusté (le tableau de bord du propriétaire
redirige désormais, le test suit la redirection).

## État du projet : Phase 45 — Accès du propriétaire au compte développeur d'une école

Le propriétaire de la plateforme ne peut pas retenir les identifiants du
compte développeur de chaque école. Un bouton **Accéder** sur chaque ligne de
la page Établissements le connecte directement au compte développeur de
l'école (le plus ancien compte développeur actif), sans mot de passe.

- **Réservé au propriétaire sans établissement**, en POST uniquement (CSRF).
  Refusé si l'école est suspendue ou n'a aucun compte développeur actif ; un
  autre superutilisateur n'est jamais ciblé.
- **Bandeau « Revenir à mon compte »** sur toutes les pages pendant l'accès ;
  le retour ne repose que sur une clé de session posée par le serveur.
- **Traçabilité** : le début et la fin de l'accès sont écrits dans le journal
  d'audit **de l'école** (elle voit qui est entré), et toute action faite
  pendant l'accès porte `via_proprietaire` dans ses détails. La « dernière
  connexion » du compte de l'école n'est pas modifiée.
- **Garde-fous** (`AccesDelegueMiddleware`) : changement de mot de passe,
  d'email et réglages 2FA refusés pendant l'accès (dépanner, pas prendre le
  compte) ; la session se ferme si le compte propriétaire n'est plus valide.
- **2FA** : le propriétaire a déjà passé la sienne. Le compte de l'école n'est
  donc pas forcé d'en activer une, ce qui enregistrerait l'appareil du
  propriétaire sur ce compte.

Limite connue : si une école a plusieurs comptes développeur, c'est toujours le
plus ancien qui est utilisé. Écran non vérifié au navigateur (tests
automatiques uniquement : 16 nouveaux tests, dont la 2FA réactivée en test).

## État du projet : Phase 46 — Audit de fuites de données (toutes routes, tous rôles)

Audit demandé sur l'ensemble de l'application. Méthode : deux écoles avec tous
les rôles et des données dans chaque module ; les routes sont énumérées
automatiquement (`get_resolver`), puis chaque rôle de l'école A essaie en GET
et en POST toutes les pages et tous les objets de l'école B, un visiteur non
connecté essaie tout, et des comptes limités d'une même école essaient les
données d'un autre élève. Le test est conservé (`comptes/test_isolation_complete.py`) :
une future page sans filtre par établissement le fera échouer.

**Aucune fuite entre écoles** (17 rôles, ~70 routes, GET et POST) et rien n'est
modifiable d'une école à l'autre. Un visiteur anonyme n'atteint que les pages
publiques.

Problèmes trouvés et corrigés :
- **Un élève voyait tous les élèves de son école** (nom, matricule, classe) dans
  la liste et la recherche : seul le parent était restreint. Un élève ne voit
  plus que lui-même.
- **Fichiers téléversés** (bibliothèque, annonces, justificatifs de transfert,
  logo) : le stockage les sert par une adresse publique non signée
  (`custom_domain`, donc `querystring_auth` sans effet) avec un nom prévisible, et
  S3 écrasait un fichier de même nom, y compris celui d'une autre école. Le chemin
  contient désormais l'école et un jeton aléatoire (`comptes/uploads.py`) et
  `file_overwrite` est désactivé. Les fichiers déjà stockés gardent leur ancienne
  adresse.
- **Portail parent en erreur 500** dès qu'un enfant était inscrit (import manquant,
  bogue antérieur sans rapport avec les fuites ; page non couverte par un test).

**À décider hors code** : rendre le bucket Supabase privé et servir les médias par
URL signée (retirer `custom_domain`), seule façon de protéger aussi les fichiers
déjà téléversés. Non fait ici car cela dépend d'un réglage Supabase à tester.
L'admin Django (`/admin/`) montre toujours toutes les écoles au propriétaire.

Tests ajoutés : isolation complète (4), élève restreint (3), chemins de fichiers
(5), portail parent (3).

## État du projet : Phase 47 — Envoi d'emails : diagnostic, copie cachée, adresses automatiques

Mise en service de l'envoi d'emails sur Render (formule gratuite). Les ports SMTP
25, 465 et 587 y sont bloqués depuis septembre 2025 : Gmail (587) est injoignable
(`OSError: [Errno 101] Network is unreachable` dans Sentry). Solution retenue, sans
code : un relais SMTP sur le port 2525 (Brevo, 300 emails par jour gratuits), avec
`EMAIL_HOST`, `EMAIL_PORT=2525`, `EMAIL_HOST_USER` (identifiant `@smtp-brevo.com`),
`EMAIL_HOST_PASSWORD` (clé de l'onglet « Clés SMTP », pas une clé API) et
`DEFAULT_FROM_EMAIL` (expéditeur validé chez Brevo). Brevo bloque par défaut les
adresses IP non autorisées : à désactiver pour les clés SMTP (Sécurité, IPs autorisées),
car Render gratuit n'a pas d'IP fixe. Un expéditeur `@gmail.com` est réécrit en
`@brevosend.com` tant qu'aucun domaine n'est authentifié (DKIM).

Dans le code :
- **Diagnostic d'échec** (`comptes.mail.diagnostic_smtp`) : à chaque envoi qui échoue,
  logs et contexte Sentry « smtp » indiquent serveur, port, identifiant, longueur du
  mot de passe et indicateurs de forme (espace ou saut de ligne caché, préfixe d'une
  clé SMTP ou API Brevo). Jamais le mot de passe ni un morceau de sa valeur.
- **Copie cachée** : un email à plusieurs destinataires (annonces) montrait l'adresse
  de tous les destinataires à chacun (champ « À » partagé). Ils sont maintenant en
  copie cachée, par lots de 50 (`construire_message`, aussi utilisé par la file
  différée). Au premier lot en échec on s'arrête, pour ne pas multiplier les délais.
- **Adresses automatiques** : les élèves inscrits par l'école ont une adresse générée
  `matricule@eleves.local` : elles ne sont plus destinataires d'annonces (rebonds,
  quota gaspillé, réputation de l'expéditeur).

Tests : 3 (diagnostic), 6 (copie cachée, lots, file différée), 1 (adresses
automatiques) ; un test existant corrigé (il vérifiait les destinataires dans « À »).

## État du projet : Phase 48 — Connexion des élèves, mot de passe provisoire, ordinateurs partagés

**Connexion des élèves.** Un élève inscrit par l'école n'a pas de vraie adresse email
(`matricule@eleves.local`, mot de passe aléatoire inconnu). Jusqu'ici il lui fallait « Mot
de passe oublié » puis l'email du parent, puis taper `matricule@eleves.local` à la
connexion. Désormais :
- la page de connexion accepte le **matricule** à la place de l'email (élèves seulement ;
  même message d'erreur générique, même verrouillage après échecs) ;
- la direction et le secrétariat peuvent remettre un **mot de passe provisoire** depuis le
  dossier de l'élève (`scolarite.views.mot_de_passe_provisoire`) : format `XXXX-XXXX`,
  affiché une seule fois sur une page à imprimer, jamais conservé en clair ni écrit dans le
  journal d'audit, valable 72 h, annulé par le suivant, déverrouille le compte. Réservé à
  fondateur, administrateur général, développeur, super administrateur, secrétaire et
  directeurs de cycle, pour un élève de leur école et de leur cycle (pas d'enseignant, de
  parent, de comptable, de Censeur ni de Surveillant général).
- À sa première connexion l'élève ne peut rien faire d'autre que choisir son mot de passe
  (`ChangementMotDePasseObligatoireMiddleware`).

**Fuites corrigées en vérifiant l'application :**
- Les pages de saisie hors-ligne (absences, notes : listes d'élèves) restaient dans le cache
  du navigateur après la déconnexion, lisibles hors-ligne par la personne suivante sur un
  ordinateur partagé : le service worker les efface à la déconnexion et à l'affichage de la
  page de connexion.
- Aucune page d'un utilisateur connecté n'est plus mise en cache par le navigateur
  (`Cache-Control: no-store`) : le bouton « Précédent » après déconnexion ne réaffiche rien.
- Sentry ne joint plus les variables locales aux erreurs (`include_local_variables=False`) :
  il enregistrait le texte des emails, donc les liens de réinitialisation de mot de passe.

Limites connues : un mot de passe imprimé reste valable jusqu'à sa première utilisation ou
72 h ; la file de saisies hors-ligne en attente (IndexedDB) n'est pas vidée à la déconnexion
(elle est rejouée avec la session de la personne connectée au retour du réseau). Écran et
service worker non vérifiés au navigateur : tests automatiques seulement.

Tests : 21 (matricule, mot de passe provisoire, obligation de changement, cache, service
worker, droits et cloisonnement du mot de passe provisoire).

## État du projet : Phase 49 — Identité Nexora

Changement de nom et de logo de la plateforme.

| Élément | Valeur |
|---|---|
| Nom commercial | NEXORA ÉDUCATION (`settings.NOM_COMMERCIAL`) |
| Nom du logiciel | Nexora (`settings.NOM_PLATEFORME`) |
| Slogan | Toute votre école. Une seule vision. (`SLOGAN_PLATEFORME`) |
| Positionnement | La plateforme intelligente de gestion et de pilotage des établissements scolaires. (`POSITIONNEMENT_PLATEFORME`) |
| Description | `DESCRIPTION_PLATEFORME` (page d'accueil publique) |

Ces valeurs sont injectées dans tous les gabarits par
`comptes.context_processors.identite_plateforme` (`nom_plateforme`, `nom_commercial`,
`slogan_plateforme`, `positionnement_plateforme`, `description_plateforme`). Pour renommer
à nouveau, il suffit de les modifier dans `config/settings.py`.

**Où apparaît l'identité de la plateforme** (et pas celle d'une école) : page d'accueil
publique, page de connexion tant qu'aucune école n'est choisie, espace du propriétaire de la
plateforme (barre latérale), page « aucun établissement », emails (en-tête), nom de
l'application installable (quand personne n'est connecté), nom affiché dans l'application
d'authentification (2FA, pour les nouveaux enregistrements) et en-tête de l'administration
Django. Dès qu'une école est choisie ou connectée, son propre nom et son propre logo
remplacent ceux de Nexora, comme avant.

**Logo.** Source : `design/logo-nexora.png` (aplat bleu marine et turquoise sur fond blanc).
`python design/generer_identite_visuelle.py` en tire : le logo à fond transparent
(`static/img/logo-nexora.png`), le favicon (`favicon.ico`, `favicon-32.png`) et les icônes de
l'application installable (`static/img/icons/` : 192, 512, « maskable » 512, iPhone 180). Le
fond blanc est retiré proprement (bords nets sur tout fond) ; à relancer si le logo change.
Le bleu marine du logo disparaît sur le bleu nuit de l'interface : il est donc toujours posé
sur une pastille blanche dans la barre latérale, l'accueil et l'annuaire.

Non modifié volontairement : le nom du service Render (`plateforme-gestion-scolaire`, donc
l'adresse du site), le nom interne de la feuille de style (`toumai.css`), et les couleurs de
l'interface (bleu nuit et or) : le logo est bleu marine et turquoise, un alignement de la
couleur d'accent sur le turquoise est possible mais demande une décision de design.

À vérifier hors code avant tout usage commercial : disponibilité du nom « Nexora » (recherche
d'antériorité à l'OAPI, dont le Mali est membre), du nom de domaine et des comptes de réseaux
sociaux. Les icônes installées sur les téléphones se mettent à jour d'elles-mêmes avec un
certain délai, ou après une réinstallation.

13 tests (identité, manifeste, images, gabarits).

## Sauvegardes locales (base de données et médias)

Le plan gratuit Render utilisé pour ce déploiement n'offre ni disque
persistant, ni tâches planifiées (cron) : la sauvegarde ne peut donc pas
tourner automatiquement sur le serveur lui-même. `manage.py
sauvegarder_donnees` est prévue pour être lancée depuis un poste local,
pointée vers la base et le bucket de production.

1. Dans le dossier du projet, sur le poste qui exécutera les sauvegardes,
   créez ou éditez `.env` avec les vraies valeurs de production :
   `DATABASE_URL` (la chaîne de connexion Supabase - Session pooler
   recommandé) et, si les médias sont sur Supabase Storage,
   `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME`,
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (les mêmes valeurs que sur
   Render). **Ne commitez jamais ce `.env` rempli.**
2. Pour la base PostgreSQL, installez les outils client PostgreSQL
   (https://www.postgresql.org/download/) et vérifiez que `pg_dump` est
   accessible depuis une invite de commande (`pg_dump --version`).
3. Test manuel :
   ```
   python manage.py sauvegarder_donnees --destination "D:\Sauvegardes\EcoleGestion"
   ```
   Chaque exécution crée un sous-dossier horodaté
   (`sauvegarde_20260101_020000`) contenant `base_de_donnees.sql` (ou
   `.sqlite3` en local) et `medias/`.
4. Pour l'automatiser à la fréquence de votre choix, ouvrez le
   **Planificateur de tâches Windows** (`taskschd.msc`) → *Créer une tâche
   de base* → choisissez la fréquence (quotidienne, hebdomadaire...) →
   action *Démarrer un programme* :
   - Programme : le chemin complet de votre `python.exe`
   - Arguments : `manage.py sauvegarder_donnees --destination "D:\Sauvegardes\EcoleGestion"`
   - Démarrer dans : le dossier du projet (celui contenant `manage.py`)
5. Testez la tâche planifiée une fois manuellement (clic droit → Exécuter)
   avant de lui faire confiance sur la durée. Pensez aussi, de temps en
   temps, à restaurer une sauvegarde sur une base de test pour vérifier
   qu'elle est réellement exploitable.

## À faire

### Exploitation production

- `AWS_STORAGE_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` et
  `AWS_S3_ENDPOINT_URL` doivent pointer vers un stockage S3/R2 persistant ;
  le démarrage en production est refusé sans stockage objet.
- `REDIS_URL` est nécessaire avec plusieurs workers afin que les limites de
  débit soient partagées entre les processus.
- `SENTRY_DSN` active le suivi des erreurs et `EMAIL_ASYNC=True` active la
  boîte d'envoi persistante. Traiter cette boîte régulièrement avec :
  `python manage.py envoyer_emails` (le cron Render est déclaré dans
  `render.yaml` et doit être vérifié après déploiement).
- Sauvegarder PostgreSQL et le bucket médias selon une politique quotidienne,
  conserver plusieurs versions et tester une restauration au moins chaque
  trimestre. Une sauvegarde non restaurée n'est pas considérée comme testée.
- La CI `.github/workflows/ci.yml` exécute les contrôles Django, les migrations,
  la suite de tests et la cohérence des dépendances.

### Déployer sur Render sans exposer de secrets

1. Révoquez toute ancienne clé Groq ayant existé dans un fichier `.env`, puis
  créez un nouveau service depuis `render.yaml` avec **New Blueprint**.
2. Dans les variables du service web et du cron email, renseignez uniquement
  dans Render : `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
  `DEFAULT_FROM_EMAIL`, `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`,
  `AWS_S3_REGION_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` et,
  si nécessaire, `GROQ_API_KEY` et `SENTRY_DSN`.
3. Remplacez `toumai-edu-school.onrender.com` dans `render.yaml` par le domaine
  Render réellement attribué, puis ajoutez votre domaine personnalisé dans
  `ALLOWED_HOSTS` et `CSRF_TRUSTED_ORIGINS`.
4. Utilisez un bucket S3/R2 privé pour les médias. Ne mettez jamais les clés
  S3 dans Git ou dans `.env` ; `AWS_QUERYSTRING_AUTH=True` produit des liens
  temporaires pour les objets privés.
5. Vérifiez que les services web, PostgreSQL, Redis et le cron
  `plateforme-gestion-scolaire-email-worker` sont tous actifs. Le cron traite
  `EmailOutbox` toutes les cinq minutes.
6. Dans les logs Render, attendez successivement `migrate`, `collectstatic` et
  le démarrage Gunicorn sans traceback. Testez ensuite inscription, code
  email, mot de passe oublié, upload, paiement et génération PDF.
7. Créez le premier compte administrateur avec une procédure sécurisée, puis
  configurez l'établissement depuis `/espace-developpeur/etablissement/`.

Ne déployez pas `db.sqlite3`, `media/` ni un compte de démonstration comme
données de production. Le service Render doit démarrer sur PostgreSQL neuf et
les données de démonstration doivent être créées uniquement à la demande.

1. Configurer les fournisseurs SMS, WhatsApp et Mobile Money retenus
2. Ajouter les connecteurs fournisseurs SMS, WhatsApp et Mobile Money avec
  webhooks signés, idempotence et rapprochement comptable
3. Mettre en place sauvegardes/restauration, tests de charge et recette utilisateur
4. Ajouter les gabarits email HTML et les préférences de notification

### Import Excel

Le premier import sécurisé concerne les élèves et fonctionne par commande :

```bash
python manage.py importer_eleves_excel eleves.xlsx --etablissement 1 --dry-run
python manage.py importer_eleves_excel eleves.xlsx --etablissement 1
```

Le mode aperçu n'écrit rien. Les colonnes obligatoires sont `prenom`, `nom`
et `classe`. Toute erreur annule l'import complet ; les lignes valides ne
sont jamais écrites partiellement.

### Secret local

Une clé Groq ne doit jamais être conservée dans `.env`, une base SQLite ou
une archive. Toute clé ayant existé dans un environnement de développement
doit être révoquée auprès de Groq puis remplacée uniquement par une variable
secrète de l'hébergeur.

## Système de design

Le fichier `static/css/toumai.css` contient l'ensemble des jetons de design
(couleurs, typographie, rayons) sous forme de variables CSS en haut de
fichier. Cette palette est l'identité visuelle du **logiciel** ; elle est
distincte du nom/logo de chaque établissement, qui restent configurables
indépendamment. Pour ajuster la palette ou la typographie du logiciel
lui-même, modifiez ces variables plutôt que les règles individuelles.

Bootstrap est auto-hébergé (`static/css/bootstrap.min.css`, non modifié,
version 5.3.3) pour la grille et les mécanismes de base des formulaires ;
`toumai.css`, chargé après, redéfinit l'apparence de tous les composants
(boutons, tableaux, cartes, badges, alertes). Pour mettre à jour Bootstrap :
`npm pack bootstrap@<version>` puis remplacer le fichier.

Les polices (Fraunces, Public Sans) sont chargées depuis Google Fonts par
défaut — accessible dans n'importe quel navigateur avec accès internet
normal. Pour un environnement sans accès à Google Fonts, les polices de
secours (Georgia, sans-serif système) s'appliquent automatiquement.
