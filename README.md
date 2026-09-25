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
