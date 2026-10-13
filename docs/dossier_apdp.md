# Dossier de préparation : protection des données personnelles (Mali, APDP)

> **Ce document n'est pas un avis juridique.** Il décrit, de façon factuelle, ce que fait la plateforme avec les
> données personnelles, pour qu'un juriste (ou le correspondant de l'APDP) puisse préparer les formalités. Les
> points marqués **« À confirmer »** sont des questions de droit que seul un juriste malien peut trancher.

Cadre à vérifier : loi n° 2013-015 du 21 mai 2013 portant protection des données à caractère personnel en
République du Mali, et Autorité de Protection des Données à caractère Personnel (APDP).

## 1. Rôles

| Qui | Rôle probable | À confirmer |
|---|---|---|
| Chaque **établissement** (école, collège, lycée) | Responsable du traitement des données de ses élèves, parents et personnel | Chaque école doit-elle faire sa propre déclaration, ou l'éditeur peut-il la faire pour elles ? |
| L'**éditeur** de la plateforme | Sous-traitant des établissements ; responsable du traitement pour les seuls comptes de gestion de la plateforme | Contrat de sous-traitance à prévoir avec chaque école (voir les conditions d'utilisation) |

## 2. Registre des traitements

| Traitement | Finalité | Personnes concernées | Données | Qui y accède |
|---|---|---|---|---|
| Inscription et dossier de l'élève | Gérer la scolarité | Élèves (en majorité mineurs) | Nom, prénom, sexe, date et lieu de naissance, n° d'acte de naissance, matricule, classe | Direction, secrétariat, enseignants de ses classes, parents, l'élève |
| Notes et bulletins | Évaluer, produire les bulletins et classements | Élèves | Notes de classe et de composition, moyennes, rang, appréciations | Direction, enseignants (leurs matières), parents, l'élève |
| Absences | Suivre l'assiduité | Élèves | Dates, justification, motif | Direction, enseignants de la classe, parents, l'élève |
| Résultats aux examens | Statistiques et suivi | Élèves | Admis, ajourné, absent, examen | Direction et secrétariat |
| Situation particulière | Statistiques de l'éducation | Élèves | Handicap, déplacement / refuge (**données sensibles**) | Administration de l'école, parents, l'élève ; jamais les enseignants ni la comptabilité |
| Comptes parents | Lier un parent à ses enfants, communiquer | Parents | Nom, prénom, email, téléphone, profession | Direction, secrétariat, le parent |
| Paiements de scolarité | Encaisser, éditer les reçus, tenir la caisse et la comptabilité | Parents, élèves | Montant, date, mode de paiement, élève concerné | Direction, comptabilité |
| Personnel | Contrats, congés, paie | Employés, enseignants | Identité, contrat, salaire, cotisations, congés | Direction, comptabilité |
| Communication | Annonces, messagerie | Tous les utilisateurs | Messages, destinataires | Selon les rôles |
| Sécurité et audit | Protéger les accès, tracer les actions sensibles | Tous les utilisateurs | Adresse IP, dates de connexion, journal des actions | Direction de l'école ; le propriétaire de la plateforme pour la maintenance |
| Assistant (optionnel) | Répondre à des questions sur un dossier | Élèves (indirectement) | Notes, absences, paiements **sans nom, ni matricule, ni référence** ; question saisie nettoyée des noms, emails et longs numéros | Prestataire d'IA (si activé) |

## 3. Sous-traitants et transferts hors du Mali

| Prestataire | Rôle | Siège | Données concernées |
|---|---|---|---|
| Render | Hébergement de l'application | États-Unis | Toutes les données en transit et en mémoire |
| Supabase | Base de données et stockage des fichiers (logos, justificatifs) | États-Unis | Toutes les données de la base ; fichiers téléversés |
| Brevo | Envoi des emails | France | Adresse email et contenu des messages (codes de vérification, notifications) |
| Sentry (si activé) | Détection des erreurs | États-Unis | Aucun contenu de formulaire ni donnée personnelle (corps des requêtes et variables locales désactivés) |
| Groq (si activé) | Assistant | États-Unis | Données anonymisées, voir ci-dessus |

**À confirmer :** ces transferts exigent-ils une autorisation de l'APDP ou des garanties particulières ? Faut-il
héberger les données dans une région précise ? Quels contrats (clauses de sous-traitance) obtenir de chaque prestataire ?

## 4. Mesures de sécurité en place

- Connexion chiffrée (HTTPS) ; mots de passe hachés ; double authentification (application d'authentification) ; verrouillage temporaire après des échecs répétés.
- Cloisonnement des données par établissement, par rôle et par cycle ; **tests automatiques** vérifiant qu'un établissement ne voit jamais les données d'un autre, y compris par la forme des réponses d'erreur.
- Fichiers servis par liens temporaires signés (bucket privé : à vérifier dans Supabase).
- Journal d'audit des actions sensibles ; limitation du nombre de tentatives sur les pages publiques.
- Mot de passe provisoire pour les élèves, à changer à la première connexion.
- Pages de saisie hors connexion effacées à la déconnexion (appareils partagés).
- Aucun secret dans le dépôt ; supervision d'erreurs configurée sans données personnelles.

**Mesures à mettre en place par l'exploitant (non automatiques) :**
- Sauvegardes automatiques et régulières de la base et des fichiers, stockées chez un autre prestataire, avec un test de restauration.
- Passage du dépôt GitHub en privé (l'historique contient l'adresse email personnelle de l'auteur et un identifiant de projet).
- Offres d'hébergement payantes (les offres gratuites s'endorment ou se mettent en pause et ont des sauvegardes limitées).

## 5. Droits des personnes

Accès, rectification, suppression et opposition : adressés à l'établissement (responsable du traitement), qui peut
corriger les données dans la plateforme (« Corriger le dossier » sur la fiche de l'élève). Pour un mineur, les droits
s'exercent par ses parents ou son tuteur.

**Suppression :** le développeur de l'école peut retirer un élève (« Supprimer / anonymiser » sur sa fiche), après avoir retapé
son matricule. Sans historique (doublon créé par erreur), l'élève est supprimé définitivement. Avec un historique (paiements,
notes, absences, documents remis), il est **anonymisé** : nom, prénom, email, téléphone, matricule, lieu et acte de naissance,
jour de naissance, famille sans compte, messages parents-enseignants, notifications qui le nomment, motifs d'absence et de sortie
et justificatif de transfert sont effacés ; le sexe, l'année et le mois de naissance, le handicap, le déplacement et les
chiffres (notes, absences, paiements) sont conservés pour la comptabilité et les statistiques officielles. Cette opération est
irréversible et notée au journal d'audit sans nom ni matricule.
**À confirmer avec le juriste :** (1) si l'année et le mois de naissance, le sexe et le handicap gardés suffisent à dire
« anonymisé » dans une très petite classe, ou s'il faut les supprimer aussi ; (2) les durées de conservation légales par
catégorie de document, avant lesquelles une suppression complète serait interdite. Les sauvegardes de la base (hébergeur)
gardent l'élève jusqu'à leur expiration.

**Minimisation :** les messages de la messagerie parents-enseignants et des fils d'équipe sont effacés automatiquement au bout de
30 jours (réglable), et les sessions de connexion expirées chaque jour. Les autres données (notes, paiements, dossiers, journal
d'audit, notifications) sont gardées jusqu'à une décision de l'école : leurs durées restent à fixer (voir ci-dessous). La page
« Confidentialité » ne mentionne pas encore l'effacement des messages : à ajouter après relecture par le juriste.

## 6. Questions à poser au juriste

1. Quelle formalité pour chaque traitement : déclaration ou autorisation (données sensibles de handicap et de déplacement ; transferts hors du Mali) ?
2. Qui dépose : chaque école, l'éditeur pour le compte des écoles, ou les deux ?
3. Les écoles doivent-elles informer les parents et recueillir un consentement écrit pour les données des mineurs ? Fournir un modèle de formulaire d'inscription.
4. Durées de conservation à imposer par type de donnée (dossiers élèves, notes, comptabilité, paie, journaux).
5. Contenu minimal du contrat de sous-traitance entre l'éditeur et une école.
6. Relecture des trois pages publiques (mentions légales, conditions d'utilisation, politique de confidentialité) et de leur mention « version provisoire ».
7. Faut-il désigner un correspondant à la protection des données ?

## 7. Après la validation juridique

1. Renseigner l'identité de l'éditeur dans les variables d'environnement de l'hébergeur : `EDITEUR_NOM`, `EDITEUR_STATUT`, `EDITEUR_ADRESSE`, `EDITEUR_EMAIL`, `EDITEUR_TELEPHONE`, `EDITEUR_IMMATRICULATION`, `DIRECTEUR_PUBLICATION`.
2. Corriger les textes (`templates/vitrine/*.html`) selon les remarques du juriste et mettre à jour `DATE_VERSION_LEGALE` dans `vitrine/views.py`.
3. Passer `PAGES_LEGALES_VALIDEES=True` : le bandeau « version provisoire » disparaît.
