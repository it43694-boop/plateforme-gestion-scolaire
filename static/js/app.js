document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-auto-submit]").forEach(function (champ) {
        champ.addEventListener("change", function () { champ.form.submit(); });
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
