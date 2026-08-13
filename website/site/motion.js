/* Page motion: one-time reveals, nav scrollspy, and counters.
   ---------------------------------------------------------------------------
   Three rules this file follows, in order of importance:

   1. Nothing here may be load-bearing. Every [data-reveal] element starts
      hidden only when <html data-js> is set, and that attribute is written by
      the inline head script — so a parse error here leaves a plain, complete
      page rather than a blank one.
   2. Reveals fire once and then stop being watched. A section that re-animates
      every time it scrolls past turns reading into a performance.
   3. prefers-reduced-motion is checked before anything animates, not patched
      afterwards — counters jump to their value, reveals resolve instantly. */
(function () {
  "use strict";

  var reduced = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;

  var supportsIO = "IntersectionObserver" in window;

  /* --- reveals ----------------------------------------------------------- */

  var revealed = document.querySelectorAll("[data-reveal]");

  /* Stagger siblings inside a group so a row of cards arrives as a row rather
     than four unrelated events. The index is capped: past the fourth item the
     delay stops being a rhythm and starts being a wait. */
  [].forEach.call(document.querySelectorAll("[data-reveal-group]"), function (group) {
    var i = 0;
    [].forEach.call(group.querySelectorAll("[data-reveal]"), function (child) {
      child.style.setProperty("--i", String(Math.min(i, 4)));
      i++;
    });
  });

  function show(el) {
    el.classList.add("is-in");
    if (el.hasAttribute("data-count-group")) countUp(el);
  }

  if (!supportsIO || reduced) {
    [].forEach.call(revealed, show);
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        show(entry.target);
        io.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });

    [].forEach.call(revealed, function (el) { io.observe(el); });
  }

  /* --- counters ---------------------------------------------------------- */

  function countUp(scope) {
    [].forEach.call(scope.querySelectorAll("[data-count]"), function (el) {
      var target = parseInt(el.getAttribute("data-count"), 10);
      if (isNaN(target)) return;
      var suffix = el.getAttribute("data-count-suffix") || "";
      /* Grouped, because the labels beside these read "3,000" and a bare 2140
         next to a 3,000 makes the reader do the comparison twice. */
      function fmt(n) { return n.toLocaleString("en-US") + suffix; }
      if (reduced) { el.textContent = fmt(target); return; }

      var started = null;
      var duration = 900;
      function frame(now) {
        if (started === null) started = now;
        var p = Math.min((now - started) / duration, 1);
        /* Ease-out: the number should land, not coast. */
        var eased = 1 - Math.pow(1 - p, 3);
        el.textContent = fmt(Math.round(target * eased));
        if (p < 1) requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    });
  }

  /* --- scrollspy --------------------------------------------------------- */

  var links = [].filter.call(
    document.querySelectorAll(".nav__link"),
    function (a) { return (a.getAttribute("href") || "").indexOf("#") === 0; }
  );

  if (links.length && supportsIO) {
    var byId = {};
    var sections = [];
    links.forEach(function (a) {
      var id = a.getAttribute("href").slice(1);
      var section = document.getElementById(id);
      if (!section) return;
      byId[id] = a;
      sections.push(section);
    });

    var visible = {};
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        visible[entry.target.id] = entry.isIntersecting;
      });
      /* The topmost visible section wins, so scrolling down never leaves two
         links lit at once. */
      var current = null;
      sections.forEach(function (s) {
        if (current === null && visible[s.id]) current = s.id;
      });
      links.forEach(function (a) {
        var id = a.getAttribute("href").slice(1);
        a.setAttribute("data-active", String(id === current));
      });
    }, { rootMargin: "-20% 0px -60% 0px" });

    sections.forEach(function (s) { spy.observe(s); });
  }
})();
