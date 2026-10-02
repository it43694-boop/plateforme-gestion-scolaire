# Plateforme de gestion scolaire

Logiciel de gestion scolaire multi-établissement, développé en Django.
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
- **Nom du logiciel** : « L'éducation du Mali au service de l'avenir »
  (`settings.NOM_PLATEFORME`) — distinct du nom de chaque établissement,
  utilisé uniquement sur la page d'accueil et dans la documentation
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
