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

    // Solde de congés payés de l'employé choisi (voir finances/enregistrer
    // un congé) : rechargé à chaque changement d'employé, même principe que
    // les mois couverts ci-dessus.
    document.querySelectorAll("[data-solde-url]").forEach(function (conteneur) {
        var cible = document.getElementById(conteneur.dataset.soldeCible);
        if (!cible) return;
        cible.addEventListener("change", function () {
            conteneur.textContent = "";
            if (!cible.value) { conteneur.style.display = "none"; return; }
            fetch(conteneur.dataset.soldeUrl + "?email=" + encodeURIComponent(cible.value))
                .then(function (r) { return r.json(); })
                .then(function (donnees) {
                    if (donnees.solde === null) { conteneur.style.display = "none"; return; }
                    conteneur.textContent = "Solde de congés payés actuel : " + donnees.solde + " jour(s).";
                    conteneur.style.display = "block";
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

    // Saisie hors-ligne (ex. absences prises dans une salle sans réseau) :
    // un formulaire marqué data-hors-ligne est toujours envoyé en AJAX ; si
    // le réseau manque, la saisie part dans une file locale (IndexedDB) et
    // se synchronise automatiquement au retour de la connexion, ou via le
    // service worker en arrière-plan (voir sw.js). Jamais de double saisie
    // silencieuse : une session expirée ou une vraie erreur serveur sont
    // signalées plutôt que ré-essayées indéfiniment.
    var NOM_BASE_HORS_LIGNE = "hors-ligne-v1";
    var NOM_MAGASIN_HORS_LIGNE = "saisies-en-attente";

    function ouvrirBaseHorsLigne() {
        return new Promise(function (resoudre, rejeter) {
            var requete = indexedDB.open(NOM_BASE_HORS_LIGNE, 1);
            requete.onupgradeneeded = function () {
                requete.result.createObjectStore(NOM_MAGASIN_HORS_LIGNE, { keyPath: "cle" });
            };
            requete.onsuccess = function () { resoudre(requete.result); };
            requete.onerror = function () { rejeter(requete.error); };
        });
    }

    function mettreEnFileHorsLigne(saisie) {
        return ouvrirBaseHorsLigne().then(function (base) {
            return new Promise(function (resoudre, rejeter) {
                var transaction = base.transaction(NOM_MAGASIN_HORS_LIGNE, "readwrite");
                transaction.objectStore(NOM_MAGASIN_HORS_LIGNE).put(saisie);
                transaction.oncomplete = function () { resoudre(); };
                transaction.onerror = function () { rejeter(transaction.error); };
            });
        });
    }

    function listerFileHorsLigne() {
        return ouvrirBaseHorsLigne().then(function (base) {
            return new Promise(function (resoudre, rejeter) {
                var requete = base.transaction(NOM_MAGASIN_HORS_LIGNE, "readonly")
                    .objectStore(NOM_MAGASIN_HORS_LIGNE).getAll();
                requete.onsuccess = function () { resoudre(requete.result); };
                requete.onerror = function () { rejeter(requete.error); };
            });
        });
    }

    function retirerDeLaFileHorsLigne(cle) {
        return ouvrirBaseHorsLigne().then(function (base) {
            return new Promise(function (resoudre, rejeter) {
                var transaction = base.transaction(NOM_MAGASIN_HORS_LIGNE, "readwrite");
                transaction.objectStore(NOM_MAGASIN_HORS_LIGNE).delete(cle);
                transaction.oncomplete = function () { resoudre(); };
                transaction.onerror = function () { rejeter(transaction.error); };
            });
        });
    }

    function afficherEtatHorsLigne(conteneur, enAttente, sessionExpiree, enErreur) {
        if (!conteneur) return;
        conteneur.innerHTML = "";
        if (sessionExpiree) {
            conteneur.className = "alert alert-danger";
            conteneur.appendChild(document.createTextNode(
                "Votre session a expiré : reconnectez-vous pour synchroniser " + enAttente + " saisie(s) en attente."
            ));
            conteneur.style.display = "block";
            return;
        }
        if (enErreur) {
            conteneur.className = "alert alert-danger";
            conteneur.appendChild(document.createTextNode(
                enErreur + " saisie(s) n'ont pas pu être synchronisées et doivent être ressaisies."
            ));
            conteneur.style.display = "block";
            return;
        }
        if (enAttente > 0) {
            conteneur.className = "alert alert-warning";
            conteneur.appendChild(document.createTextNode(
                enAttente + " saisie(s) en attente de synchronisation (hors-ligne). "
            ));
            var bouton = document.createElement("button");
            bouton.type = "button";
            bouton.className = "btn btn-sm btn-outline-secondary";
            bouton.textContent = "Synchroniser maintenant";
            bouton.addEventListener("click", function () { synchroniserFileHorsLigne(conteneur); });
            conteneur.appendChild(bouton);
            conteneur.style.display = "block";
            return;
        }
        conteneur.style.display = "none";
    }

    function ajouterLigneAbsence(resultat) {
        var corps = document.getElementById("corps-tableau-absences");
        if (corps) {
            var ligne = document.createElement("tr");
            [resultat.eleve, resultat.date_absence, resultat.justifiee ? "Oui" : "Non"].forEach(function (texte) {
                var cellule = document.createElement("td");
                cellule.textContent = texte;
                ligne.appendChild(cellule);
            });
            corps.insertBefore(ligne, corps.firstChild);
        }
        var tableau = document.getElementById("tableau-absences");
        var videMsg = document.getElementById("absences-vide");
        if (tableau) tableau.style.display = "";
        if (videMsg) videMsg.style.display = "none";
    }

    function synchroniserFileHorsLigne(conteneur) {
        listerFileHorsLigne().then(function (saisies) {
            var sessionExpiree = false;
            var enErreur = 0;
            function suivante(index) {
                if (index >= saisies.length) {
                    listerFileHorsLigne().then(function (restantes) {
                        afficherEtatHorsLigne(conteneur, restantes.length, sessionExpiree, enErreur);
                    });
                    return;
                }
                var saisie = saisies[index];
                var donnees = new FormData();
                saisie.champs.forEach(function (paire) { donnees.append(paire[0], paire[1]); });
                fetch(saisie.url, {
                    method: "POST", body: donnees, credentials: "same-origin",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                }).then(function (reponse) {
                    if (reponse.redirected && reponse.url.indexOf("/connexion/") !== -1) {
                        sessionExpiree = true;
                        suivante(index + 1);
                        return;
                    }
                    if (!reponse.ok) {
                        enErreur += 1;
                        retirerDeLaFileHorsLigne(saisie.cle).then(function () { suivante(index + 1); });
                        return;
                    }
                    reponse.json().then(function (resultat) {
                        if (resultat.ok) {
                            ajouterLigneAbsence(resultat);
                        } else {
                            enErreur += 1;
                        }
                        retirerDeLaFileHorsLigne(saisie.cle).then(function () { suivante(index + 1); });
                    });
                }).catch(function () {
                    // Toujours hors-ligne : on arrête ici, on retentera plus tard.
                    listerFileHorsLigne().then(function (restantes) {
                        afficherEtatHorsLigne(conteneur, restantes.length, sessionExpiree, enErreur);
                    });
                });
            }
            suivante(0);
        });
    }

    if (window.indexedDB) {
        document.querySelectorAll("form[data-hors-ligne]").forEach(function (formulaire) {
            var conteneurEtat = document.getElementById("etat-hors-ligne");

            if (navigator.onLine) {
                synchroniserFileHorsLigne(conteneurEtat);
            } else {
                listerFileHorsLigne().then(function (saisies) {
                    afficherEtatHorsLigne(conteneurEtat, saisies.length, false, 0);
                });
            }

            formulaire.addEventListener("submit", function (evenement) {
                evenement.preventDefault();
                var donnees = new FormData(formulaire);
                fetch(formulaire.action || window.location.href, {
                    method: "POST", body: donnees, credentials: "same-origin",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                }).then(function (reponse) {
                    if (reponse.redirected && reponse.url.indexOf("/connexion/") !== -1) {
                        throw new Error("session_expiree");
                    }
                    if (!reponse.ok) {
                        throw new Error("erreur_serveur");
                    }
                    return reponse.json();
                }).then(function (resultat) {
                    formulaire.querySelectorAll("[id^='erreurs-']").forEach(function (b) { b.innerHTML = ""; });
                    if (!resultat.ok) {
                        Object.keys(resultat.erreurs || {}).forEach(function (nomChamp) {
                            var conteneurErreur = document.getElementById("erreurs-" + nomChamp);
                            if (!conteneurErreur) return;
                            resultat.erreurs[nomChamp].forEach(function (erreur) {
                                var div = document.createElement("div");
                                div.className = "text-danger small mt-1";
                                div.textContent = erreur;
                                conteneurErreur.appendChild(div);
                            });
                        });
                        return;
                    }
                    ajouterLigneAbsence(resultat);
                    formulaire.reset();
                    var champMatricule = formulaire.querySelector("[name='matricule_eleve']");
                    if (champMatricule) champMatricule.focus();
                }).catch(function (erreur) {
                    if (erreur && erreur.message === "session_expiree") {
                        listerFileHorsLigne().then(function (saisies) {
                            afficherEtatHorsLigne(conteneurEtat, saisies.length, true, 0);
                        });
                        return;
                    }
                    if (erreur && erreur.message === "erreur_serveur") {
                        conteneurEtat.className = "alert alert-danger";
                        conteneurEtat.textContent = "Une erreur est survenue, la saisie n'a pas été enregistrée.";
                        conteneurEtat.style.display = "block";
                        return;
                    }
                    // Vrai échec réseau (fetch n'a pas pu joindre le serveur) : on
                    // met la saisie en file pour l'envoyer dès que possible.
                    var entrees = Array.from(donnees.entries());
                    mettreEnFileHorsLigne({
                        cle: Date.now() + "-" + Math.random().toString(36).slice(2),
                        url: formulaire.action || window.location.href,
                        champs: entrees,
                    }).then(function () {
                        listerFileHorsLigne().then(function (saisies) {
                            afficherEtatHorsLigne(conteneurEtat, saisies.length, false, 0);
                        });
                        formulaire.reset();
                        if ("serviceWorker" in navigator && "SyncManager" in window) {
                            navigator.serviceWorker.ready.then(function (enregistrement) {
                                return enregistrement.sync.register("synchroniser-absences");
                            }).catch(function () {});
                        }
                    });
                }).finally(function () {
                    // Le gestionnaire générique (en haut de ce fichier) désactive le
                    // bouton à la soumission en s'attendant à un rechargement de
                    // page - qui n'arrive jamais ici (tout est intercepté en AJAX).
                    // Sans ça, le bouton resterait grisé indéfiniment.
                    formulaire.querySelectorAll("button[type='submit']").forEach(function (bouton) {
                        bouton.disabled = false;
                        bouton.classList.remove("bouton-en-cours");
                    });
                });
            });

            window.addEventListener("online", function () { synchroniserFileHorsLigne(conteneurEtat); });
        });

        if ("serviceWorker" in navigator) {
            navigator.serviceWorker.addEventListener("message", function (evenement) {
                if (evenement.data !== "file-hors-ligne-mise-a-jour") return;
                document.querySelectorAll("form[data-hors-ligne]").forEach(function () {
                    var conteneurEtat = document.getElementById("etat-hors-ligne");
                    listerFileHorsLigne().then(function (saisies) {
                        afficherEtatHorsLigne(conteneurEtat, saisies.length, false, 0);
                    });
                });
            });
        }
    }

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
