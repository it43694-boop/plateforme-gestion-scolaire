// Notifications sur le téléphone (Web Push) : s'abonner ou se désabonner depuis la page « Notifications », et retirer l'appareil à la déconnexion
// (un ordinateur ou un téléphone partagé ne doit pas continuer à recevoir les notifications de la personne précédente).
// Les textes affichés viennent de t() (app.js), traduits par le serveur.
(function () {
    var brut = document.getElementById("cle-push");
    if (!brut) return;
    var cle = JSON.parse(brut.textContent);
    var gere = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

    function texte(cleTexte) { return typeof t === "function" ? t(cleTexte) : cleTexte; }

    function jeton() {
        var champ = document.querySelector("input[name=csrfmiddlewaretoken]");
        return champ ? champ.value : "";
    }

    function envoyer(chemin, corps) {
        return fetch(chemin, {
            method: "POST", credentials: "same-origin", body: JSON.stringify(corps),
            headers: {"Content-Type": "application/json", "X-CSRFToken": jeton()},
        });
    }

    function cleEnOctets(base64) {
        var rempli = (base64 + "====").slice(0, base64.length + ((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
        var binaire = atob(rempli), octets = new Uint8Array(binaire.length);
        for (var i = 0; i < binaire.length; i++) octets[i] = binaire.charCodeAt(i);
        return octets;
    }

    function abonnement() {
        return navigator.serviceWorker.ready.then(function (enregistrement) { return enregistrement.pushManager.getSubscription(); });
    }

    function activer() {
        return Notification.requestPermission().then(function (permission) {
            if (permission !== "granted") throw new Error("refuse");
            return navigator.serviceWorker.ready;
        }).then(function (enregistrement) {
            return enregistrement.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: cleEnOctets(cle)});
        }).then(function (souscription) {
            return envoyer("/comptes/push/abonner/", souscription.toJSON()).then(function (reponse) {
                if (!reponse.ok) throw new Error("serveur");
            });
        });
    }

    function desactiver() {
        return abonnement().then(function (souscription) {
            if (!souscription) return null;
            var adresse = souscription.endpoint;
            return souscription.unsubscribe().then(function () { return envoyer("/comptes/push/desabonner/", {endpoint: adresse}); });
        });
    }

    // Un appareil déjà abonné est rattaché à la personne connectée (une fois par session du navigateur) : si le compte a changé, il change aussi.
    if (gere && Notification.permission === "granted") {
        abonnement().then(function (souscription) {
            if (!souscription) return;
            var marque = "push-rattache";
            try { if (sessionStorage.getItem(marque) === souscription.endpoint) return; } catch (erreur) { /* stockage indisponible */ }
            envoyer("/comptes/push/abonner/", souscription.toJSON()).then(function (reponse) {
                if (reponse.ok) { try { sessionStorage.setItem(marque, souscription.endpoint); } catch (erreur) { /* idem */ } }
            });
        });
    }

    // Déconnexion : l'appareil quitte le compte avant que la session se ferme (au plus 1,5 s d'attente).
    document.querySelectorAll('form[action$="/comptes/deconnexion/"]').forEach(function (formulaire) {
        formulaire.addEventListener("submit", function (evenement) {
            if (!gere || Notification.permission !== "granted") return;
            evenement.preventDefault();
            var fait = false;
            function poursuivre() { if (!fait) { fait = true; formulaire.submit(); } }
            setTimeout(poursuivre, 1500);
            desactiver().then(poursuivre, poursuivre);
        });
    });

    // La carte de la page « Notifications » : toujours visible quand les notifications sont allumées sur le site, et elle dit pourquoi quand ce
    // téléphone ne peut pas les recevoir (au lieu de disparaître sans rien dire).
    var carte = document.querySelector("[data-push-carte]");
    if (!carte) return;
    var etat = carte.querySelector("[data-push-etat]");
    var boutonActiver = carte.querySelector("[data-push-activer]");
    var boutonDesactiver = carte.querySelector("[data-push-desactiver]");
    var boutonEssai = carte.querySelector("[data-push-essai]");
    if (!gere) {
        etat.textContent = texte("Ce navigateur ne permet pas les notifications sur téléphone. Ouvrez Yelenova avec Chrome (Android) ou installez l'application sur l'écran d'accueil (iPhone).");
        return;
    }
    var attente = setTimeout(function () {
        if (etat.getAttribute("data-fini") !== "1") etat.textContent = texte("Le téléphone ne répond pas : fermez et rouvrez l'application, puis réessayez.");
    }, 8000);

    function afficher() {
        if (Notification.permission === "denied") {
            etat.setAttribute("data-fini", "1"); clearTimeout(attente);
            etat.textContent = texte("Les notifications sont bloquées : autorisez-les dans les réglages de votre navigateur.");
            boutonActiver.hidden = true; boutonDesactiver.hidden = true; if (boutonEssai) boutonEssai.hidden = true;
            return;
        }
        abonnement().then(function (souscription) {
            etat.setAttribute("data-fini", "1"); clearTimeout(attente);
            var actif = !!souscription && Notification.permission === "granted";
            etat.textContent = texte(actif ? "Les notifications sont activées sur cet appareil." : "Les notifications ne sont pas activées sur cet appareil.");
            boutonActiver.hidden = actif; boutonDesactiver.hidden = !actif; if (boutonEssai) boutonEssai.hidden = !actif;
        });
    }

    function essayer() {
        boutonEssai.disabled = true;
        var echec = function () { etat.textContent = texte("L'essai n'a pas pu être envoyé. Désactivez puis réactivez les notifications."); };
        envoyer("/comptes/push/essai/", {}).then(function (reponse) {
            if (reponse.status === 429) { etat.textContent = texte("Trop d'essais : réessayez dans une heure."); return null; }
            return reponse.json().then(function (corps) {
                if (corps && corps.ok) etat.textContent = texte("Notification d'essai envoyée : elle doit arriver dans quelques secondes.");
                else echec();
            });
        }).catch(echec).then(function () { boutonEssai.disabled = false; });
    }
    if (boutonEssai) boutonEssai.addEventListener("click", essayer);

    function erreur() { etat.textContent = texte("Activation impossible pour le moment. Réessayez plus tard."); }
    boutonActiver.addEventListener("click", function () { activer().then(afficher, function () { afficher(); if (Notification.permission !== "denied") erreur(); }); });
    boutonDesactiver.addEventListener("click", function () { desactiver().then(afficher, afficher); });
    afficher();
})();
