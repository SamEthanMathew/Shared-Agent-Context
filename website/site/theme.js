/* Osmos — theme toggle, nav scroll state, copy buttons.
   No dependencies. Every behaviour degrades to a working page without JS. */
(function () {
  "use strict";

  /* ---- Theme ------------------------------------------------------------ */
  var root = document.documentElement;
  var toggle = document.getElementById("theme-toggle");

  function setTheme(t) {
    root.setAttribute("data-theme", t);
    try { localStorage.setItem("osmos-theme", t); } catch (e) {}
    if (toggle) toggle.setAttribute("aria-label", t === "dark" ? "Switch to light theme" : "Switch to dark theme");
  }

  if (toggle) {
    setTheme(root.getAttribute("data-theme") || "dark");
    toggle.addEventListener("click", function () {
      setTheme(root.getAttribute("data-theme") === "dark" ? "light" : "dark");
    });
  }

  /* Follow the OS only while the visitor hasn't chosen explicitly. */
  try {
    var mq = window.matchMedia("(prefers-color-scheme: light)");
    var onChange = function (e) {
      if (localStorage.getItem("osmos-theme")) return;
      root.setAttribute("data-theme", e.matches ? "light" : "dark");
    };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
  } catch (e) {}

  /* ---- Nav: border appears once the page has scrolled ------------------- */
  var nav = document.getElementById("nav");
  if (nav) {
    var sync = function () { nav.setAttribute("data-scrolled", window.scrollY > 8 ? "true" : "false"); };
    sync();
    window.addEventListener("scroll", sync, { passive: true });
  }

  /* ---- Copy buttons ------------------------------------------------------ */
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var text = btn.getAttribute("data-copy");
      var done = function () {
        var original = btn.textContent;
        btn.textContent = "Copied";
        btn.setAttribute("data-copied", "true");
        setTimeout(function () {
          btn.textContent = original;
          btn.removeAttribute("data-copied");
        }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () {});
      } else {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); done(); } catch (e) {}
        document.body.removeChild(ta);
      }
    });
  });
})();
