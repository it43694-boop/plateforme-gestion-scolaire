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
    if (boutonMenu) {
        boutonMenu.addEventListener("click", function () {
            var sidebar = document.getElementById("sidebar");
            if (sidebar) sidebar.classList.toggle("ouvert");
        });
    }

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
