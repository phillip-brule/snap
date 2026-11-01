/* Page-to-page reaction flash: pop in, hold, fade, then navigate. */
(function () {
  var REACTIONS = [
    "inspo/reactions/reaction_1.jpg",
    "inspo/reactions/Reaction_2.jpg",
    "inspo/reactions/reaction_3.jpg",
    "inspo/reactions/reaction_4.jpg",
    "inspo/reactions/reaction_5.jpg",
    "inspo/reactions/reaction_6.jpg",
    "inspo/reactions/reaction_7.jpg",
    "inspo/reactions/reaction_8.jpg",
    "inspo/reactions/reaction_9.jpg",
    "inspo/reactions/reaction_10.jpg",
    "inspo/reactions/reaction_11.jpg",
    "inspo/reactions/reaction_12.png",
    "inspo/reactions/reaction_13.jpg"
  ];

  var HOLD_MS = 280;
  var FADE_MS = 520;
  var navigating = false;

  function staticUrl(path) {
    var root = document.body.getAttribute("data-static") || "/static/";
    if (root.slice(-1) !== "/") root += "/";
    return root + path;
  }

  function overlay() {
    var el = document.getElementById("reaction-flash");
    if (el) return el;
    el = document.createElement("div");
    el.id = "reaction-flash";
    el.setAttribute("aria-hidden", "true");
    var img = document.createElement("img");
    img.alt = "";
    el.appendChild(img);
    document.body.appendChild(el);
    return el;
  }

  function pickReaction(forced) {
    if (forced) return forced;
    return REACTIONS[Math.floor(Math.random() * REACTIONS.length)];
  }

  function flashThen(go, forced) {
    if (navigating) return;
    navigating = true;
    var el = overlay();
    var img = el.querySelector("img");
    img.src = staticUrl(pickReaction(forced));
    el.classList.add("is-on");
    window.setTimeout(function () {
      el.classList.remove("is-on");
      window.setTimeout(go, FADE_MS);
    }, HOLD_MS);
  }

  function sameOriginNav(a) {
    if (!a || a.target === "_blank" || a.hasAttribute("download")) return false;
    var href = a.getAttribute("href");
    if (!href || href.charAt(0) === "#" || href.indexOf("mailto:") === 0) return false;
    try {
      var url = new URL(a.href, window.location.href);
      return url.origin === window.location.origin;
    } catch (e) {
      return false;
    }
  }

  document.addEventListener("click", function (ev) {
    if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) {
      return;
    }
    var a = ev.target.closest("a");
    if (!sameOriginNav(a)) return;
    if (a.href === window.location.href) return;
    ev.preventDefault();
    var forced = a.getAttribute("data-reaction");
    flashThen(function () {
      window.location.href = a.href;
    }, forced);
  });

  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!form || form.tagName !== "FORM") return;
    if (form.getAttribute("data-no-flash") != null) return;
    ev.preventDefault();
    var forced = form.getAttribute("data-reaction");
    flashThen(function () {
      HTMLFormElement.prototype.submit.call(form);
    }, forced);
  });

  // Autoplay media on detail pages (was inline; kept external for CSP script-src 'self')
  var player = document.getElementById("snap-player");
  if (player && player.play) {
    var tryPlay = player.play();
    if (tryPlay && tryPlay.catch) {
      tryPlay.catch(function () {
        player.muted = true;
        return player.play();
      });
    }
  }
})();
