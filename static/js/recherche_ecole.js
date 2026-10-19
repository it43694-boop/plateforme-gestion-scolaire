// Recherche en direct de l'établissement, sur la page d'accueil : quelques lettres suffisent, au lieu de chercher dans une longue liste.
// Les résultats sont construits avec le DOM (textContent), jamais avec du HTML venu du serveur.
(function () {
    var champ = document.querySelector("[data-recherche-ecole-url]");
    var conteneur = document.querySelector("[data-recherche-ecole-resultats]");
    if (!champ || !conteneur) return;
    var depart = conteneur.innerHTML; // ce que la page montrait avant la recherche (la liste complète si elle est courte)
    var delai;

    function ligne(ecole) {
        var lien = document.createElement("a");
        lien.className = "btn-hero-secondaire vitrine-etablissement-lien";
        lien.href = ecole.adresse;
        if (ecole.logo) {
            var image = document.createElement("img");
            image.className = "vitrine-etablissement-logo";
            image.alt = "";
            image.src = ecole.logo;
            lien.appendChild(image);
        } else {
            var initiale = document.createElement("span");
            initiale.className = "vitrine-etablissement-initiale";
            initiale.textContent = ecole.initiale;
            lien.appendChild(initiale);
        }
        var texte = document.createElement("span");
        texte.textContent = ecole.nom;
        if (ecole.lieu) {
            var lieu = document.createElement("span");
            lieu.className = "vitrine-etablissement-lieu";
            lieu.textContent = ecole.lieu;
            texte.appendChild(lieu);
        }
        lien.appendChild(texte);
        return lien;
    }

    champ.addEventListener("input", function () {
        clearTimeout(delai);
        var terme = champ.value.trim();
        if (terme.length < 2) {
            conteneur.innerHTML = depart;
            return;
        }
        delai = setTimeout(function () {
            fetch(champ.dataset.rechercheEcoleUrl + "?q=" + encodeURIComponent(terme))
                .then(function (reponse) { return reponse.json(); })
                .then(function (donnees) {
                    if (champ.value.trim() !== terme) return; // une frappe plus récente a déjà relancé la recherche
                    conteneur.innerHTML = "";
                    if (!donnees.resultats.length) {
                        var vide = document.createElement("p");
                        vide.className = "vitrine-etablissements-intro";
                        vide.textContent = donnees.vide;
                        conteneur.appendChild(vide);
                        return;
                    }
                    donnees.resultats.forEach(function (ecole) { conteneur.appendChild(ligne(ecole)); });
                });
        }, 250);
    });
})();
