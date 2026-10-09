// Service worker minimal : rend l'application installable (critère navigateur)
// et accélère le chargement des fichiers statiques (CSS/JS/icônes).
// Seules les pages de saisie listées ci-dessous (REGEX_PAGES_HORS_LIGNE)
// sont mises en cache - toutes les autres pages dynamiques (paiements,
// emplois du temps, bulletins...) viennent toujours du réseau, jamais
// d'une copie locale potentiellement obsolète.

var CACHE_NOM = "statique-v1";

// Pages de saisie volontairement rendues disponibles hors-ligne (voir
// app.js) : mises en cache après chaque visite en ligne (network-first),
// pour que l'enseignant puisse encore ouvrir le formulaire si le réseau
// tombe pendant le cours. Aucune autre page dynamique n'est concernée.
var CACHE_PAGES = "pages-hors-ligne-v1";
var REGEX_PAGES_HORS_LIGNE = [
    /^\/pedagogie\/absences\/classe\/\d+\/saisir\/$/,
    /^\/pedagogie\/notes\/affectation\/\d+\/saisir\/$/,
];
var CACHES_VALIDES = [CACHE_NOM, CACHE_PAGES];

var NOM_BASE_HORS_LIGNE = "hors-ligne-v1";
var NOM_MAGASIN_HORS_LIGNE = "saisies-en-attente";

self.addEventListener("install", function (evenement) {
    self.skipWaiting();
});

self.addEventListener("activate", function (evenement) {
    evenement.waitUntil(
        caches.keys().then(function (noms) {
            return Promise.all(
                noms.filter(function (nom) { return CACHES_VALIDES.indexOf(nom) === -1; })
                    .map(function (nom) { return caches.delete(nom); })
            );
        }).then(function () { return self.clients.claim(); })
    );
});

self.addEventListener("fetch", function (evenement) {
    var requete = evenement.request;
    var chemin = new URL(requete.url).pathname;

    // Appareil partagé : les pages de saisie en cache contiennent des noms d'élèves et resteraient
    // lisibles hors-ligne par la personne suivante. On les efface à la déconnexion, et dès que la
    // page de connexion est demandée (session expirée sans déconnexion explicite).
    if (
        (requete.method === "POST" && chemin === "/comptes/deconnexion/") ||
        (requete.method === "GET" && chemin === "/comptes/connexion/")
    ) {
        evenement.waitUntil(caches.delete(CACHE_PAGES));
        return;
    }

    var estPageHorsLigne = REGEX_PAGES_HORS_LIGNE.some(function (regex) { return regex.test(chemin); });
    if (requete.method === "GET" && estPageHorsLigne) {
        evenement.respondWith(
            fetch(requete).then(function (reponseReseau) {
                if (reponseReseau && reponseReseau.status === 200) {
                    // waitUntil, pas juste .then() en fire-and-forget : sans ça, le
                    // navigateur peut considérer l'évènement terminé dès que la
                    // réponse réseau est rendue et suspendre le service worker
                    // avant la fin réelle de l'écriture dans le cache.
                    var copie = reponseReseau.clone();
                    evenement.waitUntil(
                        caches.open(CACHE_PAGES).then(function (cache) { return cache.put(requete, copie); })
                    );
                }
                return reponseReseau;
            }).catch(function () {
                return caches.open(CACHE_PAGES).then(function (cache) { return cache.match(requete); });
            })
        );
        return;
    }

    if (requete.method !== "GET" || chemin.indexOf("/static/") !== 0) {
        return;
    }
    evenement.respondWith(
        caches.open(CACHE_NOM).then(function (cache) {
            return cache.match(requete).then(function (reponseEnCache) {
                var reseau = fetch(requete).then(function (reponseReseau) {
                    if (reponseReseau && reponseReseau.status === 200) {
                        cache.put(requete, reponseReseau.clone());
                    }
                    return reponseReseau;
                }).catch(function () { return reponseEnCache; });
                return reponseEnCache || reseau;
            });
        })
    );
});

// Synchronisation en arrière-plan (Background Sync, surtout Chrome/Android) :
// rejoue la file de saisies hors-ligne (absences, notes...) même si aucun
// onglet n'est ouvert. Complète (ne remplace pas) la synchronisation
// déclenchée par la page elle-même au retour du réseau (voir app.js) - les
// deux sont sans risque l'une pour l'autre car chaque type de saisie
// couvert par ce mécanisme est idempotent côté serveur.
self.addEventListener("sync", function (evenement) {
    if (evenement.tag !== "synchroniser-saisies-hors-ligne") return;
    evenement.waitUntil(
        synchroniserDepuisLeServiceWorker().then(function () {
            return self.clients.matchAll().then(function (clients) {
                clients.forEach(function (client) { client.postMessage("file-hors-ligne-mise-a-jour"); });
            });
        })
    );
});

function synchroniserDepuisLeServiceWorker() {
    return new Promise(function (resoudre) {
        var requeteOuverture = indexedDB.open(NOM_BASE_HORS_LIGNE, 1);
        requeteOuverture.onupgradeneeded = function () {
            requeteOuverture.result.createObjectStore(NOM_MAGASIN_HORS_LIGNE, { keyPath: "cle" });
        };
        requeteOuverture.onerror = function () { resoudre(); };
        requeteOuverture.onsuccess = function () {
            var base = requeteOuverture.result;
            base.transaction(NOM_MAGASIN_HORS_LIGNE, "readonly")
                .objectStore(NOM_MAGASIN_HORS_LIGNE).getAll().onsuccess = function (evenementLecture) {
                var saisies = evenementLecture.target.result;
                function suivante(index) {
                    if (index >= saisies.length) { resoudre(); return; }
                    var saisie = saisies[index];
                    var donnees = new FormData();
                    saisie.champs.forEach(function (paire) { donnees.append(paire[0], paire[1]); });
                    fetch(saisie.url, {
                        method: "POST", body: donnees, credentials: "same-origin",
                        headers: { "X-Requested-With": "XMLHttpRequest" },
                    }).then(function (reponse) {
                        // Session expirée (redirection vers la connexion) : on
                        // laisse la saisie en file, on retentera plus tard.
                        if (reponse.redirected) { suivante(index + 1); return; }
                        // Réponse obtenue (succès ou erreur de validation) :
                        // retenter indéfiniment ne servirait à rien, on retire.
                        base.transaction(NOM_MAGASIN_HORS_LIGNE, "readwrite")
                            .objectStore(NOM_MAGASIN_HORS_LIGNE).delete(saisie.cle);
                        suivante(index + 1);
                    }).catch(function () { resoudre(); });
                }
                suivante(0);
            };
        };
    });
}
