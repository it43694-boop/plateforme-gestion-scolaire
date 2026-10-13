"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

from config.views import manifeste_pwa, sante, service_worker

# Page d'administration technique (réservée au propriétaire de la plateforme)
admin.site.site_header = f"{settings.NOM_PLATEFORME} - administration"
admin.site.site_title = settings.NOM_PLATEFORME
admin.site.index_title = "Administration de la plateforme"


def connexion_de_l_administration(request, extra_context=None):
    """
    L'administration n'a PAS son propre formulaire de connexion : on passe par celui de l'application, qui limite les essais,
    verrouille le compte après plusieurs échecs et exige la double authentification. Le formulaire d'origine de Django ne fait
    rien de cela : un mot de passe seul aurait suffi pour entrer dans toutes les données de la plateforme. (Il répondait de
    plus par une erreur 500 à un visiteur non connecté, l'administration lisant le rôle d'un utilisateur anonyme.)
    """
    return redirect("comptes:connexion")


admin.site.login = connexion_de_l_administration

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", sante, name="sante"),
    path("manifest.webmanifest", manifeste_pwa, name="manifeste_pwa"),
    path("sw.js", service_worker, name="service_worker"),
    path("comptes/", include("comptes.urls")),
    path("scolarite/", include("scolarite.urls")),
    path("finances/", include("finances.urls")),
    path("comptabilite/", include("comptabilite.urls")),
    path("pedagogie/", include("pedagogie.urls")),
    path("tests-de-niveau/", include("tests_niveau.urls")),
    path("assistant/", include("assistant.urls")),
    path("plateforme/", include("espace_plateforme.urls")),
    path("bibliotheque/", include("bibliotheque.urls")),
    path("communication/", include("communication.urls")),
    path("statistiques/", include("statistiques.urls")),
    path("espace-developpeur/", include("espace_developpeur.urls")),
    path("", include("vitrine.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
