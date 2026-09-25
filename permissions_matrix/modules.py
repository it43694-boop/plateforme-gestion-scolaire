from django.db import models


class Module(models.TextChoices):
    """Les 16 modules du périmètre fonctionnel (cahier des charges, section 5)."""

    CLASSES = "classes", "Classes"
    ELEVES = "eleves", "Élèves"
    ENSEIGNANTS = "enseignants", "Enseignants"
    EMPLOI_DU_TEMPS = "emploi_du_temps", "Emploi du temps"
    SUIVI_DES_COURS = "suivi_des_cours", "Suivi des cours"
    NOTES_BULLETINS = "notes_bulletins", "Notes et bulletins"
    ABSENCES = "absences", "Absences"
    FINANCES = "finances", "Finances"
    CAISSE = "caisse", "Caisse"
    SALAIRES = "salaires", "Salaires"
    TESTS_DE_NIVEAU = "tests_de_niveau", "Tests de niveau"
    BIBLIOTHEQUE = "bibliotheque", "Bibliothèque"
    COMMUNICATION = "communication", "Communication"
    STATISTIQUES = "statistiques", "Statistiques"
    ASSISTANT = "assistant", "Assistant"
    ESPACE_DEVELOPPEUR = "espace_developpeur", "Espace développeur"
