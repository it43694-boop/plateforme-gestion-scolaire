# Yelenova — plateforme de gestion scolaire

**La lumière du savoir.** Yelenova est le logiciel de gestion scolaire
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
- **Nom du logiciel** : voir « Phase 49 — Identité de la plateforme » et « Phase 71 — Yelenova » plus bas. Distinct
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
  développeur (voir la Phase 58 : le propriétaire de la plateforme crée le
  fondateur et l'administrateur général depuis sa page, ou la console),
  pour limiter la portée d'un compte développeur compromis.
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
  les paliers d'appréciation (Excellent ≥17, Très Bien ≥16, Bien
  ≥13, Passable ≥10, Insuffisant en dessous). **Corrigé ensuite** : cette
  échelle, relevée sur un seul bulletin, n'avait pas « Assez Bien » (une
  note de 13 sortait « Bien »). Elle compte maintenant six niveaux :
  Excellent ≥18, Très Bien ≥16, Bien ≥14, Assez Bien ≥12, Passable ≥10,
  Insuffisant en dessous (`pedagogie.models.APPRECIATIONS_PAR_SEUIL`, une
  seule règle pour les matières, la conduite et le trimestre). Faute de pouvoir
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

## État du projet : Phase 49 — Identité de la plateforme

Nom, slogan et logo de la plateforme (nommée « Nexora » à l'origine, devenue **Yelenova** en phase 71).

| Élément | Valeur |
|---|---|
| Nom commercial | YELENOVA (`settings.NOM_COMMERCIAL`) |
| Nom du logiciel | Yelenova (`settings.NOM_PLATEFORME`) |
| Slogan | La lumière du savoir (`SLOGAN_PLATEFORME`, celui du logo) |
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
remplacent ceux de Yelenova, comme avant.

**Logo.** Source : `design/logo-yelenova.png` (dessin en dégradés vert et or : livre ouvert, soleil, carte du Mali, nom et slogan « La lumière du savoir », sur fond blanc).
`python design/generer_identite_visuelle.py` en tire : le logo complet (`static/img/logo-yelenova.png`), l'**emblème seul** (`logo-yelenova-embleme.png`, soleil et livre, utilisé dans la barre latérale, la connexion, l'accueil, l'annuaire et les pages légales), le favicon (`favicon.ico`, `favicon-32.png`) et les icônes de l'application installable (`static/img/icons/` : 192, 512, « maskable » 512, iPhone 180). Le fond n'est pas rendu transparent : les blancs du dessin (pages du livre, reflets) disparaîtraient avec lui. Il est seulement blanchi (le fond de la source est presque blanc, d'où un cadre grisâtre visible sans cela) et l'interface pose toujours le logo sur une pastille blanche (`toumai.css`, `.marque-logo-plateforme`, `.auth-logo-plateforme`...). À relancer si le logo change.

Non modifié volontairement : le nom du service Render (`plateforme-gestion-scolaire`, donc
l'adresse du site), le nom interne de la feuille de style (`toumai.css`), et les couleurs de
l'interface (bleu nuit et or) : le logo est vert et or, un alignement de la couleur d'accent sur le
vert est possible mais demande une décision de design.

À vérifier hors code avant tout usage commercial : disponibilité du nom « Yelenova » (recherche
d'antériorité à l'OAPI, dont le Mali est membre), du nom de domaine et des comptes de réseaux
sociaux. Les icônes installées sur les téléphones se mettent à jour d'elles-mêmes avec un
certain délai, ou après une réinstallation.

13 tests (identité, manifeste, images, gabarits).

## État du projet : Phase 50 — Statistiques de l'éducation (annuaire statistique du Mali)

Recherche préalable sur les statistiques scolaires du Mali (annuaire de la CPS, « Le Mali en chiffres » de
l'INSTAT, étude UNICEF/MEN sur l'eau et l'assainissement dans les écoles de 2017, plan décennal PRODEC 2
2019-2028), puis comparaison avec ce que l'application gérait. **Limite** : l'annuaire de la CPS et son
questionnaire complet n'ont pas pu être consultés (fichiers inaccessibles). Les rubriques ci-dessous suivent
les indicateurs publiés et les priorités du plan décennal ; **elles sont à comparer au questionnaire que remet
l'Académie d'enseignement** avant toute déclaration officielle.

Principe : uniquement des ajouts (champs facultatifs, nouvelles tables, aucune donnée existante modifiée) ;
tout ce qui est sensible (état civil, handicap, déplacement) reste réservé à l'élève, ses parents et
l'administration scolaire (`scolarite.models.ROLES_ETAT_CIVIL_ELEVE`) et n'apparaît jamais dans le journal d'audit.

- **Fiche statistique annuelle** (Statistiques > Fiche annuelle, impression, export Excel et export CSV) : effectifs par niveau et par
  sexe, filles pour 100 garçons, élèves par classe, redoublants, nouveaux inscrits, âge des élèves, enseignants par
  situation administrative, élèves par enseignant, résultats aux examens, infrastructures. Limitée aux classes visibles
  (un directeur de cycle ne voit que son cycle). « Inscrits » = toutes les inscriptions de l'année, quel que soit leur
  statut (une année terminée n'a plus d'élève « en cours »). Redoublants et nouveaux ne sont calculés que si l'année
  précédente contient des inscriptions. Les taux de scolarisation (brut, net) ne sont pas calculés : ils exigent la
  population par âge du recensement. Export protégé contre l'injection de formule (cellule commençant par `=`, `+`,
  `-`, `@`).
- **Résultats aux examens** : certificat d'entrée en 7ème année, DEF, Bac (par série), CAP et BT (par domaine). Saisie par
  classe (direction et secrétariat), taux de réussite sur les présents (les absents n'y comptent pas), visible dans
  le dossier de l'élève. Un examen n'est proposé que pour le cycle correspondant ; une classe CAP ne passe pas le BT.
- **Fiche d'infrastructures** (une par école et par année, modifiée par la direction générale seulement) : salles de
  classe (bon état, matériaux provisoires), places assises, points d'eau, latrines, lavage des mains, électricité,
  manuels, cantine ; ratios (élèves par salle, manuels par élève, objectif PRODEC 2 : un par élève) masqués aux directeurs
  de cycle, car ils portent sur toute l'école.
- **Élèves** : situation de handicap et situation de déplacement (déplacé interne, réfugié), à l'inscription et dans
  l'espace développeur.
- **Personnel** : « fonctionnaire des collectivités territoriales » (quatrième catégorie du PRODEC 2), formation
  pédagogique (formé, en formation, non formé), date de prise de service, heures d'enseignement par semaine.
- **Préscolaire** : nouveau cycle (petite, moyenne, grande section), activable par le propriétaire de la plateforme comme
  l'enseignement professionnel (case « Préscolaire »), ou formule « Préscolaire seul ». Les écoles existantes ne
  changent pas.
- **Situation de l'école** : ouvert, fermé temporairement ou relocalisé, avec motif (insécurité...) et date. Descriptif :
  elle n'empêche aucune connexion (seule la désactivation par la plateforme le fait).
- **Domaine CAP/BT** : industriel ou tertiaire, facultatif (les statistiques officielles les séparent).

Également : un identifiant d'année non numérique dans l'adresse des statistiques renvoie une page introuvable (et non
plus une erreur serveur) ; le test d'isolation entre écoles couvre les nouvelles données.

Migrations (toutes additives, aucune opération destructive) : `comptes/0018`, `etablissement/0013`, `scolarite/0022`.
Non fait / à vérifier : le questionnaire officiel de la CPS ; la durée du BT (les sources divergent : l'application
indique 4 ans, une source indique 2 ans après le CAP) ; les listes de types de handicap à confirmer avec le
questionnaire officiel ; un identifiant national d'élève (aucune source consultée n'en mentionne).

Tests : 81 nouveaux (calculs vérifiés à la main, cloisonnement, droits, export, formulaires, interface).

## État du projet : Phase 51 — Audit de fuites (données de l'éducation, existence entre écoles, Sentry)

Audit demandé après l'ajout des statistiques de l'éducation. Nouveaux tests : `statistiques/test_fuites_education.py`
(matrice des 17 rôles sur le dossier d'un élève, pages publiques, points JSON, exports, journal d'audit, Assistant) et un
test d'isolation dans `comptes/test_isolation_complete.py`.

**Corrigé :**
- **Existence d'un élève ou d'un compte d'une autre école devinable.** Pour un matricule d'une autre école, ces adresses
  répondaient « interdit » (403) alors qu'un matricule inexistant répondait « introuvable » (404) : on pouvait donc tester
  quels matricules existent ailleurs. Concernait le dossier, l'attestation, la clôture d'inscription, le bulletin (page et
  PDF), l'historique d'absences, la messagerie, l'Assistant (message différent) et la remise d'un mot de passe provisoire.
  Désormais `scolarite.models.eleve_de_l_etablissement_ou_404` : même réponse qu'un objet inexistant. Le test compare, pour
  chaque rôle et chaque adresse (GET et POST), la réponse pour un objet de l'autre école et pour un objet inexistant.
- **Sentry joignait aux erreurs les champs du formulaire reçu** (noms, naissance, handicap, email du parent), même sans
  données personnelles activées : `max_request_body_size="never"` et `send_default_pii=False`.
- **Inscription publique sans limite de débit** : on pouvait tester en masse quels emails et quels téléphones de parents
  sont inscrits. Limite de 10 essais par minute et par adresse IP (`LimiteInscriptionTests`).
- **Bogue existant** trouvé en passant : s'inscrire comme enseignant ou membre du personnel **sans téléphone** provoquait
  une erreur serveur (500). Corrigé (`InscriptionSansTelephoneTests`).

**Vérifié sans problème** : aucun secret ni fichier de données dans l'historique Git ; les nouvelles données (handicap,
déplacement, résultats d'examen) ne sont visibles que de l'élève, de ses parents et de l'administration, ne sont jamais
dans le journal d'audit ni dans ce que l'Assistant envoie à l'IA ; les vérifications publiques par QR code n'exposent
qu'une liste fixe de champs.

**Corrigé ensuite, à la demande « je ne veux pas de fuite de données » (`comptes/test_fuites_externes.py`,
`assistant/test_anonymisation.py`) :**
- **Médias en liens signés temporaires.** `config/settings.py` ne contient plus l'identifiant du projet Supabase ni le
  chemin du bucket public (le dépôt est public). Les fichiers (logos, documents, justificatifs de transfert) sont servis
  par des liens signés valables 1 h (`AWS_QUERYSTRING_EXPIRE`, signature V4). Le domaine public n'est utilisé que si
  `AWS_S3_CUSTOM_DOMAIN` est défini : **le laisser vide**. Sans domaine public, les liens sont toujours signés, même si
  `AWS_QUERYSTRING_AUTH=False` est resté défini sur Render (`config/stockage.py`) : un lien non signé répond
  « Missing signature » et les logos s'affichent cassés (constaté après la mise en ligne de la version 1.1.0).
- **L'Assistant n'envoie plus à l'IA (Groq, États-Unis) le nom, le matricule ni la référence des reçus** de l'élève
  interrogé. La question tapée est nettoyée avant l'envoi : nom et prénom de l'élève (avec ou sans accents), adresses
  email et longs numéros (matricule, téléphone) sont remplacés. L'écran prévient de ne pas taper le nom d'une personne :
  un nom tapé qui n'est pas celui de l'élève ne peut pas être deviné.
- **Assistant : un matricule d'une autre école** répond « introuvable », comme un matricule inexistant.
- **`docker-compose.yml`** n'écrit plus de mot de passe de base de données : `POSTGRES_PASSWORD` est obligatoire (dans
  `.env`), et la base et Redis ne sont pas publiés hors de la machine.
- Les prochains commits portent l'adresse `…@users.noreply.github.com` au lieu de l'email personnel.

**À faire de votre côté (non réalisable par le code) :**
- **Rendre le bucket Supabase `medias` privé, APRÈS le déploiement** de cette version (sinon les logos et documents
  existants s'afficheraient cassés), puis vérifier un logo, une attestation et un bulletin PDF. Les fichiers téléversés
  avant la Phase 46 ont des noms prévisibles : tant que le bucket est public, ils restent lisibles par quiconque.
- **Dépôt GitHub public** : les anciens commits portent toujours l'email personnel de l'auteur, et l'identifiant du
  projet Supabase reste dans l'historique. Passer le dépôt en privé règle les deux ; la réécriture de l'historique
  (force-push) n'a pas été faite. Dans GitHub : Settings → Emails → « Keep my email addresses private » et « Block
  command line pushes that expose my email ».
- Les données quittent le Mali (Render, Supabase, Sentry, Brevo, Groq) : la loi malienne de protection des données
  personnelles (2013) impose des conditions pour les transferts à l'étranger ; à faire vérifier par un juriste.
- Le journal d'audit de l'inscription d'un élève note « nom (matricule) » (volontaire, comportement existant ; ce journal
  reste interne, il n'est envoyé à aucun service externe).

### Export Excel de la fiche annuelle

« Exporter en Excel » (`statistiques/fiche-annuelle.xlsx`, `statistiques/excel.py`) produit un classeur `.xlsx` au même
contenu que le CSV : les deux exports partent des mêmes lignes (`fiche.lignes_csv`), donc les rubriques réservées à
l'administration et la limite de cycle d'un directeur s'appliquent identiquement. Les chiffres sont de vrais nombres
(sommables dans Excel), les titres et en-têtes sont mis en forme, l'impression est en paysage sur une page de large. Un
nom d'école commençant par `=` reste du texte (jamais une formule). Chaque export est noté dans le journal d'audit
(`export_fiche_statistique_annuelle`, format `xlsx`). Le format reste celui d'une fiche de travail, pas celui du
questionnaire officiel de la CPS.

## État du projet : Phase 52 — Import Excel des élèves depuis l'écran

Jusqu'ici l'import en masse n'existait que sous forme de commande technique (`importer_eleves_excel`). Il est maintenant
dans l'application : **Élèves → Importer depuis Excel** (`scolarite/eleves/importer/`), pour le personnel qui peut inscrire
un élève (jamais un parent ni un élève).

1. **Télécharger le modèle** (`modele.xlsx`) : feuille « Élèves » (titres, listes déroulantes Sexe et Classe), feuille
   « Classes » (noms exacts des classes de l'année choisie, limitées au cycle d'un directeur de cycle) et « Mode d'emploi ».
2. **Envoyer le fichier** → un **aperçu** vérifie chaque ligne et signale les erreurs avec leur numéro de ligne Excel.
   Rien n'est créé à ce stade.
3. **Confirmer** → les élèves sont inscrits, avec la liste des matricules (affichée une seule fois, imprimable). Chaque
   élève reçoit ensuite son mot de passe provisoire depuis son dossier, comme pour une inscription isolée.

Colonnes obligatoires : prénom, nom, sexe, classe, email du parent 1 (même règle que l'inscription d'un élève). Facultatif :
date de naissance (jj/mm/aaaa), lieu et acte de naissance, matricule à reprendre, parent 2, noms et téléphones des parents.
Le handicap et la situation de déplacement ne s'importent pas (ils se renseignent dans l'espace développeur).

**Garanties** (`scolarite/test_import_eleves.py`, 46 tests) :
- **Mêmes règles que l'inscription isolée** : chaque ligne passe par `InscrireEleveForm` et la création par
  `scolarite.inscription_eleve.creer_eleve_inscrit`, fonction désormais partagée par les deux chemins.
- **Tout ou rien** : une seule erreur et aucun élève n'est créé ; une création qui échoue en cours de route annule les
  précédentes. La confirmation revalide les données (une classe supprimée ou un élève inscrit entre-temps font tout refuser).
- **Pas de doublons** : un fichier rechargé deux fois est refusé (« déjà inscrit dans cette classe ») ; la confirmation ne
  sert qu'une fois (jeton à usage unique en session : un rechargement ou un double clic ne recrée rien).
- **Cloisonnement** : uniquement les classes visibles de l'utilisateur (école, année, cycle) ; une classe d'une autre école
  ou d'un autre cycle est « introuvable » ; l'année d'une autre école est une page introuvable.
- **Fichier borné** : .xlsx de 2 Mo au plus, 500 élèves, 40 colonnes lues, 5000 lignes parcourues. Un nom commençant par
  `=` reste du texte. Le journal d'audit ne note que le nombre d'élèves et les classes, jamais de nom ni d'email, et les
  données du fichier ne sont gardées en session que le temps de l'aperçu : effacées à la confirmation, à l'annulation ou
  au prochain aperçu.

## État du projet : Phase 53 — Exports Excel, pages légales, facturation des abonnements, comptabilité

Livraison préparée avant le déploiement de la version 1.2.0. Chaque bloc a ses tests ; la suite complète est exécutée avant toute mise en ligne.

### Exports Excel des listes (`comptes/excel.py`, `pedagogie/exports.py`, `scolarite/views_exports.py`)
- **Liste d'une classe** (`classes/<id>/eleves.xlsx`) : matricule, nom, prénom, sexe, statut ; la date de naissance seulement pour
  l'administration qui a le droit de voir l'état civil (jamais pour un enseignant).
- **Relevé de notes** (`pedagogie/notes/classe/<id>/releve.xlsx`) : récapitulatif annuel, une feuille par trimestre (matières par
  ordre alphabétique, moyenne pondérée, rang de compétition, moyenne de la classe) et détail des notes. Mêmes calculs que le
  bulletin (test de comparaison). Un enseignant n'obtient que SES matières, sans moyenne générale ni rang.
- **Absences** (`pedagogie/absences/classe/<id>/export.xlsx?du=&au=`) : synthèse par élève et détail.
- Boutons dans « Classes », « Suivi des cours », « Mes classes » (enseignant) et « Élèves » (classe choisie). Une classe d'une autre
  école ou d'un autre cycle est introuvable ; chaque export est noté au journal d'audit (sans nom d'élève).

### Pages légales (`vitrine/`, `docs/dossier_apdp.md`)
Mentions légales, conditions d'utilisation et politique de confidentialité, publiques, liées depuis l'accueil, la connexion,
l'inscription et le pied de page de l'application. L'identité de l'éditeur vient de l'environnement (`EDITEUR_NOM`,
`EDITEUR_ADRESSE`, `EDITEUR_EMAIL`...) ; tant que `PAGES_LEGALES_VALIDEES` n'est pas à `True`, un bandeau « version provisoire,
en cours de validation juridique » s'affiche. Les prestataires facultatifs (Sentry, Groq) ne sont cités que s'ils sont configurés.
`docs/dossier_apdp.md` : registre des traitements, sous-traitants, mesures de sécurité et questions à poser à un juriste pour la
déclaration auprès de l'APDP (**ce n'est pas un avis juridique**).

### Facturation des abonnements (`etablissement/abonnements.py`, `espace_plateforme/`)
Réservée au propriétaire de la plateforme (menu Plateforme → Abonnements). Factures numérotées `ABO-AAAA-NNNN`, en FCFA : émission
(une période ne se facture qu'une fois), règlement (date, mode, référence), annulation avec motif (une facture payée ne s'annule
pas), PDF, export Excel, vue d'ensemble par école (à jour, facture à payer, en retard, expiré). Une école en retard n'est **pas**
désactivée automatiquement : le propriétaire décide. `ABONNEMENT_INSTRUCTIONS_PAIEMENT` s'imprime sur les factures.

### Comptabilité SYSCOHADA en partie double (`comptabilite/`)
Menu Finances → Comptabilité (module « Caisse » : direction, comptable ; le super administrateur consulte seulement).
- **Plan comptable** de base d'école (classes 1 à 8, niveau 3 chiffres + subdivisions de scolarité sur 5 chiffres), extensible.
- **Exercices** qui ne se chevauchent pas ; **écritures équilibrées**, jamais modifiées ni supprimées (une erreur se corrige par une
  contre-passation) ; numérotation par journal (CAI, BQ, OD, AN) ; cloisonnement strict par école.
- **Comptabilisation automatique de la caisse** (bouton « Mettre à jour la comptabilité ») : un paiement débite caisse, monnaie
  électronique ou banque selon son mode et crédite les droits d'inscription ou frais de scolarité ; un salaire payé est passé au net,
  ou avec le bulletin détaillé (brut, charges patronales, INPS, AMO, ITS). Corrections de montant ou de mode et annulations sont
  reprises par des écritures de régularisation (méthode de l'écart : attendu moins déjà passé), idempotent.
- **Saisie** : « Dépense ou recette » (deux lignes trouvées seules) et écriture libre à plusieurs lignes.
- **États** : journal, grand livre (solde cumulé), balance, compte de résultat (avec soldes intermédiaires), bilan simplifié ; export
  Excel de tous les états. Ces états sont des **aides à la gestion, à faire valider par un expert-comptable** : plan de base réduit,
  compte 551 (monnaie électronique) et subdivisions 706xx à confirmer, pas de TVA, ni de provisions, ni d'amortissements automatiques.
- **Clôture** : solde les comptes de charges et de produits dans le résultat (131 bénéfice, 139 perte) puis verrouille l'exercice
  (irréversible) ; **report à nouveau** des soldes de bilan dans l'exercice suivant.
- Le registre de caisse (Finances) ne montre toujours que la scolarité et les salaires ; la comptabilité est la référence complète.

### Indicateurs du rapport de la CPS dans la fiche annuelle (`statistiques/fiche.py`)
Le « Rapport de suivi des indicateurs du système éducatif 2017-2018 à 2021-2022 » de la CPS (mai 2022) est un rapport **national** :
il donne les définitions des indicateurs, pas le questionnaire de collecte. La fiche en reprend ce qu'un établissement peut calculer
seul, sans modèle ni migration nouveaux (elle apparaît dans la page, le CSV et l'Excel, avec les mêmes limites de cycle et de rôle) :
- **Indicateurs par cycle** : indice de parité F/G (0,97 = 97 filles pour 100 garçons, en plus de « filles pour 100 garçons »), élèves
  par classe (groupe pédagogique), **pourcentage de redoublants** garçons / filles / ensemble, enseignants, **part de femmes**,
  élèves par enseignant. Un enseignant qui intervient dans deux cycles est compté dans chacun, et une seule fois au total.
- **Promotion, redoublement et abandon** par niveau et par sexe (tableau 30 du rapport), d'après les décisions de fin d'année déjà
  enregistrées (admis, redouble, abandon). Les élèves transférés et ceux sans décision ne sont pas comptés, et leur nombre est
  affiché. Méthode propre à l'établissement : la CPS suit les effectifs d'une année à l'autre à l'échelle du pays.
- **Part de femmes parmi les enseignants**, calculée sur ceux dont le sexe est renseigné.

Ce que la fiche ne calcule pas : les taux bruts d'admission, de scolarisation et d'achèvement (TBA, TBS, TA, TBP), dont le
dénominateur est la population par âge du recensement ; les ratios élèves par salle **par cycle** (la fiche d'infrastructures est
saisie pour toute l'école) ; les diplômes des enseignants (IFM, SARPE, faculté) et les manuels par matière au fondamental 2, qui
demandent de nouveaux champs. À décider après avoir vu le questionnaire de collecte (« collecte rapide ») remis par l'académie.

### Corrections liées
- Les attributs `style=""` en ligne, bloqués par la politique de sécurité du site, laissaient visibles des blocs censés être cachés
  (bandeau hors connexion vide, « mois couverts » du paiement) : remplacés par l'attribut `hidden`, avec un test qui interdit leur retour.
- La saisie hors connexion des notes et des absences existait déjà (file locale, synchronisation au retour du réseau, nettoyage à la
  déconnexion) ; à essayer sur un téléphone réel après le déploiement.

## État du projet : Phase 54 — Messages aux familles (WhatsApp et SMS à envoyer à la main)

Page **Ressources → Messages aux familles** (`communication/diffusion.py`, `communication/views_diffusion.py`). Sans fournisseur
SMS ni clé : **le serveur n'envoie rien**. Chaque bouton ouvre WhatsApp (ou l'application de SMS) sur le téléphone ou l'ordinateur
de la personne connectée, avec le numéro de la famille et le message déjà écrits ; rien ne part tant qu'elle n'appuie pas sur
« Envoyer », et le message part de **son** numéro (pas d'accusé de réception, pas d'historique des envois).

- **Quatre types** : annonce à une classe (une ligne par numéro), convocation (une ligne par parent et par élève), élèves absents
  (à une date, aujourd'hui par défaut), relance de scolarité (solde non réglé, avec le montant).
- Le message se modifie ; les mots `{eleve}` `{prenom}` `{classe}` `{ecole}` `{date}` `{solde}` sont remplacés famille par famille
  (remplacement de ces seuls mots : un texte tapé ne peut rien évaluer). 500 caractères au plus.
- **Copier pour un groupe WhatsApp** : seulement pour une annonce à une seule classe, et le message n'a alors aucun nom d'élève
  ni montant (`{eleve}` devient « votre enfant ») : un message individuel n'existe que sous forme de liens individuels.
- **Qui** : les rôles qui voient déjà les coordonnées des familles (direction, directeurs de cycle, secrétariat, surveillant
  général ; la comptabilité pour la seule relance de scolarité), jamais un enseignant, un parent ou un élève. Un directeur de
  cycle ne voit que son cycle ; une classe d'une autre école, d'un autre cycle ou d'une année passée est « introuvable ».
- Les mots remplacés pour chaque famille (`{eleve}`, `{prenom}`, `{classe}`, `{ecole}`, `{date}`, `{solde}`) ne sont plus listés avec leur code : des **boutons** (« Nom de l'élève »,
  « Classe », « Montant dû »...) les ajoutent à l'endroit du curseur, avec les espaces nécessaires (`static/js/app.js`, `data-inserer-mot`) ; « Montant dû » n'apparaît que pour la relance
  de scolarité. Sans JavaScript, les boutons restent cachés. Le serveur n'a pas changé : il remplace les mêmes mots.
- Chaque préparation est notée au journal d'audit (type, classe, nombre de lignes), sans numéro ni nom.
- Les élèves sans numéro utilisable sont listés à part ; un numéro dont l'indicatif de pays est incertain est marqué « à vérifier ».

**Numéros** (`comptes/utils.py::numero_international`) : WhatsApp et les SMS exigent l'indicatif du pays. Avant, un numéro saisi en
local (76 00 00 00) donnait un lien refusé par WhatsApp, y compris sur « Suivi des paiements ». Désormais un numéro local reçoit
`INDICATIF_TELEPHONIQUE` (223 par défaut, `LONGUEUR_NUMERO_LOCAL` = 8) ; un numéro déjà international (`+221...`, `00221...`) n'est
jamais modifié ; tout autre numéro est gardé tel quel et signalé.

Hors de portée sans fournisseur payant : l'envoi automatique en masse, les accusés de réception et les messages envoyés d'un
numéro unique par le serveur (voir « À faire »).

### Correction liée
- Le motif de sortie d'un élève (abandon ou transfert) s'affichait comme deux champs de texte vides : les boutons radio recevaient
  la classe `form-control`. Corrigé dans le mélangeur commun des formulaires (`BootstrapFormMixin`), avec un test.

## État du projet : Phase 55 — Finition premium, montants lisibles, correction du dossier d'un élève

Trois volets, sans migration. Le premier est purement visuel (`static/css/toumai.css`, `static/js/app.js`, `templates/base.html`,
`templates/comptes/tableau_de_bord.html`) : tout reste conforme à la CSP (aucun `style=""` dans les gabarits ; le JavaScript
n'écrit que dans le CSSOM) et **optionnel** : sans JavaScript, la page est complète.

- **Mouvement** : transitions de page natives (View Transitions, ignorées par les navigateurs qui ne les connaissent pas), trait de
  chargement doré au clic sur un lien ou à l'envoi d'un formulaire, indicateur or sur le lien actif du menu latéral, apparition en cascade
  des sections du menu, ondulation au clic sur les boutons, apparition au défilement (uniquement ce qui est sous la ligne de
  flottaison ; tout est visible à l'impression), halo doré qui suit la souris sur l'accueil, la connexion et l'annuaire, bascule
  clair/sombre en fondu, compteurs animés des tableaux de bord.
- **Menu du compte** : l'avatar en haut à droite ouvre un menu (thème, mot de passe, email, codes de secours, 2FA, déconnexion) à la
  place des six boutons qui occupaient trois lignes sur téléphone. Un élément `<details>` : fonctionne sans JavaScript ; le script
  le referme au clic ailleurs et avec Échap.
- **Connexion** : anneau doré en pointillés qui tourne lentement derrière la carte, filet doré animé sur la carte.
- **Respect des préférences** : `prefers-reduced-motion` coupe toutes les animations (les compteurs affichent directement la valeur
  finale) ; les effets au survol ne s'appliquent qu'aux appareils avec souris (`hover: hover`).

### Corriger le dossier d'un élève (`scolarite/views.py::corriger_dossier_eleve`, route `eleves/<matricule>/corriger/`)
Avant, un nom, une date de naissance ou un numéro de parent saisi de travers à l'inscription ne se corrigeait nulle part (seuls le
lieu de naissance, le n° d'acte, le handicap et le déplacement l'étaient, dans l'Espace développeur).
- **Qui** : l'administration qui voit déjà l'état civil des élèves (`peut_corriger_dossier_eleve` : direction, secrétariat, directeurs
  de cycle pour leur cycle, super-administrateur, développeur), jamais un parent, l'élève, un enseignant, un comptable, le Censeur ni
  le Surveillant général. Un élève d'une autre école est « introuvable » (404).
- **Quoi** : prénom, nom, sexe, date de naissance (pas dans le futur), lieu et acte de naissance, handicap, déplacement ; et les
  **parents sans compte** (`ParentEnAttente`) : email, nom, prénom, téléphone, ajout (deux parents au plus, comptes liés compris) et
  retrait. Un email qui correspond à un compte parent de l'école le relie aussitôt ; un email de compte non-parent est refusé.
- **Jamais** : le matricule (il figure sur les documents remis), l'email technique de l'élève, les données d'un parent qui a un compte
  (ce sont les siennes), et le téléphone propre de l'élève (unique dans toute la base : le vérifier révélerait l'existence d'un
  numéro dans une autre école).
- Le journal d'audit (`correction_dossier_eleve`) note les **noms** des champs modifiés, jamais leurs valeurs.

### Numéros des parents sans compte
Le bouton WhatsApp de « Suivi des paiements » et la page « Messages aux familles » ne lisaient que les numéros des parents ayant un
compte et celui de l'élève : le numéro donné à l'inscription par un parent qui n'avait pas encore créé son compte (affiché sur la
fiche dans « En attente ») était ignoré. Ils l'utilisent maintenant (comptes liés d'abord, puis le plus ancien parent en attente ;
un numéro identique n'est pas répété).

### Montants (`comptes/templatetags/montants.py`)
- Filtre `montant` : `{{ paiement.montant|montant }}` affiche « 1 460 000 » (séparateur de milliers français, espace insécable) ;
  la devise suit `{{ etablissement.code_devise|default:"FCFA" }}`. Appliqué aux listes de paiements, caisse, salaires, contrats,
  journal SYSCOHADA, dossier élève, portail parent, statistiques financières et assistant ; le tableau de bord en fait autant côté vue.
- Correction : un compteur animé collait l'unité au chiffre (« 1 460 000FCFA ») ; l'unité est désormais un élément à part
  (`.stat-unite`) séparé du nombre par une espace. Les nombres décimaux (« 66,7 % ») ne sont pas animés.

## État du projet : Phase 56 — Supprimer ou anonymiser un élève

Avant, un élève ne pouvait pas être retiré : l'inscription, les paiements et les bulletins sont protégés à dessein (comptabilité,
statistiques, authenticité des documents remis). Réservé au **développeur de l'école** (`espace_developpeur/retrait_eleve.py`, route
`espace-developpeur/eleves/<matricule>/retirer/`, bouton « Supprimer / anonymiser » sur le dossier), pour un élève de son école
(autre école : 404), après avoir **retapé le matricule**. Le mode est décidé par le serveur, jamais par le formulaire :
- **Suppression définitive** : aucun historique (ni paiement, aide, note, absence, résultat d'examen, document remis, sortie, message).
  C'est le doublon ou l'inscription faite par erreur ; le compte, les inscriptions et la famille sans compte disparaissent.
- **Anonymisation** : il y a un historique. La personne est effacée, les chiffres restent. Effacés : prénom, nom, email, téléphone,
  matricule (devient `ANON-<n°>`), lieu et acte de naissance, jour de naissance, famille sans compte, lien avec les parents (leurs
  comptes ne sont pas touchés), messages parents-enseignants à son sujet, notifications qui le nomment, motifs d'absence et de sortie,
  justificatif de transfert (supprimé du disque). Gardés : sexe, année et mois de naissance, handicap, déplacement, inscriptions,
  notes, absences, paiements, résultats d'examen. Le compte est désactivé et sans mot de passe. Un test vérifie que les totaux de la
  fiche annuelle sont identiques avant et après.
- Le journal d'audit (`suppression_eleve`, `anonymisation_eleve`) note le numéro interne et des compteurs, jamais un nom, un matricule
  ou un numéro de téléphone.
- **Limites** : irréversible ; les sauvegardes de l'hébergeur gardent l'élève jusqu'à leur expiration ; l'année et le mois de naissance
  gardés pour les âges des statistiques sont, avec le sexe et la classe, des quasi-identifiants dans une très petite classe (voir
  `docs/dossier_apdp.md`, à valider avec un juriste). Les entrées plus anciennes du journal d'audit portent encore l'ancien matricule,
  qui ne mène plus à personne.

### Rang par trimestre sur le bulletin (`pedagogie/views.py::_reperes_classe`)
Le bulletin (écran et PDF) n'affichait que le rang général de l'année. Chaque bloc de trimestre porte maintenant « Rang du trimestre :
3ème sur 27 », à côté de la moyenne obtenue et des moyennes la plus forte et la plus faible. Même règle que le rang de l'année et que
la colonne « Rang » du relevé Excel (un test les compare) : élèves actuellement inscrits, moyenne pondérée par les coefficients, ex æquo
au même rang puis saut (1, 1, 3). Seuls les élèves qui ont des notes ce trimestre sont classés, mais l'effectif affiché est celui de la
classe, comme pour le rang de l'année. Pas de rang pour une inscription d'une année passée (personne n'y est plus « en cours »), comme
avant. Sur téléphone, l'en-tête d'une page (titre et actions) passe à la ligne au lieu de déborder.

## État du projet : Phase 57 — Entretien quotidien de la base (messages anciens, sessions expirées)

Pour que la base ne grossisse pas sans fin et garder moins de données personnelles (`comptes/entretien.py`) :
- **Messages** de la messagerie parent-enseignant et des fils d'équipe de plus de `DUREE_CONSERVATION_MESSAGES_JOURS` jours (**30** par
  défaut ; **0 = jamais effacés**), lus ou non. Irréversible. Les annonces, notifications, notes, paiements et dossiers ne sont pas touchés.
  Les pages de messagerie le rappellent (« Les messages sont effacés automatiquement après 30 jours »), via la balise
  `duree_conservation_messages_jours` (`communication/templatetags/conservation.py`) ; le rappel disparaît si la durée est à 0.
- **Sessions de connexion expirées** (table `django_session`) : Django ne les supprime jamais lui-même, chaque connexion en ajoute une.
  Une session expirée ne peut plus servir : personne n'est déconnecté.
- **Lancement** : le plan gratuit de Render n'a pas de cron, donc `EntretienQuotidienMiddleware` lance l'entretien à la première visite
  d'un utilisateur connecté, **au plus une fois par 24 h** (marqueur dans le cache : partagé avec Redis, par processus sinon, sans gravité
  car les purges sont sans effet une seconde fois). Il s'exécute après la réponse ; une panne est journalisée et jamais retentée avant
  le lendemain, sans jamais casser la page. `ENTRETIEN_AUTOMATIQUE=False` le coupe.
- **Commande** : `python manage.py entretien` (tâche planifiée sur un hébergement payant, ou à la main) ; `--simulation` compte sans
  effacer, `--jours N` change la durée pour cet appel.
- Le journal d'audit (`entretien_quotidien`) note des compteurs, jamais un texte de message ; rien n'est écrit quand il n'y a rien à effacer.
- **Pas fait volontairement** : les notifications et le journal d'audit ne sont pas purgés (le journal est une preuve ; les notifications
  n'ont pas été demandées). La durée est la même pour toutes les écoles (réglage de la plateforme, pas de l'école).

## État du projet : Phase 58 — Créer un fondateur ou un administrateur général sans terminal

Avant, ces deux rôles à accès total (hors matrice de permissions) ne pouvaient être créés que par la console technique (`manage.py shell`),
et la page `/admin/` n'a pas de champ « établissement ». Maintenant, le **propriétaire de la plateforme** (superutilisateur) les crée depuis
**Plateforme → Établissements → Comptes → Ajouter un compte de direction** (`espace_plateforme/views.py::creer_compte_direction`) :
- Rôle (fondateur ou administrateur général : seuls ces deux, jamais développeur, enseignant, etc.), prénom, nom, email (unique, minuscules).
- **Mot de passe provisoire généré** (12 caractères, `XXXX-XXXX-XXXX`) et affiché **une seule fois**, à remettre à la personne ; jamais conservé
  en clair, ni au journal d'audit, ni dans un message de session. Même mécanisme que les élèves : remplacé dès la première connexion
  (`doit_changer_mot_de_passe`), expire après 72 h, et la **double authentification est imposée** (`ROLES_2FA_OBLIGATOIRE`).
- **Nouveau mot de passe provisoire** (bouton sur la ligne du compte dans la liste des comptes de l'école) pour un compte de direction dont la
  fiche est perdue ou le mot de passe expiré ; il déverrouille aussi le compte. Refusé (404) pour tout autre rôle ou une autre école.
- Réservé au propriétaire : un développeur d'école, un fondateur ou toute autre personne est redirigé. Le développeur d'une école ne peut toujours
  pas s'attribuer ces rôles ni les donner (`espace_developpeur`). Journal d'audit : `creation_compte_direction` et
  `mot_de_passe_provisoire_direction` (email, rôle, école, expiration ; jamais le mot de passe).
- Le développeur d'une école reste créé avec l'école (« Créer un établissement »). La console reste possible.
- **Mot de passe provisoire expiré** : le message dit à qui s'adresser selon le rôle (« l'administrateur de la plateforme » pour un compte de
  direction, « le secrétariat de l'école » pour un élève), seulement une fois le mot de passe vérifié.
- **L'espace développeur n'est plus un module du fondateur ni de l'administrateur général** (`permissions_matrix.models.MODULES_RESERVES_AU_DEVELOPPEUR`) :
  il ne figure plus dans « Modules auxquels vous avez accès » et `PermissionMatrix.a_acces` / `modules_autorises` le refusent à ces deux rôles ;
  leur accès au reste de l'école ne change pas. Les pages de l'espace développeur leur étaient déjà refusées (`role_requis`). Les rôles
  de direction sont définis une seule fois (`comptes.roles.ROLES_DIRECTION_GENERALE`).

## État du projet : Phase 59 — Audit de fuites de données (octobre 2026)

**Méthode** : (1) historique git complet cherché pour des clés, jetons, mots de passe et URL de base ; (2) réglages de sécurité relus ; (3) les 155
routes classées par décorateur d'accès ; (4) une **matrice rôle x route** exécutée sur des données réelles de test (les 17 rôles, plus le parent, l'élève et
l'enseignant liés, sur les objets d'un élève précis : aucune route à paramètre ne répond 200 à un parent, un élève, un enseignant, un bibliothécaire ou un
membre du personnel qui n'est pas lié à l'élève ; l'espace développeur ne répond 200 qu'au développeur) ; (5) relecture ciblée : recherches d'objets par
identifiant, exports, PDF, journaux, assistant IA, mode hors connexion, connexion et inscription.

**Corrigé** (tests dans `comptes/test_durcissement_fuites.py`) :
1. **CSV : injection de formule** (`finances` journal de caisse, `statistiques` effectifs). Le neutralisateur `cellule_csv` n'existait que pour la fiche annuelle ;
   il est maintenant partagé (`comptes/excel.py`) et appliqué aux deux autres CSV. Les exports Excel l'avaient déjà.
2. **Synthèse des alertes (IA)** mise en cache **par rôle** : un enseignant pouvait lire la phrase calculée à partir des élèves d'un autre enseignant (des chiffres,
   jamais de noms). La clé de cache est désormais le contenu des alertes lui-même.
3. **Saisie de notes et d'absences** : deux messages d'erreur différents (« aucun élève » / « pas inscrit dans cette classe ») permettaient à tout enseignant de savoir
   quels matricules existent dans les autres écoles ; or le matricule sert d'identifiant de connexion à l'élève. Un seul message désormais.
4. **Connexion** : le message « compte verrouillé » n'apparaissait que pour un compte existant (quelques essais ratés suffisaient à le savoir, et à verrouiller
   le compte de quelqu'un). Le message est identique pour un identifiant inconnu, un mauvais mot de passe et un compte verrouillé ; le verrouillage, lui, tient.
5. **Journaux de l'hébergeur** (stdout) : la ligne d'audit contenait noms, emails, matricules et libellés (`cible`, `details`). Elle ne porte plus que l'action et des
   numéros internes ; le journal d'audit en base, visible de l'école seule, garde tout le détail.
6. **Durcissement** : un lien d'image `/media/../..` ne peut plus faire lire un fichier du serveur au générateur de PDF des bulletins (`_chemin_dans`) ;
   la politique CSP ajoute `form-action 'self'`.

**Vérifié, sans défaut** : aucun secret réel dans l'historique (seulement des exemples et des valeurs de test) ; DEBUG coupé par défaut, clé secrète obligatoire, cookies
sécurisés, HSTS ; fichiers servis par liens signés ; emails en masse en copie cachée ; aucune redirection ouverte, aucun SQL brut, aucun `eval`/`pickle`/`subprocess` ;
`|safe` seulement sur de l'aide statique ; données envoyées à l'IA externe (jamais de nom ni de matricule, seulement des chiffres) ; cache hors connexion effacé à la
déconnexion et à l'affichage de la page de connexion ; routes JSON de recherche cloisonnées par école ; pages publiques de l'accueil et de l'annuaire.

**Restes, à décider** (voir aussi « À faire ») :
- La clé TOTP (`totp_secret`) est stockée **en clair** en base : une fuite de la base permettrait de contourner la double authentification d'un compte dont le mot de
  passe serait aussi trouvé. La chiffrer demande une migration des données et lie les clés à `DJANGO_SECRET_KEY` (changer la clé obligerait à réactiver la 2FA de
  tous les comptes).
- Les pages publiques de vérification (QR des bulletins et attestations) renvoient le **matricule** de l'élève, qui sert aussi d'identifiant de connexion.
- Le formulaire public d'inscription dit si un email ou un téléphone existe déjà (limité à 10 essais par minute et par adresse).
- À l'inscription d'un élève, un matricule saisi à la main qui existe déjà dans une autre école est refusé : le matricule est unique dans toute la base.
- La CSP autorise les images `https:` de n'importe quelle origine (logos du stockage).
- Dépôt GitHub public : l'historique contient l'adresse email personnelle de l'auteur ; bucket de stockage à passer en privé (déjà prévu).

## État du projet : Phase 60 — Retrouver un élève par son nom (sans retenir le matricule)

Trois écrans exigeaient de connaître le matricule ; la barre de recherche, les paiements et les fiches de personnel acceptaient déjà le nom.
- **Saisie des notes et des absences** (`pedagogie/forms.py::EleveDeLaClasseMixin`) : le champ « Élève » accepte le nom ou le matricule. La liste des
  élèves de la classe est dans la page (`<datalist>`), donc la saisie par nom marche aussi hors connexion ; elle ne contient que les élèves
  actuellement inscrits dans CETTE classe, « NOM Prénom », avec le matricule seulement pour distinguer des homonymes (le matricule est aussi l'identifiant
  de connexion de l'élève). Le serveur accepte : le matricule seul, « NOM Prénom (matricule) », ou le nom complet dans un sens ou dans l'autre s'il est
  unique dans la classe ; deux homonymes demandent de choisir ; **jamais un bout de nom** (pour ne pas noter le mauvais élève). Un seul message pour
  « inconnu », « autre classe » et « autre école » (voir Phase 59).
- **Assistant** : recherche en direct (`assistant:rechercher_eleve_json`) parmi les seuls élèves que le rôle peut consulter
  (`scolarite.models.eleves_visibles_pour`, même règle que `eleve_visible_pour` en une requête : un enseignant ne trouve que ses classes, un directeur
  de cycle que son cycle) ; un nom tapé en entier ouvre le dossier sans rien choisir. Les messages d'erreur existants sont inchangés.
- **Toutes les recherches** (`scolarite/recherche.py`) ignorent les accents, les majuscules et l'ordre des mots : « aissata maiga » trouve « MAIGA Aïssata »
  (barre du haut, paiements, fiches de personnel, assistant). La recherche se fait en Python sur des listes déjà limitées à ce que la personne peut voir.
- Test navigateur de bout en bout : note et absence saisies par nom, recherche en direct, dossier ouvert.

## État du projet : Phase 61 — Second audit de fuites (octobre 2026)

**Méthode, en plus de la Phase 59** : (1) une **matrice « rôle x donnée »** : sur des données de test, pour chacun des 17 rôles plus six comptes liés ou non à l'élève,
quelles données sensibles de l'élève (état civil, téléphone et email des parents, motif d'absence, message, salaire, paiement...) apparaissent dans quelles pages, exports
Excel compris ; (2) une **matrice d'écriture** : pour chaque action en POST seul, quels rôles passent le contrôle d'accès (chaque appel annulé). Résultat : la politique
est respectée partout (état civil et contacts des parents : direction du bon cycle, secrétariat, super-administrateur, famille concernée ; messages : le parent et
l'enseignant concernés seulement ; aucun accès entre élèves, parents ou enseignants d'une même école ; actions d'administration réservées aux rôles prévus).
(3) Relecture ciblée : sessions, double authentification, changements d'email et de mot de passe, notifications, sauvegardes, supervision, dépendances, fichiers suivis par git,
chargements de fichiers (ZIP, Excel), emails.

**Corrigé** (tests dans `comptes/test_durcissement_fuites_2.py`) :
1. **Administration Django (`/admin/`)** : son formulaire de connexion répondait par une erreur 500 à un visiteur non connecté, et n'aurait de toute façon ni limité les essais
   ni demandé la double authentification : un mot de passe seul aurait ouvert toutes les données. Il renvoie maintenant vers la connexion de l'application
   (`config/urls.py::connexion_de_l_administration`) : verrouillage et double authentification s'appliquent.
2. **Double authentification** : les codes faux ne verrouillaient jamais le compte (seule la limite par adresse IP, 10 par minute), et quelqu'un qui connaît le mot de passe pouvait
   se reconnecter pour remettre le compteur à zéro. Les échecs comptent maintenant comme ceux du mot de passe (verrouillage après 5, message identique), et ne sont effacés
   qu'après un second facteur réussi.
3. **Changer l'email ou le mot de passe** : le mot de passe actuel pouvait être deviné sans limite depuis une session laissée ouverte. 5 essais par minute et par utilisateur.
4. **Notifications de messages** : chacune garde les 200 premiers caractères du message ; l'effacement des messages à 30 jours (Phase 57) ne les touchait pas. Elles partent avec le message.
5. **Lien de réinitialisation du mot de passe** : valable 1 jour (`PASSWORD_RESET_TIMEOUT`) au lieu de 3.
6. **Sauvegardes** (`manage.py sauvegarder_donnees`) : refusées si la destination est dans le dossier du projet (le dépôt est public) ; `.gitignore` ignore `sauvegarde_*/`, `sauvegardes/`, `backups/`, `*.dump`.

**Vérifié, sans défaut** : aucune adresse email, aucun numéro ni secret réel dans les fichiers suivis (seulement des valeurs fictives) ; supervision (Sentry) sans variables locales ni corps de
requête ni données personnelles ; politique de mots de passe (10 caractères, majuscule, chiffre, caractère spécial) ; changement d'email protégé par le mot de passe actuel et signalé à l'ancienne adresse ;
chargements ZIP et Excel bornés (taille, nombre de fichiers, extensions, signature) ; emails HTML échappés ; aucune exemption CSRF ; adresse IP des limites de fréquence prise derrière le proxy de confiance.

**Restes** (en plus de ceux de la Phase 59) :
- **Supabase** : si l'API de données (PostgREST) du projet est active et que les tables n'ont pas la sécurité par ligne (RLS), toute personne qui obtiendrait la clé publique du projet pourrait lire les
  tables. À vérifier dans le tableau de bord Supabase : désactiver l'API de données (l'application se connecte directement à la base) ou activer la RLS sur toutes les tables. Non vérifiable depuis le code.
- La file de saisie hors connexion (IndexedDB) garde les notes et absences non envoyées après une déconnexion, pour ne rien perdre : sur un ordinateur partagé, elle reste lisible jusqu'à l'envoi.
- « Mot de passe oublié » : limité par adresse IP, pas par compte ; un envoi massif vers des comptes existants pourrait épuiser le quota d'emails du jour.
- Le cache Redis sérialise avec pickle (réglage par défaut de django-redis) : le Redis doit rester privé (c'est le cas sur Render).

## État du projet : Phase 62 — Note de conduite (7ème à 12ème année)

La conduite n'est pas une matière (pas de professeur, pas de composition) mais elle entre dans la moyenne. Elle est donc gérée à part, avec une règle unique
(`pedagogie/conduite.py`) utilisée partout où une moyenne est calculée.
- **Quelles classes** : de la **7ème à la 12ème année** seulement (`pedagogie.models.classe_note_la_conduite`). Pas le primaire (1ère à 6ème année), ni le préscolaire,
  ni les classes sans niveau, ni les filières professionnelles. Pour une autre classe, la page de saisie renvoie vers la liste avec une explication.
- **Modèle** `NoteConduite` : élève, classe, trimestre, valeur de 0 à 20 (deux décimales), une seule note par élève, classe et trimestre. La validation vérifie que
  l'élève est bien inscrit dans cette classe, de la même école, et que la classe est concernée.
- **Coefficient** : réglage de l'école `Etablissement.coefficient_conduite` (1 par défaut ; 0 = la note s'affiche mais ne compte pas), modifiable dans les réglages de
  l'école de l'espace développeur.
- **Règle de calcul** : la conduite d'un trimestre ne compte que si l'élève a au moins une note de matière ce trimestre (pas de moyenne faite de la seule conduite).
  Elle s'ajoute au total pondéré avec son coefficient. Intégrée au **bulletin** (ligne « Conduite », écran et PDF), au **rang** et aux repères de la classe, au **relevé Excel**
  de la classe (colonne « Conduite (coef N) », moyenne et rang, lignes de détail ; vue complète seulement, pas la vue d'un enseignant), aux **alertes** de l'assistant
  (élèves à risque) et au compte des « notes » de l'historique d'un élève (anonymisation).
- **Saisie** (`pedagogie:saisir_conduite`, bouton « Conduite » dans la liste des classes) : une grille par classe et par trimestre, une case par élève (virgule ou point,
  case vide = pas de note ; vider une case efface la note). Tout est enregistré en une fois ou rien (une erreur n'enregistre rien et garde ce qui a été tapé). Année archivée :
  lecture seule. Journal d'audit `saisie_conduite` avec les seuls nombres (jamais de noms).
- **Qui peut saisir** (`ROLES_SAISIE_CONDUITE` + module Absences de la matrice) : les rôles à accès total, les directeurs d'études (D2 : 7ème à 9ème année ; DL, censeur
  et surveillant général : lycée) et le super-administrateur. Pas les enseignants, parents, élèves, secrétaire, comptable, RP ni D1. Un autre établissement : 404.
- Tests : `pedagogie/test_conduite.py` (50 tests, données fictives) ; vérification dans un vrai navigateur (liste des classes, saisie, erreur, bulletin, relevé Excel, primaire).
- **Primaire** : les notes de matière sont les mêmes pour toutes les classes (note de classe /20 + composition /40). Aucune règle propre au primaire n'est codée.

## État du projet : Phase 63 — Factures d'abonnement : email, rappels, WhatsApp et alertes

Avant, émettre une facture d'abonnement ne faisait que l'enregistrer : le propriétaire de la plateforme téléchargeait le PDF et l'envoyait lui-même. Maintenant
l'application peut l'envoyer (`etablissement/envoi_factures.py`). Toujours réservé au propriétaire ; l'école ne voit pas ses factures dans l'application.
- **Envoi** : case « Envoyer la facture par email à l'école » (cochée par défaut) sur l'écran d'émission, et bouton « Envoyer par email » / « Renvoyer par email » sur chaque
  facture émise de la liste. Le PDF part en pièce jointe, avec le numéro, la période, le montant, l'échéance et les instructions de paiement
  (`ABONNEMENT_INSTRUCTIONS_PAIEMENT`) ; l'expéditeur est `DEFAULT_FROM_EMAIL`, les réponses vont à `EDITEUR_EMAIL`. Un double clic n'envoie qu'un message (60 secondes).
  La facture est émise quoi qu'il arrive à l'email : un échec ou l'absence d'adresse donne un avertissement, et on réessaie depuis la liste. Seule une facture émise part
  (jamais une facture payée ou annulée).
- **Destinataires** : le nouveau champ `Etablissement.email_facturation` (réglages de l'école, modifiable par le propriétaire) ; à défaut, les comptes actifs de CETTE école
  de rôle fondateur ou administrateur général ; à défaut, son développeur. Plusieurs destinataires : en copie cachée. Jamais une adresse d'une autre école.
- **Rappels automatiques** : une facture émise, déjà envoyée par email et dont l'échéance est dépassée reçoit un rappel dès le lendemain de l'échéance, puis un par semaine,
  trois au plus ; jamais une facture payée ou annulée, ni une facture que la plateforme n'a pas envoyée par email (un rappel ne doit pas être le premier contact). Ils partent avec
  l'entretien quotidien (Phase 57 : première visite de la journée, ou `python manage.py entretien`, avec `--simulation` pour compter sans envoyer), car le plan gratuit de Render n'a pas de tâches
  planifiées. Un passage envoie dix rappels au plus et s'arrête au premier échec d'envoi (réessayé le lendemain : le compteur ne bouge qu'après un envoi réussi), pour ne jamais
  retenir longtemps la page d'un utilisateur ; une panne des rappels ne gêne pas les purges de l'entretien.
- **Suivi** : champs `envoyee_le`, `nombre_rappels` et `dernier_rappel_le` de la facture, affichés dans la liste. Journal d'audit `envoi_facture_abonnement` et `rappel_facture_abonnement` avec le
  nom de l'école et le NOMBRE de destinataires, jamais leurs adresses.
- **Bouton WhatsApp** sur chaque facture émise (non payée) de la liste : lien wa.me avec le message déjà écrit (la facture à payer avant telle date, ou un rappel avec le nombre de jours
  de retard ; montant, instructions de paiement, numéro de la facture). Rien n'est envoyé par le serveur : le propriétaire ouvre WhatsApp et clique lui-même sur Envoyer (WhatsApp ne permet pas de
  joindre le PDF par ce lien : le bouton « PDF » reste à côté). Numéro : le nouveau champ `Etablissement.telephone_facturation` (« numéro WhatsApp pour les factures », vérifié à la saisie : 8 chiffres au
  Mali ou format international) ; à défaut le numéro d'un compte actif de cette école (direction, puis développeur) ; sans numéro, le bouton « + N° WhatsApp » mène aux réglages de l'école.
  Les numéros de toute la page sont cherchés en une requête (`telephones_de_facturation`).
- **Alertes** (`etablissement.abonnements.alertes_factures`) : en haut de la page d'arrivée du propriétaire (liste des établissements), de la vue d'ensemble des abonnements et de la liste des
  factures : une alerte rouge « N factures d'abonnement en retard de paiement » (montant à encaisser, jours de retard de la plus ancienne, écoles concernées) et une alerte orange « N factures
  d'abonnement à payer » (prochaine échéance), chacune avec un lien vers la liste filtrée (nouveau filtre « À payer (dans les délais) »). Le jour même de l'échéance n'est pas un retard. Le propriétaire
  n'a pas de tableau de bord (il est renvoyé vers la liste des établissements) : c'est là que l'alerte se voit ; une école ne la voit jamais.
- Corrigé au passage : la « Date d'émission » du formulaire s'affichait vide dans le navigateur (format de date) ; le PDF est produit par une fonction commune (`pdf_de_la_facture`) pour la page et pour
  l'email ; les boutons de la liste des factures se rangent sur plusieurs lignes au lieu de se déformer.
- Tests : `espace_plateforme/test_envoi_factures.py` et `test_whatsapp_alertes_factures.py` (numéros, liens et messages WhatsApp, alertes, destinataires, contenu et pièce jointe, journal sans adresse, échecs, bouton, double clic, rôles, calendrier des rappels, entretien, commande) ;
  vérification dans un vrai navigateur (courrier affiché dans le journal du serveur de démonstration).
- **À régler sur Render** pour des factures complètes : `EDITEUR_NOM`, `EDITEUR_STATUT`, `EDITEUR_ADRESSE`, `EDITEUR_EMAIL`, `EDITEUR_TELEPHONE`, `EDITEUR_IMMATRICULATION` (RCCM, NIF) et
  `ABONNEMENT_INSTRUCTIONS_PAIEMENT` (numéro Orange Money, compte bancaire...). Vides, le PDF et l'email n'ont ni identité de l'éditeur ni moyen de payer.
- Limite connue : le quota d'emails du fournisseur SMTP (Brevo, 300 par jour en offre gratuite) est partagé avec les autres messages de la plateforme.

## État du projet : Phase 64 — Finition de l'interface (menu, téléphone, accessibilité, graphiques)

Audit de l'interface dans un vrai navigateur (19 pages du menu, ordinateur et téléphone, modes clair et sombre ; mesures de débordement, de tailles de texte, de zones tactiles et contrôle d'accessibilité axe-core), puis corrections.
- **Menu latéral** : une icône devant chaque lien (`comptes.context_processors.ICONES_DES_LIENS`, un test échoue si un nouveau lien n'en a pas) ; sections repliables (`<details>`, ouvertes par défaut, le choix est mémorisé dans le navigateur
  par `static/js/app.js`, la section de la page affichée reste ouverte) ; la marque et le pied restent fixes et seul le menu défile, avec une ombre en haut et en bas qui signale qu'il y a une suite ; pastille dorée du nombre de notifications non lues
  (« 99+ » au-delà) à la place de « Notifications (3) » ; filet de séparation en mode sombre ; animation d'apparition qui ne laisse plus d'état figé (les outils d'audit lisaient mal le fond marine).
- **Barre du haut** : cloche de notifications avec la même pastille (utile sur téléphone, où le menu est caché) ; icône SVG pour le bouton du menu mobile, avec son état annoncé (`aria-expanded`).
- **Barre latérale réellement fixe** : `overflow-x: hidden` sur la page en faisait un conteneur de défilement et empêchait `position: sticky` de tenir la barre en haut sur les longues pages ; remplacé par `overflow-x: clip` (repli `hidden` pour les très anciens navigateurs).
- **Téléphone** : les listes (élèves, classes, matières, paiements, caisse, salaires, personnel, factures, établissements, bulletin, messages aux familles, recherche, suivi des cours...) s'affichent en **cartes** « libellé : valeur » sous 720 px
  (tableaux marqués `table-cartes`, les libellés viennent des en-têtes de colonne, ajoutés par `app.js` ; sur ordinateur rien ne change). Les tableaux de chiffres (comptabilité, statistiques, grilles de saisie) restent des tableaux et défilent sur le côté.
  Zones à toucher : liens du menu 44 px, boutons 40 px, champs 44 px, liens isolés 40 px. Le nombre de classes avait disparu de l'en-tête de la page Classes depuis la Phase 62 (`classes.count` sur une liste) : corrigé.
- **Lisibilité** : aucun texte sous 12 px (la base fait 15 px : 0,8 rem) ; couleurs discrètes remontées au seuil AA (4,5:1) : gris discret `--ink-300` et or foncé `--gold-600` en mode clair, gris du mode sombre ; bulles de confirmation en bas à droite (elles cachaient les boutons de l'en-tête de page).
- **Mot de passe** : bouton « œil » pour afficher ou masquer (tous les champs mot de passe, ajouté par `app.js`, `data-sans-oeil` pour l'exclure).
- **Accessibilité** : filtres et interrupteurs sans nom (`aria-label`), en-têtes de colonne vides remplacés par « Actions » (masqué à l'écran), zone « contenu principal » sur l'accueil public, la connexion et la page d'attente, ordre des titres du dossier élève. Résultat de l'audit axe-core sur les 19 pages : **aucune violation**.
- Tests : `comptes/test_interface.py` (icônes de tous les rôles, pastille et cloche, sections, zones principales, filtres, cartes, aucun en-tête vide dans les gabarits, aucune taille sous 12 px, contrastes AA des couleurs) ; comportements JavaScript (œil, repli mémorisé, clavier, cartes, zones tactiles) vérifiés dans un vrai navigateur.
- **Graphiques** (`comptes/graphiques.py`, balises `{% graphique_anneau %}`, `{% graphique_barres %}`, `{% graphique_colonnes %}`) : figures SVG dessinées côté serveur, sans bibliothèque ni style en ligne (la CSP les interdit), couleurs par classes CSS
  (`g-bleu`, `g-or`, `g-vert`, `g-rouge`, `g-gris`) donc thèmes clair et sombre ; nombres d'attributs SVG formatés en texte avec un point (le gabarit écrirait une virgule) ; chaque figure a un libellé accessible et ses valeurs en clair.
  Statistiques : anneau garçons / filles et barres des effectifs par classe (vue d'ensemble), anneau garçons / filles (page d'une classe), anneau admis / redoublants dès que des décisions sont saisies, barres de l'encaissé par échéance (finances) ;
  sous-menu des statistiques regroupé (« Par classe », « Rapports ») avec la page courante marquée (`aria-current`).
- **Tableau de bord** : encaissements des 6 derniers mois (colonnes ; mois en cours en or ; `encaissements_par_mois` : paiements supprimés et autres écoles jamais comptés) et effectifs par classe (barres ; les 10 plus grandes classes au-delà de 10), avec **les mêmes droits que les chiffres** (Finances pour les encaissements,
  module Élèves pour les effectifs, classes visibles du rôle : directeur de cycle = son cycle). Raccourcis de tâches (« Inscrire un élève », « Enregistrer un paiement », « Publier une annonce », selon le rôle) à la place des doublons du menu ; carte « Comptes à valider »
  (cliquable) pour les rôles qui valident les comptes ; la liste des modules a disparu (le message « Aucun module ne vous est encore attribué » reste quand il n'y en a aucun).
- Tests : `comptes/test_graphiques.py` (formes, anneau, barres, colonnes, mois, passage d'année, droits par rôle, pas de style en ligne, pages de statistiques).
- Restes : les tableaux de comptabilité et de statistiques détaillés (fiche annuelle) ne passent pas en cartes et n'ont pas de graphique ; les enseignants n'ont pas de graphique (leur matrice n'ouvre ni Finances ni Élèves).

## État du projet : Phase 65 — Arabe (bouton de langue, écriture de droite à gauche, écrans courants)

Des écoles du Mali enseignent uniquement en arabe : l'application peut s'afficher en **arabe** ou en **français** (langue par défaut). Première étape : écrans courants ; le reste de l'application reste en français tant qu'il n'est pas traduit (aucune page ne casse).
- **Bouton de langue** (`templates/partials/bouton_langue.html`) en haut de chaque page : application (barre du haut), connexion, accueil public, annuaire, pages légales, page « aucun établissement ». Il propose toujours l'**autre** langue, écrite dans cette langue (« العربية » / « Français »), jamais traduite (`translate="no"`).
  Il envoie un formulaire (POST, protection CSRF) à `/comptes/langue/` (`comptes.views.changer_langue`) ; 400 si la langue est inconnue ; le retour (`next`) ne sort jamais du site (`url_has_allowed_host_and_scheme`) ; la route reste ouverte pendant l'activation 2FA et le changement de mot de passe obligatoires.
- **Quelle langue ?** (`comptes.langue.langue_de_la_requete`) : choix enregistré sur le **compte** (`Utilisateur.langue`) → sinon **cookie** `yelenova_langue` (l'ancien `nexora_langue` est encore lu ; un an, `HttpOnly`, `SameSite=Lax` ; visiteurs non connectés) → sinon **langue par défaut de l'école** (`Etablissement.langue_par_defaut`, réglée par le développeur dans les paramètres de l'école ; pour un visiteur, l'école choisie sur la page d'accueil) → sinon français.
- **Traduction** : plutôt que de modifier 124 gabarits, un intergiciel (`comptes.langue.TraductionMiddleware`) traduit la **page HTML produite** quand la langue n'est pas le français (`comptes/traduction.py`). Le catalogue est le fichier `comptes/traductions/ar.csv` (colonnes `francais`, `arabe`, `note`), environ 870 textes :
  menu, connexion, tableau de bord, élèves, classes, matières, notes, bulletin à l'écran, absences, conduite, paiements, caisse, salaires, messages, bibliothèque, assistant, statistiques, comptabilité de base, accueil public, tous les libellés de listes de choix et les textes du JavaScript.
  Règles : texte exact (espaces et apostrophes normalisés) ; motifs avec valeurs `{0}` (« {0} élèves inscrits ») ; une phrase en plusieurs morceaux (« · », « — », « / ») est traduite morceau par morceau ; `translate="no"` protège un texte ; scripts, styles, zones de saisie et commentaires ne sont jamais touchés ;
  attributs `placeholder`, `aria-label`, `title`, `alt` et boutons traduits ; **les données (noms, matricules, annonces, noms de classes) ne sont jamais traduites** ; PDF, JSON et réponses en flux ne sont pas modifiés (règles de la première étape, remplacées par la phase 67 : noms, chiffres, PDF et exports passent en arabe). Ce que le catalogue ne connaît pas reste en français.
- **De droite à gauche** : `<html lang dir>` suit la langue ; en arabe, Bootstrap RTL (`static/css/bootstrap.rtl.min.css`, 5.3.3) remplace Bootstrap et `static/css/toumai-rtl.css` renverse les positions propres au thème (menu à droite, flèches, graphiques, cartes sur téléphone) ; police **Cairo** (sous-ensemble arabe, `static/fonts/cairo-variable-arabic.woff2`, hébergée avec l'application : la CSP n'autorise aucune police externe).
  Les textes du JavaScript passent par `t()` (`static/js/app.js`) avec le dictionnaire `{% textes_js %}` (bloc JSON de la page).
- **Sens de lecture des données** : de droite à gauche, un texte latin qui mélange lettres, chiffres et parenthèses (« 10ème CM1 (2026-2027) », « Awa EXEMPLE », un numéro « +223 ... ») est réordonné par le navigateur (« ème CM1 (2026-2027) 10 »). Les données ne se traduisent pas, donc le moteur les **isole** : balise `<bdi>` autour de chaque texte non traduit qui contient des lettres latines ou un numéro précédé de « + » (la ponctuation de bord reste dehors), et autour des valeurs insérées dans une phrase traduite (« مرحبًا، Mamadou »). Là où une balise est interdite (liste déroulante `<option>`, `<title>`, texte de graphique SVG, attributs), ce sont les isolats Unicode invisibles FSI / PDI. Les nombres ordinaires (« 1 460 000 », « 26001-1 », dates) se lisent déjà bien et ne sont pas touchés ; en français rien n'est ajouté.
- **Faire relire les traductions** : `python manage.py exporter_traductions --sortie traductions_arabe.xlsx` écrit un tableau Excel (Français | Arabe | Note) ; la personne qui relit corrige la colonne « Arabe » (les valeurs `{0}` doivent rester) ;
  `python manage.py importer_traductions traductions_arabe.xlsx --simulation` contrôle et compte les changements (refuse tout le fichier si une ligne est vide, perd une valeur `{0}` ou n'a aucune lettre arabe), puis la même commande sans `--simulation` met à jour le catalogue. Le fichier Excel est ignoré par Git. La colonne « Note » signale les termes à valider
  (classe = القسم, trimestre = الفصل, bulletin = كشف النقاط, matricule = رقم التسجيل…).
  `python manage.py audit_traduction /scolarite/eleves/ /finances/paiements/ --email compte@ecole.ml` ouvre les pages indiquées en français avec ce compte et liste les textes sans traduction (`--a-traduire fichier.csv` pour obtenir un tableau à compléter).
- Tests : `comptes/test_traduction.py` (moteur : motifs, segments, attributs, protections ; catalogue : valeurs `{0}` cohérentes, tous les libellés de choix et textes JavaScript traduits) et `comptes/test_langue.py` (ordre de choix, cookie invalide ignoré, bouton sur chaque type de page, changement de langue en POST seulement,
  retour sûr, CSRF, 2FA et mot de passe provisoire, école par défaut sans effet sur les autres écoles, `lang`/`dir`, PDF et JSON intacts, **aucune phrase française** restante sur les écrans essentiels de la direction, de l'enseignant, du parent, de l'élève et du public, **menu entièrement traduit pour chacun des rôles**).
- Restes de la première étape (traités à la phase 67 : PDF, courriels, messages aux familles, écrans rares) ; les termes marqués « à valider » attendent la relecture.

## État du projet : Phase 66 — Bouton « Installer l'application »

L'application était déjà installable (manifeste, service worker, icônes : `config/views.py`, `static/js/sw.js`), mais seulement par le menu du navigateur, que peu de gens trouvent. Un bouton visible l'ouvre maintenant.
- **Où** : barre du haut de l'application (à côté du bouton de langue ; sur téléphone, l'icône seule avec une zone tactile de 40 px), page de connexion et accueil public (`templates/partials/bouton_installer.html`, une seule fois par page).
- **Quand il apparaît** (`static/js/app.js`, bloc « phase 66 ») : le bouton est caché au départ. Chrome, Edge et Samsung Internet (Android et ordinateur) envoient `beforeinstallprompt` quand l'installation est possible : l'évènement est gardé et le clic ouvre la fenêtre d'installation du navigateur, puis le bouton disparaît.
  Sur iPhone et iPad (Safari n'envoie pas cet évènement), le bouton est montré et ouvre une aide en trois gestes (Partager, « Sur l'écran d'accueil », Ajouter). Il n'apparaît **jamais** quand l'application est déjà ouverte en mode installé (`display-mode: standalone`, `navigator.standalone`), ni sur un navigateur qui ne sait pas installer (Firefox ordinateur…) ; il disparaît à l'évènement `appinstalled`.
- **Manifeste** : `id` fixe (`/`) et `lang` / `dir` qui suivent la langue choisie (français ou arabe, de droite à gauche).
- Arabe : le bouton et l'aide sont dans le catalogue de traduction (`تثبيت التطبيق`, `إضافة إلى الشاشة الرئيسية`).
- Tests : `comptes/test_installation.py` (bouton caché au départ et présent une fois sur chaque type de page, aide, arabe, script, manifeste, service worker) ; comportement vérifié dans un vrai navigateur (Chrome avec évènement simulé, iPhone, application déjà installée, arabe, mode sombre, téléphone : aucun débordement, aucune erreur de console).
- Limite : la fenêtre d'installation elle-même est celle du navigateur (texte, icône et nom viennent du manifeste) ; l'application ne peut pas la modifier. Une fois refusée, Chrome ne la reproposera que plus tard.

## État du projet : Phase 67 — Arabe pur (noms, chiffres, PDF, exports, courriels)

Les écoles arabophones veulent qu'en cliquant sur « العربية » **tout** soit arabe, y compris les noms des élèves et les chiffres. Cette phase remplace les règles « les données ne sont jamais traduites » et « PDF, JSON ne sont pas modifiés » de la phase 65.
- **Noms** (`comptes/arabisation.py`, `comptes/transcription.py`, `comptes/traductions/noms_ar.csv`) : en arabe, chaque nom de personne (élève, parent, personnel, candidat, parent en attente), de classe et d'école est écrit en lettres arabes. Ordre de priorité : écriture **enregistrée** par l'école (`Utilisateur.prenom_ar` / `nom_ar`, `Classe.nom_ar`, `Etablissement.nom_ar` / `devise_ar`) → **proposition automatique** (dictionnaire de prénoms et noms maliens, sinon transcription lettre à lettre).
  La proposition n'est qu'une aide : l'école la relit et la corrige sur l'écran **« Noms en arabe »** (`/comptes/noms-en-arabe/`, direction ; le secrétariat pour élèves et parents), qui affiche le nom d'origine en lettres latines à côté de la case arabe (c'est la seule exception voulue de la page). Ce qui est enregistré passe avant la proposition partout.
  Les noms sont repérés dans le texte de la page par un index par école, gardé en cache et invalidé par des signaux (`comptes/signaux.py`) quand un nom change ; le propriétaire de la plateforme voit toutes les écoles. Un texte qui est déjà une phrase du catalogue reste traduit comme tel (« Plan comptable » même si une personne s'appelle « Comptable »).
  À la saisie, `valider_ecriture_arabe` refuse les lettres latines dans les champs « en arabe » ; l'inscription d'un élève et l'import Excel acceptent les colonnes arabes (modèle de fichier généré en arabe).
- **Chiffres** : en arabe, les nombres, dates, heures, montants (« 1 460 000 فرنك سيفا »), pourcentages (٪), références (REC, CAI, BQ, OD, AN, SAL, ABO), mois et jours sont écrits en chiffres arabes-indiens (٠١٢٣…) avec la virgule arabe (٫). Les chiffres tapés par l'utilisateur sont ramenés à l'écriture occidentale avant d'atteindre l'application (`ChiffresOccidentauxMiddleware`, mots de passe et jeton CSRF exclus), si bien que les formulaires, les recherches et la base ne voient que des chiffres ordinaires.
- **Moteur de traduction** (`comptes/traduction.py`) : phrases à trous classées par précision, phrase par phrase pour un message de plusieurs phrases, texte exact du catalogue prioritaire sur le découpage aux séparateurs, mot entre parenthèses traduit à part (« handicap visuel (1). »), virgule française → « ، », profondeur limitée. Catalogue : environ 2 760 textes.
- **PDF** (`comptes/pdf.py`) : bulletins, reçus, attestations, factures en arabe avec la police **Amiri** (licence OFL, `static/fonts/pdf/`), de droite à gauche, lettres jointes (arabic-reshaper et python-bidi, déjà exigés par xhtml2pdf). Les lignes sont réordonnées après la coupure de ligne pour que l'ordre des mots reste correct.
- **Excel et CSV** (`comptes/excel.py`, `arabiser_classeur`) : feuilles de droite à gauche, textes et noms traduits, nombres laissés **numériques** (un CSV ou une cellule en chiffres arabes ne se calcule plus dans Excel ; l'affichage des chiffres suit alors les réglages d'Excel).
- **Courriels, WhatsApp, SMS, relances d'impayés, assistant** : écrits dans la langue du **destinataire** (`comptes.langue.langue_du_compte`, `texte_en_langue`) ; l'assistant reçoit la consigne de répondre en arabe pur (`consigne_de_langue`).
- **Restent volontairement en lettres latines** : adresses de courriel et liens, bouton « Français », secrets à recopier (clé 2FA, codes de secours, mot de passe provisoire), identifiants (code d'école `ML-BKO-٠٠٤٢`, noms de fichier, numéros de vérification) et le texte libre saisi par le personnel (titre d'une annonce, intitulé d'une opération comptable…), qu'aucune machine ne peut traduire fidèlement.
- À faire relire par un arabophone : termes comptables et juridiques, transcriptions des noms, formules des courriels.
- Tests : `comptes/test_arabe_pur.py` (aucune lettre latine ni chiffre occidental sur les pages essentielles de chaque rôle), `test_moteur_arabe.py`, `test_arabisation.py`, `test_noms_arabes.py`, `test_pdf_arabe.py`, `test_exports_arabes.py`, `test_courriels_arabes.py`, `assistant/test_langue_ia.py`, et ceux de la phase 65 mis à jour.

## État du projet : Phase 68 — Vie scolaire complète (comparaison avec le cahier des charges « Toumaï Edu School »)

Les fonctions qui manquaient par rapport au cahier des charges de référence ont été ajoutées, chacune avec ses droits par rôle, son journal d'audit, sa traduction en arabe pur et ses tests. Aucune ne change le comportement des écrans existants tant qu'elle n'est pas utilisée.
- **Courriel de reçu** (`finances/courriels.py`) : à chaque paiement enregistré, les parents liés (comptes actifs avec adresse) reçoivent le reçu et le reste à payer, dans leur langue. Un courriel qui échoue ne bloque jamais le paiement.
- **Liste de classe en CSV et en PDF** (`scolarite/views_exports.py`) : mêmes droits que l'Excel, noms protégés contre les formules, logo lisible dans les PDF (`scolarite/documents.py: logo_en_donnees`).
- **Dossier élève complet** : père, mère, adresse, personne à prévenir, école d'origine, photo (`comptes.Utilisateur`, migration 0021). La photo n'a jamais d'adresse publique : `scolarite:photo_eleve` vérifie les droits ; elle est refaite à l'enregistrement (`scolarite/photos.py` : vraie image seulement, redressée, 480 px, JPEG sans métadonnées, protection contre les images « bombes »). Import d'une archive ZIP par classe (120 photos au plus, reconnues par matricule ou par nom). L'anonymisation efface ces champs et la photo.
- **Cartes d'élève** (`scolarite/cartes.py`, `views_cartes.py`, gabarit `cartes_eleves_pdf.html`) : chaque carte est une pièce d'un seul tenant, **recto à gauche et verso à droite**, à découper, plier sur le trait en pointillé et plastifier ; quatre pièces par feuille A4. Recto : logo, nom et ville de l'école, photo, « CARTE D'ÉLÈVE » et l'année en pastille, nom et prénom, né(e) le … à …, classe, matricule, fonction, signature et nom du signataire de l'école (s'ils sont renseignés), devise dans la bande du bas. Verso : QR code, **code court** de douze signes (`XXXX-XXXX-XXXX`) et adresse de la page de vérification, personne à prévenir en cas d'urgence, règle d'usage, nom et matricule, validité. Une classe entière ou un seul élève ; secrétariat et direction. La carte en arabe est retournée toute seule (recto à droite) ; le code et l'adresse restent en lettres latines (`translate="no"`) pour pouvoir être recopiés. Un nom très long s'écrit plus petit au lieu de passer sur deux lignes. **Piège de mise en page** : xhtml2pdf réduit tout le contenu d'une case quand il dépasse la hauteur qu'on lui a imposée ; la carte fait 59 mm et les cases du corps ont des hauteurs fixes (36 mm au recto, 41 mm au verso) qu'il ne faut pas réduire sans regarder le PDF.
- **Vérifier un document** (`scolarite/views_verification.py`, route publique `/verifier/`, `vitrine:verifier`) : on y tape le code court de la carte, ou on y arrive en scannant son QR code (`?code=`). Elle affiche seulement ce que le document montre déjà (type, élève, matricule, classe, école, date), limitée à 20 essais par minute et par adresse ; un code inconnu, mal tapé ou désactivé répond pareil. Le code est stocké dans `VerificationDocument.code` (migration `scolarite.0027`, additive) : les cartes déjà imprimées en reçoivent un à la prochaine impression, sans changer leur QR code, et l'ancienne adresse (`scolarite:verifier_document`, JSON) fonctionne toujours. Tests : `scolarite/test_cartes_eleves.py`, `test_verification_publique.py`.
- **Documents officiels** (`scolarite/documents.py`, `views_documents.py`) : certificat de scolarité, attestation de fréquentation, certificat de radiation, numérotés `003/SIGLE/CERT/2026` (compteur verrouillé par école, type et année ; un même document garde son numéro et son QR). Version française, arabe ou les deux (deux pages dans un seul PDF) ; signature et cachet imprimés au choix s'ils sont téléversés. Nouveaux réglages de l'école : sigle, nom et fonction du signataire, signature, cachet (`etablissement.Etablissement`, migration 0020).
- **Retards et discipline** (`pedagogie/discipline.py`, `views_discipline.py`) : registre des retards, avertissements, blâmes, convocations et exclusions ; courriel et notification aux parents pour toute mesure et, pour les retards, au **troisième du mois exactement**. Historique lisible par l'élève et ses parents ; suppression réservée à la vie scolaire et à la direction ; le motif est effacé à l'anonymisation.
- **Calendrier scolaire** (`scolarite/views_calendrier.py`) : rentrée, vacances, jours fériés, examens, réunions ; dates « réservées au personnel » invisibles des parents et des élèves ; prochaines dates sur le tableau de bord et le portail parent. Géré par le secrétariat et la direction.
- **Cahier de textes et devoirs** (`pedagogie/cahier.py`, `views_cahier.py`) : séances et travail à faire notés par l'enseignant affecté (ou la direction) ; les familles voient les devoirs à rendre et les deux dernières semaines (page « Devoirs » et portail parent).
- **Suivi des programmes** (`pedagogie/views_programmes.py`) : chapitres avec avancement en %, date prévue, difficultés ; vue d'ensemble de la direction, **retards en tête**.
- **Clôture des notes** (`pedagogie/clotures.py`) : fondateur, administrateur général et développeur clôturent ou rouvrent un trimestre ; plus aucune note de matière ni de conduite n'y entre. Une année archivée est toujours clôturée.
- **Bulletins d'une classe en un seul PDF** (`pedagogie.views.exporter_bulletins_classe_pdf`) : un bulletin par page, mêmes calculs que le bulletin individuel, 150 élèves au plus. Le serveur web attend maintenant 120 secondes au lieu de 30 (`Procfile`, `render.yaml` : `--timeout 120`).
- **Frais annexes et arriérés** (`finances/annexes.py`, `views_annexes.py`) : frais (tenue, examen, transport...) pour une classe ou toute l'école, ajoutés au dû mais jamais réduits par les aides ; réglés avec la tranche « Frais annexe » (compte 70608). Un arriéré est le reste dû d'une année passée, calculé avec la classe de l'époque ; il se règle depuis la page « Arriérés » (paiement pré-rempli). **Nouveau garde-fou** dans le formulaire de paiement : un montant au-dessus du reste dû est refusé (sans effet si l'école n'a défini aucun échéancier ; le code métier garde sa souplesse).
- **Anciens élèves et réintégration** (`scolarite/anciens.py`) : liste de ceux qui ont quitté l'école (transfert, abandon) ; réintégration dans une classe (l'inscription de la même année est rouverte, sinon une nouvelle est créée ; la décision de sortie est effacée, le journal en garde la trace).
- **Pré-inscription en ligne** (`tests_niveau/preinscription.py`, `views_publiques.py`) : la direction ouvre une campagne et partage son lien secret ; la famille dépose sa demande (formulaire public protégé : jeton CSRF, limite de débit, piège à robots, doublons ignorés, plafond de 3 000 demandes, validation stricte) ; le secrétariat est notifié, convoque au test ou refuse, puis décide après le test : la famille reçoit un courriel à chaque étape, dans sa langue. Une demande n'inscrit personne.
- Tests : `scolarite/test_dossier_complet.py`, `test_cartes_eleves.py`, `test_documents_officiels.py`, `test_calendrier.py`, `test_anciens_eleves.py`, `test_exports_csv_pdf.py` ; `pedagogie/test_discipline.py`, `test_clotures_bulletins.py`, `test_cahier_programmes.py` ; `finances/test_courriel_paiement.py`, `test_frais_annexes_arrieres.py` ; `tests_niveau/test_preinscription.py`.
- Restes volontaires : paiement en ligne (Orange Money, Moov Money), envoi automatique de SMS et de WhatsApp, appareil de confiance pour la double authentification, assistance et annonces de la plateforme depuis la console, sauvegarde d'une école depuis l'écran (elle reste en ligne de commande), bibliothèque de prêts papier, fil d'Ariane et guides d'aide.

## État du projet : Phase 69 — Cantine et vente de tenues

Deux nouveaux modules, chacun avec ses droits, son journal d'audit, sa traduction en arabe pur et ses tests. Les deux alimentent la Caisse et la comptabilité comme un paiement de scolarité.
- **Cantine** (app `cantine`, module de permissions **Cantine**) : la gère le *gérant de la cantine*, c'est-à-dire un compte au rôle « Personnel » auquel le développeur accorde le module Cantine dans la matrice de permissions de l'école (par défaut aucun rôle ne l'a, sauf le super administrateur ; fondateur et administrateur général y ont accès comme à tout). Formules (tarif **au mois** : tout mois commencé est dû ; ou **au repas** : chaque repas servi à l'appel est dû), inscription des élèves classe par classe, appel du jour (refaire l'appel corrige le précédent, jamais de doublon), fiche d'un élève (repas, paiements, reste), paiement avec reçu PDF numéroté `CAN-2026-000001`, fin d'inscription (rien ne se supprime). Le dû se calcule sans requête par élève (`cantine/services.py: avec_soldes`). Seule la direction annule un paiement (conservé, marqué « annulé », sa ligne de Caisse aussi). Les parents et les élèves voient seulement leur propre suivi (`cantine:mon_suivi`, lien du menu affiché seulement si une formule est active).
- **Vente de tenues** (`finances/tenues.py`, `views_tenues.py`, module Finances) : réservée au comptable et à la direction. Articles (une tenue dans une taille) avec prix, stock et seuil d'alerte ; le stock ne change **que** par un arrivage, une vente, l'annulation d'une vente ou une correction d'inventaire (motif obligatoire), chacun laissant une ligne d'historique ; il ne descend jamais sous zéro (contrainte en base). Vente à un élève (recherche par nom) ou à une personne extérieure, plusieurs articles à la fois, tout ou rien, reçu numéroté `TEN-2026-000001`, prix du jour conservé. Seule la direction annule une vente (les articles reviennent en stock).
- **Caisse et comptabilité** : un mouvement de Caisse a maintenant exactement une origine parmi quatre (paiement, salaire, vente de tenues, paiement de cantine ; contrainte `mouvement_caisse_origine_unique`). Comptabilisation : vente de tenues = débit de la trésorerie (selon le mode) et crédit **701** ; cantine = crédit **70608**. Le journal de caisse simple sépare maintenant ces trois produits.
- **Retrait d'un élève** (`espace_developpeur/retrait_eleve.py`) : un élève inscrit à la cantine ou acheteur de tenues a un historique (anonymisation, pas suppression) ; l'anonymisation remplace aussi son nom dans les libellés de la Caisse et de la comptabilité (corrige un oubli de la phase 56 pour les paiements de scolarité).
- Arabe : préfixes de reçus `CAN` (مطعم) et `TEN` (زي) ; 145 textes ajoutés au catalogue ; termes à faire valider par un arabophone : المطعم المدرسي (cantine), الأزياء المدرسية (tenues).
- Tests : `cantine/test_cantine.py`, `test_cantine_arabe.py` ; `finances/test_tenues.py`, `test_tenues_arabe.py` ; `espace_developpeur/test_retrait_eleve.py`.
- Migrations additives : `permissions_matrix.0012_module_cantine` (une ligne de matrice par rôle et par école, refusée sauf super administrateur), `cantine.0001`, `finances.0010` (articles, ventes, mouvements de stock, deux nouvelles origines de Caisse).

## État du projet : Phase 70 — Bulletin mensuel du premier cycle (1ère à 6ème année)

Le premier cycle ne se note pas par trimestre : une composition par mois, chaque discipline sur 10, toutes de coefficient 1, un seul enseignant (le maître de la classe) qui remplit tout. Le modèle vient d'un vrai bulletin de classe ; il vit à côté du bulletin trimestriel sans le toucher.
- **Données** (`pedagogie.models`, migration 0011) : `DisciplineMensuelle` (les disciplines de la classe, activables/désactivables), `NoteMensuelle` (0 à 10 en base, une note par élève, discipline et mois), `ObservationMensuelle` (mot du maître). Réglage de l'école : `moyenne_passage_premier_cycle` (5 sur 10 par défaut ; `etablissement.0021`, modifiable dans les paramètres de l'école).
- **Calculs** (`pedagogie/mensuel.py`) : moyenne du mois = total ÷ nombre de disciplines notées (une case vide n'entre ni dans le total ni dans la moyenne), arrondie à 2 décimales ; rang « à égalité » (1, 2, 2, 4) parmi les élèves qui ont une moyenne ; effectif = élèves inscrits en cours ; plus forte et plus faible moyenne de la classe ; appréciation = l'échelle à six niveaux du bulletin, appliquée à la moyenne ramenée sur 20. **Moyenne de l'année = moyenne des moyennes mensuelles** (les mois où l'élève a une moyenne) ; il passe à partir de la moyenne de passage de l'école.
- **Écrans** (`pedagogie/views_mensuel.py`, menu Pédagogie > « Bulletins mensuels », `pedagogie:mensuel_*`) : liste des classes du premier cycle ; grille de saisie du mois (élèves en lignes, disciplines en colonnes, virgule ou point acceptés, mois précédent/suivant) ; résultats du mois ; synthèse de l'année avec « passe / ne passe pas » ; gestion des disciplines (liste habituelle de quinze disciplines, ajout, renommage, désactivation, reprise depuis une autre classe ; une discipline qui a des notes ne se supprime pas) ; page de l'élève, visible de l'élève et de ses parents ; bulletin d'un élève en PDF et bulletins de toute la classe en un PDF (un par page).
- **Droits** : seul le maître de la classe (un enseignant affecté à la classe), la direction générale, le super administrateur et le directeur du premier cycle saisissent ; le responsable pédagogique consulte sans modifier. Une classe d'une autre école ou d'un autre cycle répond 404, comme une classe qui n'existe pas. La saisie respecte la clôture des notes (mois d'un trimestre clôturé : lecture seule) et l'année archivée. L'enregistrement des notes est tout ou rien (une note fausse annule l'ensemble) ; la saisie, la gestion des disciplines et les PDF laissent une ligne au journal d'audit.
- **Arabe pur** : 122 textes ajoutés au catalogue ; le bulletin PDF arabe tient sur une page.
- Tests : `pedagogie/test_bulletin_mensuel.py` (calculs sur le bulletin de la photo, droits, isolation, clôture, PDF), `test_bulletin_mensuel_arabe.py` (aucune lettre latine hors textes saisis).
- **Laissé de côté volontairement** : en 6ème année, l'école fait aussi un bulletin trimestriel ; son rôle dans la décision de passage n'est pas encore défini (à rechercher avec l'équipe) et n'entre donc pas dans la décision calculée ici. Il n'existe pas d'examen de fin de 6ème année dans ce modèle.
- Migrations additives : `etablissement.0021_bulletin_mensuel_premier_cycle`, `pedagogie.0011_bulletin_mensuel_premier_cycle`.
- **Correction liée : mot de passe refusé à l'inscription** (`comptes/forms.py::InscriptionForm`). Une inscription avec un mot de passe qui ne respecte pas les règles (10 caractères, une majuscule, un chiffre, un caractère spécial, ni trop courant ni tout en chiffres) rechargeait la page **sans aucun message** : l'erreur était rattachée au formulaire entier, que le gabarit n'affichait pas. Elle est maintenant écrite sous le champ, toutes les règles manquantes d'un coup, en français et en arabe ; les règles sont aussi écrites avant la saisie. Le contrôle de ressemblance de Django (mot de passe presque identique à l'email, au prénom ou au nom) est actif sur tous les écrans (`comptes/validators.py::SimilitudeMotDePasseValidator`, `AUTH_PASSWORD_VALIDATORS`) ; il ne refuse que les quasi-copies (l'email, ou un long prénom suivi d'un chiffre). Test : `comptes/test_mot_de_passe_messages.py`.

## État du projet : Phase 71 — Yelenova (changement de nom et de logo)

La plateforme s'appelle **Yelenova** (nom choisi par le propriétaire le 18 octobre 2026) ; son logo est un livre ouvert devant un soleil qui porte la carte du Mali, vert et or, avec le slogan « La lumière du savoir ».
- **Nom** : `NOM_PLATEFORME = "Yelenova"`, `NOM_COMMERCIAL = "YELENOVA"` (sans « Éducation » : le logo porte seulement le nom), description de l'accueil à jour. Partout où le nom était écrit en dur (fichiers Excel, courriels en arabe `comptes/mail.py`, double authentification, application installable, pages légales, tests) il est remplacé. Le slogan devient « La lumière du savoir » (celui du logo ; en arabe : نور المعرفة, à faire relire), à la place de « Toute votre école. Une seule vision. ».
- **Arabe** : يلينوفا (`comptes/arabisation.py::LEXIQUE`, `comptes/mail.py`, trois entrées du catalogue). **Écriture à faire valider par un arabophone**, comme les autres termes.
- **Noms internes** : le cookie de langue devient `yelenova_langue` ; l'ancien `nexora_langue` est encore lu (un visiteur qui avait choisi l'arabe n'a rien à refaire) et effacé au prochain changement de langue (`comptes.langues.ANCIEN_NOM_COOKIE_LANGUE`). La clé de mémoire du menu replié (`static/js/app.js`) change aussi : le menu se redéploie une fois.
- **Images** : voir « Logo » dans la phase 49. Les anciens fichiers `logo-nexora.png` sont supprimés.
- **Non modifié** : l'historique des migrations, le nom du service Render et la palette de l'interface (bleu nuit et or).
- Tests : `vitrine/tests.py` (`IdentiteYelenovaTests`), `comptes/test_langue.py` (cookie de l'ancien nom).

## État du projet : Phase 72 — Effectifs par cycle pour le propriétaire de la plateforme

Le propriétaire facture chaque cycle à son prix : il lui faut savoir, pour chaque école, combien il y a d'élèves et de personnel dans chaque cycle.
- **Page** `/plateforme/effectifs/` (menu « Effectifs par cycle » et bouton sur la liste des établissements), réservée au propriétaire (`est_proprietaire_plateforme`) ; **export Excel** `/plateforme/effectifs/export.xlsx` (une ligne par école et par cycle, journalisé). Des nombres seulement : aucun nom, aucun courriel, aucun matricule.
- **Calcul** (`espace_plateforme/effectifs.py`) pour l'année scolaire active de chaque école : *élèves* = inscriptions « en cours » par cycle de la classe ; *enseignants* = enseignants actifs affectés à au moins une classe du cycle (un enseignant de deux cycles est compté dans chacun) ; *direction du cycle* = directeur du 1er cycle, du 2ème cycle ; pour le lycée, directeur du lycée, censeur et surveillant général ; *sans cycle* = tout autre membre du personnel actif (fondateur, secrétariat, comptabilité, bibliothèque, enseignant sans classe cette année). **Les parents d'élèves ne sont pas comptés** ; les comptes inactifs ou en attente de validation non plus. Une vue d'ensemble additionne toutes les écoles.
- **Hors formule** : un cycle où l'école a des comptes alors que sa formule ne le couvre pas est signalé (badge sur la ligne et sur l'école), pour le régulariser ou le facturer en plus. Une école sans année scolaire active l'explique au lieu de compter zéro en silence.
- **Tarifs par cycle** (`TarifCycle`, migration `etablissement/0022_tarif_cycle`, additive) : pour chaque école et chaque cycle, le propriétaire choisit **soit** « Par élève et par an » (montant × élèves inscrits en cours), **soit** « Forfait par an » (le montant, une seule fois, si le cycle est *ouvert* : couvert par la formule de l'école ou déjà habité). Un cycle sans tarif n'entre pas dans le calcul. Page `/plateforme/<école>/tarifs/` (bouton « Tarifs » sur chaque école), un seul tarif par école et par cycle, enregistrement journalisé (`tarifs_cycle`).
- **Montant annuel estimé** : affiché par cycle, par école et pour toute la plateforme, et ajouté à l'export Excel (mode, tarif, montant). Le bouton « Émettre la facture » ouvre le formulaire d'émission déjà rempli (école, montant, période = année scolaire, libellé) ; **tout reste modifiable** et la facture n'est jamais créée sans que le propriétaire la valide. Les enseignants et la direction sont comptés pour information : les deux modes de facturation ne portent que sur les élèves ou sur le forfait.
- Tests : `espace_plateforme/test_effectifs.py` (calculs, parents exclus, comptes inactifs, année archivée, formule, droits, aucun nom, export, arabe pur) et `espace_plateforme/test_tarifs_cycle.py` (montants par élève et au forfait, cycle fermé, tarifs propres à chaque école, formulaire, droits, facture préremplie, export, arabe pur).

## État du projet : Phase 73 — Signature et cachet des cartes d'élève, cycle par cycle

Chaque cycle a son directeur : la signature et le cachet imprimés sur une carte d'élève sont ceux du cycle de sa classe.
- **Saisie** : page `/espace-developpeur/etablissement/signataires/` (bouton « Signatures et cachets par cycle » sur « Identité de l'établissement »), réservée au développeur de l'école. Un bloc par cycle de la formule de l'école (et par cycle qui a déjà un signataire) : nom, fonction, signature, cachet (images de 2 Mo au plus, contrôlées comme celles de l'école). Tout ou rien à l'enregistrement ; un cycle dont tout est vidé est retiré ; l'action est journalisée (`signataires_cycle`, les cycles modifiés, jamais les images). Nouveau modèle `SignataireCycle` (un par école et par cycle), migration `etablissement/0023_signataire_cycle` additive.
- **Règle de repli** (`scolarite.cartes.signataires_par_cycle`) : si l'école n'a rien saisi pour un cycle (nom, fonction, signature), la carte reprend le signataire de l'école entière ; sinon celui du cycle, **sans mélange** (la signature d'un directeur n'accompagne jamais le nom d'un autre). Le cachet est celui du cycle, sinon celui de l'école.
- **Carte** : le cachet est nouveau sur la carte (elle n'imprimait que la signature) ; il est recadré dans un carré transparent (`cachet_en_donnees`) et se place à droite du texte du signataire, dans une petite table, parce qu'une image plus haute que la signature faisait rétrécir les textes de la carte (limite connue de xhtml2pdf). Une carte sans cachet est inchangée.
- Tests : `scolarite/test_signataires_cycle.py` (repli, cycles, cachet carré, cartes de deux cycles, page de saisie, droits, tout ou rien, arabe pur).

## État du projet : Phase 74 — Chacun ne voit que ce qui le concerne, même dans sa propre école

Constat : les audits précédents contrôlaient les écoles entre elles et les adresses interdites ; ils ne voyaient pas ce qui déborde **à l'intérieur d'une école** dans les listes, les menus déroulants, les recherches et les chiffres, dès qu'un module est accordé à un rôle (la matrice de permissions est réglable par chaque école). Cause principale : `classes_visibles_pour` ne cloisonnait que les directeurs de cycle ; un enseignant, un parent ou un élève recevait toutes les classes de l'école.
- **Règle centrale** (`scolarite.models.classes_visibles_pour`) : un enseignant voit les classes où il est affecté, un parent celles de ses enfants, un élève les siennes ; directeurs de cycle, censeur et surveillant général gardent leur cycle ; les autres rôles, toute l'école. Elle gouverne la liste des classes et des élèves, la recherche (barre du haut), les exports, l'emploi du temps, les annonces, etc.
- **Annonces** (`communication.visibilite.annonces_visibles_pour`) : un enseignant ne pouvait pas seulement lire mais **publier** pour n'importe quelle classe (courriel aux familles compris) ; il ne cible plus que ses classes et ne lit que les annonces de toute l'école, de ses classes et les siennes. Parents, élèves et directeurs de cycle : même règle.
- **Tableau de bord et assistant** : un élève ne voit plus l'effectif de l'école ni les absences de toute l'école (uniquement les siennes), ni les effectifs par classe ; un enseignant ne voit que les chiffres de ses classes ; l'assistant ne donne à un élève ou à un parent aucun chiffre de l'école ; le total encaissé (et son graphique) est réservé à la comptabilité et à la direction ; le nombre d'enseignants d'un directeur de cycle ne compte que ceux de son cycle.
- **Affectation des enseignants** : un enseignant à qui l'école donne le module Classes ne voit que ses collègues de ses classes (pas tous les enseignants de l'école), un parent ou un élève n'en voit aucun.
- **Garde-fous permanents** : `comptes/test_isolation_complete.py` (nouveau test : tous les modules des élèves et des classes sont cochés pour l'enseignant, le parent, l'élève et le directeur de cycle, et aucune page ne doit montrer un nom, un matricule ou une classe hors de leur périmètre ; il ajoute une 3ème classe d'un autre cycle et un camarade) et `scolarite/test_perimetre_roles.py` (classes visibles par rôle, recherche, annonces, tableau de bord, assistant, affectation). Règle pour la suite : toute nouvelle liste, recherche ou menu déroulant passe par `classes_visibles_pour` / `eleves_visibles_pour` et se teste pour ces quatre profils.

## État du projet : Phase 75 — Accueil quand les écoles sont nombreuses

Constat : l'accueil listait toutes les écoles dans une colonne, sans recherche, et l'école choisie n'était retenue que le temps de la session (30 minutes) : à chaque déconnexion, chacun devait retrouver son école dans la liste.
- **École retenue un an** (`vitrine.ecole_memorisee`, cookie `yelenova_ecole` : le nom court de l'école, rien sur la personne, aucun droit) : posé quand on choisit une école et, par `vitrine.middleware.MemoriserEcoleMiddleware`, après chaque connexion (une seule fois par école grâce à un repère dans la session). Au retour, l'accueil propose « Continuer vers [école] » en un clic, avec « Ce n'est pas mon école » (`/ecole/changer/`) ; une école suspendue ou inconnue est ignorée. L'école d'un propriétaire de la plateforme (sans école) n'est pas retenue.
- **Recherche** : champ sur l'accueil (nom, sigle, commune, cercle, région ; sans accents ni majuscules, mots dans n'importe quel ordre), qui répond en direct (`/ecole/rechercher.json`, 2 lettres au moins, 10 écoles au plus, 60 demandes par minute et par adresse IP) et marche aussi sans JavaScript (`?q=`). Seules les écoles actives de l'annuaire public sont proposées.
- **Seuil de la liste** (`vitrine.views.SEUIL_LISTE_COMPLETE`, 30) : jusqu'à 30 écoles, la liste complète reste affichée sous la recherche ; au-delà, seulement la recherche, et personne ne parcourt la liste des clients de la plateforme. Une école peut aussi se retirer de l'annuaire (« visible dans l'annuaire »), son lien direct continue de marcher. La recherche en direct limite et plafonne les réponses, elle n'est pas une protection absolue contre quelqu'un qui testerait beaucoup de mots.
- **Lien et code QR de l'école** : sur « Identité de l'établissement » (développeur de l'école), le lien direct `/e/<nom-court>/` et son code QR (`/espace-developpeur/etablissement/qr-connexion.png`, à télécharger) pour les lettres aux parents, les affiches et les groupes WhatsApp ; ses utilisateurs n'ont plus à passer par la liste.
- Tests : `vitrine/test_ecoles_nombreuses.py` (liste ou recherche selon le seuil, accents, plafond, écoles cachées ou suspendues, cookie, limite par IP, arabe pur, lien et code QR, droits).

## État du projet : Phase 76 — Paiement Mobile Money déclaré par le parent

Le parent a payé par Orange Money ou Moov Money : il le déclare dans la plateforme, la comptabilité vérifie dans son propre compte Mobile Money puis valide. Première étape, sans branchement avec un opérateur (qui demande un accord commercial) ; elle prépare la suivante.
- **Parent** (`/finances/paiements/declarer/`, menu « Déclarer un paiement », rôle parent seulement) : il choisit l'un de **ses** enfants (inscription en cours), l'opérateur, le montant, le **numéro de transaction** du SMS (normalisé : majuscules, sans espaces ni tirets ; 6 caractères au moins), la date (ni future ni de plus d'un an), le numéro utilisé et, facultatif, une capture d'écran (image, 2 Mo). Il voit « comment payer » (champ `instructions_mobile_money` de l'école, à renseigner par son développeur dans « Identité de l'établissement ») et l'état de ses déclarations : à valider, validé (avec le reçu), refusé (avec le motif). 20 déclarations par heure au plus.
- **Un numéro de transaction ne se déclare qu'une fois** par opérateur (contrainte en base, sauf s'il a été refusé).
- **Comptabilité et direction** (`/finances/paiements/declares/`, menu « Paiements déclarés », indicateur « Paiements à valider » du tableau de bord, notification à chaque nouvelle déclaration) : **Valider** ouvre « Enregistrer un paiement » déjà rempli (élève, montant, Mobile Money) ; l'enregistrement crée le paiement, son reçu numéroté et sa ligne de caisse comme n'importe quel paiement, relie la déclaration au reçu et prévient le parent (notification et courriel du reçu). **Refuser** demande un motif, que le parent lit. Une déclaration traitée ne donne jamais un second paiement ; seul le même élève peut être validé.
- Rien n'entre en caisse avant la validation. Journal d'audit : `declaration_paiement`, `validation_paiement_declare`, `refus_paiement_declare`. Données : table `PaiementDeclare` (migration `finances/0011`), champ `Etablissement.instructions_mobile_money` (migration `etablissement/0024`), additives.
- Tests : `finances/test_declarations.py` (déclaration, doublons, données invalides, droits, limite par heure, capture, validation, refus, autre école, tableau de bord, menu, arabe pur).

## État du projet : Phase 77 — Notifications sur le téléphone (Web Push)

Chaque notification interne (`comptes.Notification`) part aussi, quelques secondes plus tard, sur les téléphones que la personne a activés, même application fermée. Les messages arrivent chiffrés de bout en bout (norme Web Push) : ni Google, ni Apple, ni Mozilla ne les lisent.
- **Mise en service (une fois, par vous)** : `python manage.py generer_cles_push` donne une paire de clés ; mettre dans l'environnement de Render `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` (**secret**) et `VAPID_ADMIN_EMAIL` (courriel de contact). **Sans ces clés, la fonction reste éteinte** : aucun bouton, aucun envoi, aucune erreur. Changer de clés oblige chacun à réactiver ses notifications. Nouvelle dépendance : `pywebpush` (`requirements.txt`).
- **Pour chacun** : page « Notifications », carte « Notifications sur ce téléphone » (Activer / Désactiver) ; le navigateur demande la permission. Sur iPhone, il faut d'abord installer l'application sur l'écran d'accueil. L'appareil quitte le compte à la déconnexion (ordinateur ou téléphone partagé) et passe à la personne suivante si elle se connecte sur le même appareil (une adresse d'envoi n'appartient qu'à un compte). `static/js/push.js`, `static/js/sw.js` (réception et clic), `comptes/views_push.py` (`/comptes/push/abonner/`, `/comptes/push/desabonner/`, 60 par heure), table `AbonnementPush` (migration `comptes/0022`, additive).
- **Envoi** (`comptes/push.py`) : dans un fil à part (la page n'attend pas), texte court (160 caractères), adresse toujours de notre site ; un appareil qui répond « disparu » (404, 410) est retiré, et après 5 échecs de suite aussi. Toute notification créée y passe : discipline, messagerie, relances d'impayés, paiement validé ou refusé, annonces...
- **Nouvelles notifications automatiques** : **absence signalée** → les parents de l'élève (pas pour une absence saisie plus de 3 jours après, ni pour une mise à jour) ; **annonce publiée** → toute l'école ou la classe visée et ses parents, jamais l'auteur ; **paiement enregistré** → les parents, avec le reçu et le reste à payer (pour une déclaration validée, « Paiement validé » à la place).
- Les textes des notifications restent dans la langue où ils ont été écrits (comme les autres messages enregistrés). SMS automatiques : à faire, il faut choisir un fournisseur payant.
- Tests : `comptes/test_push.py` (éteint sans clés, abonnement et appareil partagé, envoi, appareils perdus, chiffrement réel sans réseau, génération des clés, absence, annonce, paiement, arabe).

## État du projet : Phase 78 — Finitions de l'interface et nouvelle page d'accueil

Contrôle complet de l'interface dans un vrai navigateur (84 pages vues par le fondateur et le propriétaire, 95 pages vues par les neuf autres profils, ordinateur, téléphone, mode sombre) : aucune erreur d'accessibilité (WCAG A et AA), aucun débordement. Les défauts trouvés sont corrigés.
- **Menus d'actions** (`<details class="menu-actions">`, `static/js/app.js`, `static/css/toumai.css`) : une ou deux actions principales restent visibles sur chaque ligne, le reste se range dans un menu « Actions » ou « Plus » (les actions de suppression en dernier, en rouge, après un filet). Pages concernées : Classes (jusqu'à 9 boutons et une colonne « Excel » illisible avant), Paiements (la suppression n'est plus rouge sur chaque ligne), Salaires, Dossier de l'élève (« Imprimer » et « Plus »), Mes classes de l'enseignant (11 boutons avant), Liste des élèves (exports de la classe), Établissements et Factures du propriétaire. Le panneau quitte le tableau pendant qu'il est ouvert (sinon la carte le coupe et les lignes suivantes passent par-dessus), se pose à l'écran, s'ouvre au-dessus s'il n'y a pas de place en dessous, se referme au clic ailleurs, avec Échap, au défilement et après le choix ; un seul menu est ouvert à la fois. Sans JavaScript il s'ouvre quand même, à sa place naturelle.
- **Montants et références** : « 25 000 FCFA » et « REC-2026-000044 » ne se coupent plus en deux lignes (`.montant-val`, `.reference-val`).
- **Téléphone** : cases à cocher et interrupteurs agrandis (appel de la cantine, des absences, réglages), liens de bas de carte et de notifications avec une vraie zone à toucher ; portail parent : boutons en grille régulière, classe sur sa propre ligne.
- **Tableau de bord** : chiffres clés dans une grille qui connaît leur nombre (5 cartes = 3 + 2, plus de carte orpheline) ; mois sans encaissement du graphique = simple ligne ; l'élève voit trois raccourcis (bulletin, absences, devoirs) ; liste de classes cachée quand il n'y a rien à choisir.
- **Menu latéral** : champ « Chercher une page du menu » dès 12 liens ; les résultats remplacent les rubriques sans changer leur état replié ou déplié mémorisé.
- **Page d'accueil publique** : le vrai logo (emblème vert et or) à la place de la toque ; bande défilante remplacée par cinq atouts (français et arabe, Mobile Money, alertes sur le téléphone, saisie sans réseau, chacun ne voit que ce qui le concerne) ; neuf cartes (français et arabe, cantine et vie scolaire, téléphone et sans réseau en plus ; alertes et Mobile Money mis à jour) ; « L'application en images » avec trois captures (`static/img/vitrine/*.webp`, faites avec les données fictives de démonstration) ; aperçu de partage (`og:image`) pour WhatsApp. Les captures existent aussi en arabe (`*-ar.webp`, choisies selon la langue de la page).
- **Contact public** : bloc « Demander une démonstration » (WhatsApp, courriel) affiché **seulement** si les variables `CONTACT_WHATSAPP` (format international, par exemple `223XXXXXXXX`) et/ou `CONTACT_COURRIEL` sont renseignées dans l'environnement (Render) ; jamais écrites dans ce dépôt public. Le message prérempli est en français ou en arabe selon la langue de la page.
- **Arabe** : un mot courant d'un champ libre (« Tuteur **de** Kadidia » dans la personne à prévenir, nom du père ou de la mère, signataire) n'est plus pris pour un nom de personne par l'index des noms (`comptes/arabisation.py`, `MOTS_JAMAIS_DES_NOMS`) : il cassait la traduction de toutes les phrases contenant « de » (par exemple « 1 élève(s) en risque de redoublement » sur le tableau de bord).
- **Montants du propriétaire** : séparateur des milliers sur les factures, les abonnements, le règlement d'une facture et la validation d'une déclaration (« 600 000 » au lieu de « 600000 »).
- Tests : `comptes/test_interface_menus.py`. Arabe : 33 nouveaux textes dans `comptes/traductions/ar.csv` (relecture par un arabophone toujours à faire).

## État du projet : Phase 79 — Conseils de classe

Menu **Pédagogie → Conseils de classe** (direction : fondateur, administrateur général, développeur, super administrateur, directeurs de cycle, censeur, responsable pédagogique ; les directeurs de cycle et le censeur ne voient que les classes de leur cycle ; **un enseignant, un parent, un élève, le surveillant général, le secrétariat et la comptabilité n'y ont pas accès** : le tableau montre la moyenne générale de tous les élèves).
- **Le tableau d'un conseil** (une classe, un trimestre) : rang, moyenne, conduite (dès la 7ème année), absences non justifiées, avertissements et blâmes du registre de discipline, moyenne de l'année au 3ème trimestre. Les moyennes et les rangs viennent **des mêmes fonctions que le bulletin** (`pedagogie/views.py`) : un élève a au conseil la moyenne et le rang de son bulletin.
- **Ce que le conseil note** : distinction (tableau d'honneur, encouragements, félicitations), sanction (avertissement ou blâme, pour le travail ou la conduite), au 3ème trimestre la décision de passage (admis, redouble), une observation par élève et des observations générales, la date. Les **seuils** des distinctions (12, 14, 16 par défaut) et du passage (10) se règlent sur le conseil et sont repris au conseil suivant de l'école ; les moyennes ne font que **suggérer** (bouton « Appliquer les suggestions ») : c'est le conseil qui décide. Aucun texte officiel malien précis n'ayant été trouvé pour ces seuils, ils restent réglables et à confirmer avec une école.
- **Valider** verrouille le conseil (tableau en lecture seule) ; seuls le fondateur, l'administrateur général et le développeur le **rouvrent**. Un champ absent d'un envoi ne change jamais une décision (seul un champ envoyé vide l'efface). Une alerte rappelle de clôturer les notes du trimestre avant de valider.
- **Documents PDF** (français et arabe) : procès-verbal (« projet, non validé » tant que le conseil n'est pas validé ; signatures du président et du chef d'établissement à la main) et tableau d'honneur.
- **Sur le bulletin** : distinction, sanction, décision de passage et observation du conseil apparaissent, pour chaque trimestre, sur le bulletin de l'élève concerné (page et PDF) **seulement quand le conseil est validé**.
- **Passage de classe** : les décisions du conseil validé du 3ème trimestre sont déjà choisies pour chaque élève ; la direction les vérifie et peut les changer (le passage reste l'acte qui déplace les élèves).
- **Boutons à plusieurs actions** : la page reconnaît l'action par le **nom** du bouton cliqué, jamais par sa valeur, parce que la page arabe traduit la valeur des boutons d'envoi (un bouton « valider » aurait envoyé un mot arabe inconnu du serveur). `static/js/app.js` garde le bouton cliqué dans un champ caché avant de désactiver les boutons, et un message de confirmation propre à chaque bouton (`data-confirmer-bouton`, traduit par le moteur d'arabe).
- Base de données : migration additive `pedagogie/0012_conseil_de_classe` (tables `ConseilDeClasse` et `DecisionConseil`). Journal d'audit : enregistrement, validation, réouverture, exports.
- Tests : `pedagogie/test_conseils.py` (droits, cloisonnement par école et par cycle, calculs, enregistrement et refus, validation et réouverture, PDF, passage de classe, bulletin), `pedagogie/test_conseils_arabe.py` (pages, PDF et bulletin en arabe pur). Arabe : 79 nouveaux textes dans `comptes/traductions/ar.csv` (relecture par un arabophone à faire : مجلس القسم, لوحة الشرف, التشجيعات, التهنئة).

## État du projet : Phase 80 — Notifications sur le téléphone : la carte dit pourquoi, et une notification d'essai

Constat sur un vrai téléphone : la carte « Notifications sur ce téléphone » restait **invisible** sans explication (le script la cachait quand le navigateur ne gère pas les notifications, par exemple un navigateur de marque ou celui intégré à WhatsApp, alors qu'elle s'affichait bien sur ordinateur).
- **La carte est toujours dans la page** dès que les clés sont en place (`templates/comptes/notifications.html`, `static/js/push.js`) et écrit ce qui se passe : « Vérification de votre téléphone... » puis l'état (activées, pas activées, bloquées), ou **« Ce navigateur ne permet pas les notifications sur téléphone. Ouvrez Yelenova avec Chrome (Android) ou installez l'application sur l'écran d'accueil (iPhone). »**. Si le téléphone ne répond pas en 8 secondes, elle le dit aussi (service worker absent).
- **Notification d'essai** : un bouton apparaît quand les notifications sont activées ; il envoie une notification aux seuls appareils de la personne connectée (`/comptes/push/essai/`, 10 par heure, rien n'est ajouté à son historique ; message en français ou en arabe selon la page).
- **Pour le développeur seulement** : quand les clés ne sont pas dans l'environnement du serveur, la page Notifications le dit et nomme les deux variables à ajouter (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`) ; les autres rôles ne voient aucun message technique.
- Tests : `comptes/test_push.py` (classes `EssaiEtCarteTests`, `EssaiEteintTests`). Arabe : 10 nouveaux textes (page et script).

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
