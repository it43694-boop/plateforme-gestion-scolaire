// Textes que ce script écrit lui-même : traduits par le serveur (voir comptes/templatetags/traductions.py), en français sinon.
function t(texte) {
    try {
        var bloc = document.getElementById("textes-js");
        var textes = bloc ? JSON.parse(bloc.textContent) : {};
        return Object.prototype.hasOwnProperty.call(textes, texte) ? textes[texte] : texte;
    } catch (erreur) {
        return texte;
    }
}

// Chiffres affichés par le script : arabes (٠١٢...) quand la page est en arabe, comme ceux que le serveur écrit.
function chiffres(valeur) {
    var texte = String(valeur);
    if (document.documentElement.lang !== "ar") return texte;
    return texte.replace(/\d/g, function (c) { return "٠١٢٣٤٥٦٧٨٩".charAt(Number(c)); });
}
function chiffresOccidentaux(texte) {
    return String(texte).replace(/[٠-٩]/g, function (c) { return String(c.charCodeAt(0) - 1632); });
}

document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-imprimer]").forEach(function (bouton) {
        bouton.addEventListener("click", function () { window.print(); });
    });

    // Copier un texte dans le presse-papiers (message à coller dans un groupe WhatsApp).
    document.querySelectorAll("[data-copier]").forEach(function (bouton) {
        var libelle = bouton.textContent;
        bouton.addEventListener("click", function () {
            var source = document.querySelector(bouton.getAttribute("data-copier"));
            if (!source) return;
            var fini = function () {
                bouton.textContent = t("Copié");
                setTimeout(function () { bouton.textContent = libelle; }, 2500);
            };
            var repli = function () { source.select(); document.execCommand("copy"); fini(); };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(source.value).then(fini, repli);
            } else {
                repli();
            }
        });
    });

    document.querySelectorAll("[data-auto-submit]").forEach(function (champ) {
        champ.addEventListener("change", function () { champ.form.submit(); });
    });

    // Cocher ou décocher d'un coup toutes les cases d'une liste (appel de la cantine, choix des élèves à inscrire).
    document.querySelectorAll("[data-cocher-tout]").forEach(function (bouton) {
        bouton.addEventListener("click", function () {
            var coche = bouton.getAttribute("data-valeur") !== "0";
            document.querySelectorAll(bouton.getAttribute("data-cocher-tout")).forEach(function (caseACocher) {
                if (!caseACocher.disabled) caseACocher.checked = coche;
            });
        });
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
            if (cible !== champRecherche) cible.value = ""; // champ de recherche = champ envoyé : on garde ce qui est tapé
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
                            vide.textContent = t("Aucun résultat.");
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
                                if (cible !== champRecherche) cible.value = item[cleValeur];
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
                    var etiquettes = donnees.etiquettes || donnees.periodes;
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
                        etiquette.textContent = etiquettes[index] || libelle;
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
                    conteneur.textContent = t("Solde de congés payés actuel :") + " " + (donnees.solde_texte || donnees.solde) + " " + t("jour(s).");
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
                t("Votre session a expiré : reconnectez-vous pour synchroniser") + " " + chiffres(enAttente) + " " + t("saisie(s) en attente.")
            ));
            conteneur.style.display = "block";
            return;
        }
        if (enErreur) {
            conteneur.className = "alert alert-danger";
            conteneur.appendChild(document.createTextNode(
                chiffres(enErreur) + " " + t("saisie(s) n'ont pas pu être synchronisées et doivent être ressaisies.")
            ));
            conteneur.style.display = "block";
            return;
        }
        if (enAttente > 0) {
            conteneur.className = "alert alert-warning";
            conteneur.appendChild(document.createTextNode(
                chiffres(enAttente) + " " + t("saisie(s) en attente de synchronisation (hors-ligne).") + " "
            ));
            var bouton = document.createElement("button");
            bouton.type = "button";
            bouton.className = "btn btn-sm btn-outline-secondary";
            bouton.textContent = t("Synchroniser maintenant");
            bouton.addEventListener("click", function () { synchroniserFileHorsLigne(conteneur); });
            conteneur.appendChild(bouton);
            conteneur.style.display = "block";
            return;
        }
        conteneur.style.display = "none";
    }

    // Ajoute une ligne au tableau "déjà saisi" après une soumission réussie
    // (immédiate ou synchronisée depuis la file hors-ligne), sans recharger
    // la page. Générique : la liste et l'ordre des colonnes viennent de
    // data-ligne-champs sur le <tbody>, pas d'un champ en dur - réutilisé
    // par la saisie d'absences ET de notes (voir saisir_absence.html et
    // saisir_note.html).
    function ajouterLigneResultat(resultat) {
        var corps = document.querySelector("[data-corps-resultats]");
        if (corps) {
            var champs = (corps.dataset.ligneChamps || "").split(",").filter(Boolean);
            var ligne = document.createElement("tr");
            champs.forEach(function (champ) {
                var valeur = resultat[champ];
                if (typeof valeur === "boolean") valeur = valeur ? t("Oui") : t("Non");
                var cellule = document.createElement("td");
                cellule.textContent = (valeur === null || valeur === undefined) ? "-" : chiffres(valeur);
                ligne.appendChild(cellule);
            });
            corps.insertBefore(ligne, corps.firstChild);
        }
        var tableau = document.querySelector("[data-tableau-resultats]");
        var videMsg = document.querySelector("[data-etat-vide-resultats]");
        if (tableau) { tableau.hidden = false; tableau.style.display = ""; }
        if (videMsg) { videMsg.hidden = true; videMsg.style.display = "none"; }
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
                            ajouterLigneResultat(resultat);
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
                    ajouterLigneResultat(resultat);
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
                        conteneurEtat.textContent = t("Une erreur est survenue, la saisie n'a pas été enregistrée.");
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
                                return enregistrement.sync.register("synchroniser-saisies-hors-ligne");
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
        var texte = chiffresOccidentaux(el.textContent.trim());
        // Un nombre (avec ses séparateurs de milliers) puis une unité éventuelle (« 1460000 FCFA ») : l'espace reste
        // ENTRE le nombre et l'unité (avant, il était absorbé par le nombre et « FCFA » se collait au chiffre).
        var correspondance = texte.match(/^(\d+(?:[\s\u00a0\u202f]\d{3})*)\s*(.*)$/);
        if (!correspondance) return;
        var cible = parseInt(correspondance[1].replace(/[\s\u00a0\u202f]/g, ""), 10);
        var unite = correspondance[2];
        if (isNaN(cible) || cible === 0 || /^[,.٫\d]/.test(unite)) return; // « 66,7 % » : nombre décimal, laissé tel quel
        function afficher(valeur) {
            el.textContent = chiffres(valeur.toLocaleString("fr-FR").replace(/\u202f/g, "\u00a0")); // espace insécable ordinaire (police du thème)
            if (unite) {
                var marque = document.createElement("span");
                marque.className = "stat-unite";
                marque.textContent = unite;
                el.appendChild(document.createTextNode(" "));
                el.appendChild(marque);
            }
        }
        if (reductionMouvement) { afficher(cible); return; }
        var duree = 600;
        var debut = null;
        function etape(horodatage) {
            if (!debut) debut = horodatage;
            var progression = Math.min((horodatage - debut) / duree, 1);
            afficher(Math.floor(progression * cible));
            if (progression < 1) requestAnimationFrame(etape);
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
            boutonTheme.textContent = estSombreActuellement() ? t("Mode clair") : t("Mode sombre");
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


/* ========================================================================
   Finition premium (phase 55) : trait de chargement, apparition au défilement, halo qui suit le curseur,
   ondulation des boutons, bascule de thème en douceur.
   Tout est facultatif : sans ce script, la page est complète. Rien n'est caché tant qu'il n'a pas tourné,
   et prefers-reduced-motion le désactive.
   ======================================================================== */
(function () {
    "use strict";
    var racine = document.documentElement;
    var reduit = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // --- Trait de chargement doré -------------------------------------------------------------------
    var barre = document.createElement("div");
    barre.className = "barre-chargement";
    barre.setAttribute("aria-hidden", "true");
    function demarrerBarre() {
        if (reduit) return;
        if (!barre.parentNode) document.body.appendChild(barre);
        barre.classList.remove("actif");
        void barre.offsetWidth; // relance la transition si le trait était déjà parti
        barre.classList.add("actif");
    }
    document.addEventListener("click", function (evenement) {
        var lien = evenement.target.closest && evenement.target.closest("a[href]");
        if (!lien || evenement.defaultPrevented || evenement.button !== 0) return;
        if (evenement.metaKey || evenement.ctrlKey || evenement.shiftKey || evenement.altKey) return;
        if (lien.target && lien.target !== "_self") return;
        if (lien.hasAttribute("download") || lien.hasAttribute("data-telechargement")) return;
        var adresse = lien.getAttribute("href") || "";
        if (!adresse || adresse.charAt(0) === "#" || /^(mailto|tel|sms|javascript):/i.test(adresse)) return;
        if (lien.origin && lien.origin !== window.location.origin) return;
        if (/\.(pdf|xlsx|csv|zip)(\?|$)/i.test(lien.pathname)) return;
        demarrerBarre();
    });
    document.addEventListener("submit", function (evenement) {
        if (!evenement.defaultPrevented && !evenement.target.hasAttribute("data-hors-ligne")) demarrerBarre();
    });
    window.addEventListener("pageshow", function () { barre.classList.remove("actif"); }); // retour arrière (cache de page)

    // --- Ondulation au clic sur les boutons ------------------------------------------------------------
    document.addEventListener("pointerdown", function (evenement) {
        if (reduit) return;
        var bouton = evenement.target.closest && evenement.target.closest(".btn:not(:disabled):not(.disabled)");
        if (!bouton) return;
        var boite = bouton.getBoundingClientRect();
        var taille = Math.max(boite.width, boite.height) * 2;
        var onde = document.createElement("span");
        onde.className = "btn-ondulation";
        onde.style.width = onde.style.height = taille + "px";
        onde.style.left = (evenement.clientX - boite.left - taille / 2) + "px";
        onde.style.top = (evenement.clientY - boite.top - taille / 2) + "px";
        bouton.appendChild(onde);
        setTimeout(function () { if (onde.parentNode) onde.parentNode.removeChild(onde); }, 600);
    }, { passive: true });

    // --- Halo doré qui suit le curseur (zones sombres, écrans avec souris seulement) ---------------------
    if (!reduit && window.matchMedia && window.matchMedia("(hover: hover)").matches) {
        document.querySelectorAll(".vitrine-hero, .auth-scene, .annuaire-contenu").forEach(function (zone) {
            var image = null;
            zone.addEventListener("mousemove", function (evenement) {
                if (image) return;
                image = requestAnimationFrame(function () {
                    var boite = zone.getBoundingClientRect();
                    zone.style.setProperty("--mx", (evenement.clientX - boite.left) + "px");
                    zone.style.setProperty("--my", (evenement.clientY - boite.top) + "px");
                    zone.style.setProperty("--halo-opacite", "1");
                    image = null;
                });
            });
            zone.addEventListener("mouseleave", function () { zone.style.setProperty("--halo-opacite", "0"); });
        });
    }

    // --- Apparition au défilement : uniquement ce qui est sous la ligne de flottaison ----------------------
    if (!reduit && "IntersectionObserver" in window) {
        var cibles = document.querySelectorAll(
            ".app-content > .card, .app-content > .row, .app-content > form, .app-content > .table-responsive, " +
            ".vitrine-section h2, .vitrine-section .vitrine-carte, .vitrine-section .guide-role, .vitrine-securite-corps"
        );
        var seuil = window.innerHeight * 0.92;
        var observateur = new IntersectionObserver(function (entrees) {
            entrees.forEach(function (entree) {
                if (entree.isIntersecting) {
                    entree.target.classList.add("visible");
                    observateur.unobserve(entree.target);
                }
            });
        }, { rootMargin: "0px 0px -8% 0px", threshold: 0.06 });
        var rang = 0;
        cibles.forEach(function (cible) {
            if (cible.getBoundingClientRect().top < seuil) return; // déjà visible : l'animation d'entrée habituelle suffit
            cible.classList.add("reveal");
            if (cible.parentElement && cible.parentElement.classList.contains("vitrine-grille")) {
                cible.style.transitionDelay = ((rang++ % 3) * 70) + "ms"; // cascade des cartes d'une même rangée
            }
            observateur.observe(cible);
        });
        window.addEventListener("beforeprint", function () {
            document.querySelectorAll(".reveal").forEach(function (element) { element.classList.add("visible"); });
        });
    }

    // --- Bascule clair / sombre en douceur ----------------------------------------------------------------
    var boutonTheme = document.querySelector("[data-bouton-theme]");
    if (boutonTheme && !reduit) {
        boutonTheme.addEventListener("click", function () {
            racine.classList.add("bascule-theme");
            setTimeout(function () { racine.classList.remove("bascule-theme"); }, 500);
        });
    }
})();


/* Menu du compte : se referme au clic ailleurs, avec Échap, et après le choix du thème. */
(function () {
    "use strict";
    var menu = document.querySelector("[data-menu-compte]");
    if (!menu) return;
    document.addEventListener("click", function (evenement) {
        if (menu.open && !menu.contains(evenement.target)) menu.open = false;
    });
    document.addEventListener("keydown", function (evenement) {
        if (evenement.key !== "Escape" || !menu.open) return;
        menu.open = false;
        var declencheur = menu.querySelector("summary");
        if (declencheur) declencheur.focus();
    });
    menu.addEventListener("click", function (evenement) {
        if (evenement.target.closest && evenement.target.closest("[data-bouton-theme]")) {
            setTimeout(function () { menu.open = false; }, 380); // le temps de voir le thème changer
        }
    });
})();


/* Messages aux familles : des boutons ajoutent « le nom de l'élève », « la classe »... dans le message ; l'application remplace
   chaque mot pour chaque famille (voir communication/diffusion.py). Le bouton « Montant dû » ne sert qu'à la relance de scolarité. */
(function () {
    "use strict";
    var conteneur = document.querySelector("[data-mots-a-inserer]");
    if (!conteneur) return;
    var champ = document.getElementById(conteneur.dataset.cibleInsertion);
    if (!champ) return;
    conteneur.hidden = false;
    var selecteurType = document.getElementById(conteneur.dataset.selecteurType);

    function afficherSelonLeType() {
        var type = selecteurType ? selecteurType.value : "";
        conteneur.querySelectorAll("[data-types]").forEach(function (bouton) {
            bouton.hidden = bouton.dataset.types.split(" ").indexOf(type) === -1;
        });
    }
    if (selecteurType) selecteurType.addEventListener("change", afficherSelonLeType);
    afficherSelonLeType();

    conteneur.addEventListener("click", function (evenement) {
        var bouton = evenement.target.closest("[data-inserer-mot]");
        if (!bouton) return;
        var mot = bouton.dataset.insererMot;
        var valeur = champ.value;
        var debut = typeof champ.selectionStart === "number" ? champ.selectionStart : valeur.length;
        var fin = typeof champ.selectionEnd === "number" ? champ.selectionEnd : debut;
        // Les espaces nécessaires sont ajoutés pour la personne : « Bonjour,{eleve}rendez-vous » deviendrait illisible.
        var avant = debut > 0 ? valeur.charAt(debut - 1) : "";
        var apres = fin < valeur.length ? valeur.charAt(fin) : "";
        var texte = (avant && !/[\s(«'"]/.test(avant) ? " " : "") + mot + (apres && !/[\s.,;:!?)»]/.test(apres) ? " " : "");
        var nouvelle = valeur.slice(0, debut) + texte + valeur.slice(fin);
        champ.focus();
        if (champ.maxLength > 0 && nouvelle.length > champ.maxLength) return; // message déjà trop long : rien ne change
        champ.value = nouvelle;
        champ.setSelectionRange(debut + texte.length, debut + texte.length);
    });
})();


// Finition de l'interface : sections du menu repliables et mémorisées, bouton « œil » des mots de passe, libellés des
// tableaux en cartes sur téléphone, état annoncé du menu mobile.
document.addEventListener("DOMContentLoaded", function () {
    var CLE_MENU = "nexora-menu-replie";
    function lireReplies() {
        try { return JSON.parse(localStorage.getItem(CLE_MENU) || "[]"); } catch (erreur) { return []; }
    }
    function ecrireReplies(liste) {
        try { localStorage.setItem(CLE_MENU, JSON.stringify(liste)); } catch (erreur) { /* navigation privée : pas de mémoire */ }
    }
    var replies = lireReplies();
    document.querySelectorAll("details.nav-section").forEach(function (section) {
        var identifiant = section.getAttribute("data-nav-section");
        // La section de la page affichée reste toujours ouverte, même si elle avait été repliée.
        if (replies.indexOf(identifiant) !== -1 && !section.querySelector(".nav-lien.actif")) section.removeAttribute("open");
        section.addEventListener("toggle", function () {
            var liste = lireReplies().filter(function (autre) { return autre !== identifiant; });
            if (!section.open) liste.push(identifiant);
            ecrireReplies(liste);
        });
    });

    var boutonMenu = document.querySelector(".bouton-menu-mobile");
    var barre = document.getElementById("sidebar");
    var rideauMenu = document.getElementById("sidebar-rideau");
    function annoncerMenu() {
        if (boutonMenu && barre) boutonMenu.setAttribute("aria-expanded", barre.classList.contains("ouvert") ? "true" : "false");
    }
    if (boutonMenu) boutonMenu.addEventListener("click", annoncerMenu);
    if (rideauMenu) rideauMenu.addEventListener("click", annoncerMenu);

    var OEIL = '<svg xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
    var OEIL_BARRE = '<svg xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
    document.querySelectorAll('input[type="password"]').forEach(function (champ) {
        if (champ.hasAttribute("data-sans-oeil") || champ.closest(".champ-mot-de-passe")) return;
        var enveloppe = document.createElement("div");
        enveloppe.className = "champ-mot-de-passe";
        champ.parentNode.insertBefore(enveloppe, champ);
        enveloppe.appendChild(champ);
        var bouton = document.createElement("button");
        bouton.type = "button";
        bouton.className = "bouton-oeil";
        bouton.setAttribute("aria-label", t("Afficher le mot de passe"));
        bouton.setAttribute("aria-pressed", "false");
        bouton.innerHTML = OEIL;
        bouton.addEventListener("click", function () {
            var visible = champ.type === "password";
            champ.type = visible ? "text" : "password";
            bouton.setAttribute("aria-pressed", visible ? "true" : "false");
            bouton.setAttribute("aria-label", visible ? t("Masquer le mot de passe") : t("Afficher le mot de passe"));
            bouton.innerHTML = visible ? OEIL_BARRE : OEIL;
            champ.focus();
        });
        enveloppe.appendChild(bouton);
    });

    // Tableaux de liste (class="table-cartes") : sur téléphone chaque ligne devient une carte ; le libellé de chaque
    // valeur est celui de son en-tête de colonne. Une colonne « Actions » (ou sans titre) n'a pas de libellé.
    document.querySelectorAll("table.table-cartes").forEach(function (tableau) {
        var entetes = Array.prototype.map.call(tableau.querySelectorAll("thead tr:last-child th"), function (th) {
            return th.textContent.trim();
        });
        tableau.querySelectorAll("tbody tr").forEach(function (ligne) {
            Array.prototype.forEach.call(ligne.children, function (cellule, i) {
                if (cellule.tagName !== "TD" || cellule.colSpan > 1) return;
                var libelle = entetes[i] || "";
                if (libelle === "Actions") libelle = "";
                cellule.setAttribute("data-label", libelle);
                if (!libelle) cellule.classList.add("cellule-actions");
                if (!cellule.children.length && !cellule.textContent.trim()) { cellule.classList.add("cellule-vide"); return; }
                var valeur = document.createElement("div");
                valeur.className = "cellule-valeur";
                while (cellule.firstChild) valeur.appendChild(cellule.firstChild);
                cellule.appendChild(valeur);
            });
        });
    });
});


/* ========================================================================
   Bouton « Installer l'application » (phase 66).
   Le navigateur décide si l'installation est possible : Chrome, Edge, Samsung Internet (Android et ordinateur) envoient
   « beforeinstallprompt », qu'on garde pour l'ouvrir au clic ; Safari sur iPhone et iPad n'a pas cet évènement, on montre
   alors une aide en trois gestes. Le bouton reste caché dans les autres cas et dès que l'application est déjà installée.
   ======================================================================== */
(function () {
    var boutons = document.querySelectorAll("[data-installer]");
    if (!boutons.length) { return; }
    var dejaInstallee = (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
        window.navigator.standalone === true;
    if (dejaInstallee) { return; }

    var invite = null;
    function afficher(oui) {
        boutons.forEach(function (bouton) { bouton.hidden = !oui; });
    }
    var surApple = /iphone|ipad|ipod/i.test(navigator.userAgent) ||
        (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    if (surApple) { afficher(true); }

    window.addEventListener("beforeinstallprompt", function (evenement) {
        evenement.preventDefault();
        invite = evenement;
        afficher(true);
    });
    window.addEventListener("appinstalled", function () {
        invite = null;
        afficher(false);
    });
    boutons.forEach(function (bouton) {
        bouton.addEventListener("click", function () {
            if (invite) {
                var proposition = invite;
                invite = null;
                afficher(false);
                proposition.prompt();
                return;
            }
            var aide = document.getElementById("installer-aide");
            if (!aide) { return; }
            if (aide.showModal) { aide.showModal(); } else { aide.setAttribute("open", ""); }
        });
    });
})();
