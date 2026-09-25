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
from django.urls import include, path

from config.views import sante

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", sante, name="sante"),
    path("comptes/", include("comptes.urls")),
    path("scolarite/", include("scolarite.urls")),
    path("finances/", include("finances.urls")),
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
