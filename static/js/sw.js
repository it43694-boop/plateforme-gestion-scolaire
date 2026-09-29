// Service worker minimal : rend l'application installable (critère navigateur)
// et accélère le chargement des fichiers statiques (CSS/JS/icônes).
// Ne met JAMAIS en cache les pages HTML ni les requêtes dynamiques : les
// notes, paiements, emplois du temps etc. doivent toujours venir du réseau,
// jamais d'une copie locale potentiellement obsolète.

var CACHE_NOM = "statique-v1";

self.addEventListener("install", function (evenement) {
    self.skipWaiting();
});

self.addEventListener("activate", function (evenement) {
    evenement.waitUntil(
        caches.keys().then(function (noms) {
            return Promise.all(
                noms.filter(function (nom) { return nom !== CACHE_NOM; })
                    .map(function (nom) { return caches.delete(nom); })
            );
        }).then(function () { return self.clients.claim(); })
    );
});

self.addEventListener("fetch", function (evenement) {
    var requete = evenement.request;
    if (requete.method !== "GET" || new URL(requete.url).pathname.indexOf("/static/") !== 0) {
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
