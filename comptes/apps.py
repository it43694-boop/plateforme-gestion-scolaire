from django.apps import AppConfig


class ComptesConfig(AppConfig):
    name = 'comptes'

    def ready(self):
        from comptes import signaux  # noqa: F401  (branche les signaux : voir comptes/signaux.py)
