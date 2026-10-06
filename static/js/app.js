document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-auto-submit]").forEach(function (champ) {
        champ.addEventListener("change", function () { champ.form.submit(); });
    });

    document.querySelectorAll('form[method="post"], form[method="POST"], form[data-attente]').forEach(function (formulaire) {
        formulaire.addEventListener("submit", function (evenement) {
            var confirmation = formulaire.getAttribute("data-confirmer");
            if (confirmation && !window.confirm(confirmation)) {
                evenement.preventDefault();
                return;
            }
            formulaire.querySelectorAll("button, input[type='submit']").forEach(function (bouton) {
                if (bouton.type !== "submit") return;
                bouton.disabled = true;
                if (bouton.tagName === "BUTTON") bouton.classList.add("bouton-en-cours");
            });
        });
    });

    // Liens de téléchargement (export PDF/CSV) : la page ne navigue pas
    // ailleurs (le fichier part en pièce jointe), donc pas d'état "désactivé"
    // fiable possible - juste un repère visuel qui se referme tout seul.
    document.querySelectorAll("a[data-telechargement]").forEach(function (lien) {
        lien.addEventListener("click", function () {
            if (lien.classList.contains("bouton-en-cours")) return;
            lien.classList.add("bouton-en-cours");
            setTimeout(function () { lien.classList.remove("bouton-en-cours"); }, 4000);
        });
    });

    function fermerToast(toast) {
        toast.classList.add("masque");
        toast.addEventListener("animationend", function () { toast.remove(); }, { once: true });
    }
    document.querySelectorAll(".toast-message").forEach(function (toast) {
        var minuteur = setTimeout(function () { fermerToast(toast); }, 6000);
        var bouton = toast.querySelector(".toast-fermer");
        if (bouton) {
            bouton.addEventListener("click", function () {
                clearTimeout(minuteur);
                fermerToast(toast);
            });
        }
    });

    var boutonMenu = document.querySelector(".bouton-menu-mobile");
    var sidebar = document.getElementById("sidebar");
    var rideau = document.getElementById("sidebar-rideau");
    if (boutonMenu && sidebar) {
        boutonMenu.addEventListener("click", function () {
            sidebar.classList.toggle("ouvert");
            if (rideau) rideau.classList.toggle("ouvert");
        });
    }
    if (rideau && sidebar) {
        // Seul moyen de refermer autrement qu'en tapant le bouton : la
        // sidebar ouverte recouvre entièrement ce bouton sur mobile.
        rideau.addEventListener("click", function () {
            sidebar.classList.remove("ouvert");
            rideau.classList.remove("ouvert");
        });
    }

    // Recherche avec suggestions (ex. choisir un élève par nom plutôt que de
    // devoir déjà connaître son matricule par cœur - voir finances/saisir
    // un paiement/un salaire). Générique : n'importe quel champ texte avec
    // data-recherche-url devient une recherche en direct, le résultat choisi
    // remplit le champ caché data-recherche-cible.
    document.querySelectorAll("[data-recherche-url]").forEach(function (champRecherche) {
        var cible = document.getElementById(champRecherche.dataset.rechercheCible);
        var conteneurResultats = champRecherche.parentElement.querySelector("[data-recherche-resultats]");
        if (!cible || !conteneurResultats) return;
        var cleAffichage = champRecherche.dataset.rechercheAffichage;
        var cleValeur = champRecherche.dataset.rechercheValeur;
        var delai;

        function masquerResultats() {
            conteneurResultats.style.display = "none";
            conteneurResultats.innerHTML = "";
        }

        champRecherche.addEventListener("input", function () {
            clearTimeout(delai);
            cible.value = "";
            var terme = champRecherche.value.trim();
            if (terme.length < 2) { masquerResultats(); return; }
            delai = setTimeout(function () {
                fetch(champRecherche.dataset.rechercheUrl + "?q=" + encodeURIComponent(terme))
                    .then(function (r) { return r.json(); })
                    .then(function (donnees) {
                        conteneurResultats.innerHTML = "";
                        if (!donnees.resultats.length) {
                            var vide = document.createElement("div");
                            vide.className = "recherche-resultat-vide";
                            vide.textContent = "Aucun résultat.";
                            conteneurResultats.appendChild(vide);
                            conteneurResultats.style.display = "block";
                            return;
                        }
                        donnees.resultats.forEach(function (item) {
                            var ligne = document.createElement("button");
                            ligne.type = "button";
                            ligne.className = "recherche-resultat-item";
                            ligne.textContent = item[cleAffichage];
                            ligne.addEventListener("click", function () {
                                cible.value = item[cleValeur];
                                champRecherche.value = item[cleAffichage];
                                masquerResultats();
                                cible.dispatchEvent(new Event("change"));
                            });
                            conteneurResultats.appendChild(ligne);
                        });
                        conteneurResultats.style.display = "block";
                    });
            }, 300);
        });
        document.addEventListener("click", function (evenement) {
            if (evenement.target !== champRecherche) masquerResultats();
        });
    });

    // Cases à cocher des mois/trimestres couverts par un versement de
    // scolarité (voir finances/enregistrer un paiement) : rechargées à
    // chaque changement d'élève (déclenché par la recherche ci-dessus),
    // puisque les mois valides dépendent de l'échéancier de sa classe.
    document.querySelectorAll("[data-periodes-url]").forEach(function (conteneur) {
        var cible = document.getElementById(conteneur.dataset.periodesCible);
        var bloc = document.getElementById("periodes-bloc");
        if (!cible || !bloc) return;

        cible.addEventListener("change", function () {
            conteneur.innerHTML = "";
            if (!cible.value) { bloc.style.display = "none"; return; }
            fetch(conteneur.dataset.periodesUrl + "?matricule=" + encodeURIComponent(cible.value))
                .then(function (r) { return r.json(); })
                .then(function (donnees) {
                    if (!donnees.periodes.length) { bloc.style.display = "none"; return; }
                    donnees.periodes.forEach(function (libelle, index) {
                        var id = "periode-" + index;
                        var ligne = document.createElement("div");
                        ligne.className = "form-check";
                        var case_ = document.createElement("input");
                        case_.type = "checkbox";
                        case_.className = "form-check-input";
                        case_.name = "periodes";
                        case_.value = libelle;
                        case_.id = id;
                        var etiquette = document.createElement("label");
                        etiquette.className = "form-check-label";
                        etiquette.htmlFor = id;
                        etiquette.textContent = libelle;
                        ligne.appendChild(case_);
                        ligne.appendChild(etiquette);
                        conteneur.appendChild(ligne);
                    });
                    bloc.style.display = "block";
                });
        });
    });

    document.querySelectorAll(".annuaire-item").forEach(function (bouton) {
        bouton.addEventListener("click", function () {
            document.querySelectorAll(".annuaire-panneau").forEach(function (p) { p.style.display = "none"; });
            var cible = document.getElementById(bouton.dataset.cible);
            if (cible) cible.style.display = "flex";
            document.querySelectorAll(".annuaire-item").forEach(function (b) { b.classList.remove("actif"); });
            bouton.classList.add("actif");
        });
    });

    var reductionMouvement = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.querySelectorAll("[data-compteur]").forEach(function (el) {
        var texte = el.textContent.trim();
        var correspondance = texte.match(/^([\d\s]+)(.*)$/);
        if (!correspondance) return;
        var cible = parseInt(correspondance[1].replace(/\s/g, ""), 10);
        var suffixe = correspondance[2];
        if (isNaN(cible) || cible === 0 || reductionMouvement) return;
        var duree = 600;
        var debut = null;
        function etape(horodatage) {
            if (!debut) debut = horodatage;
            var progression = Math.min((horodatage - debut) / duree, 1);
            el.textContent = Math.floor(progression * cible).toLocaleString("fr-FR") + suffixe;
            if (progression < 1) requestAnimationFrame(etape);
            else el.textContent = cible.toLocaleString("fr-FR") + suffixe;
        }
        requestAnimationFrame(etape);
    });

    var boutonTheme = document.querySelector("[data-bouton-theme]");
    if (boutonTheme) {
        var estSombreActuellement = function () {
            var force = document.documentElement.getAttribute("data-theme");
            if (force === "dark") return true;
            if (force === "light") return false;
            return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
        };
        var rafraichirLibelle = function () {
            boutonTheme.textContent = estSombreActuellement() ? "Mode clair" : "Mode sombre";
        };
        rafraichirLibelle();
        boutonTheme.addEventListener("click", function () {
            var nouveauTheme = estSombreActuellement() ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", nouveauTheme);
            try { localStorage.setItem("theme", nouveauTheme); } catch (e) {}
            rafraichirLibelle();
        });
    }
});

// Enregistrement du service worker : rend l'application installable et met
// en cache les fichiers statiques. Ne concerne jamais les pages/données
// dynamiques (voir static/js/sw.js) - sans risque pour la fraîcheur des
// notes, paiements, etc.
if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
        navigator.serviceWorker.register("/sw.js").catch(function () {});
    });
}
