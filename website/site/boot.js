/* Theme before paint, the data-js flag the reveal styles depend on, and the one
   listener behind every [data-osmos-event] on the site.
   ---------------------------------------------------------------------------
   A file rather than an inline <script> because the app serves this site under
   `default-src 'self'`, which drops inline script entirely. Inlined, this would
   silently stop running in production: a light-theme visitor would get a dark
   flash, and every [data-reveal] section would stay hidden because nothing set
   data-js. Loaded synchronously from <head>, so it still runs before paint.

   If it fails anyway, nothing is hidden and the page reads normally. */
(function () {
  try {
    var t = localStorage.getItem("osmos-theme");
    if (!t) t = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", t);
    document.documentElement.setAttribute("data-js", "1");
  } catch (e) {}
})();

/* The [data-osmos-event] links, and where they go.
   ---------------------------------------------------------------------------
   The pages have carried these attributes since launch with nothing listening,
   so every one of them was a measurement nobody was taking. One delegated
   listener on `document` covers all of them, including anything added later —
   per-element listeners would have to be re-bound and would silently miss a new
   page's buttons.

   There is deliberately no vendor here. `default-src 'self'` blocks every
   external host outright, so a third-party tag would not load at all; and a
   site whose pitch is that nothing leaves has no business shipping a tracker to
   say so. The collector is therefore a same-origin path, named by the page:

       <meta name="osmos-analytics" content="/e">

   No meta tag means no collector, which is the state today: the listener still
   runs, finds nothing configured, and does nothing. Only a root-relative path is
   accepted — an absolute URL would be a third-party endpoint by another name,
   and the CSP would refuse the request anyway.

   The config is read on the first click rather than now, because this file is
   parsed in <head> before the <meta> exists. Everything is wrapped: a failure to
   count a click must never be able to stop the click. */
(function () {
  var url; // undefined = not looked up yet, null = nothing configured

  function collector() {
    if (url !== undefined) return url;
    url = null;
    try {
      var meta = document.querySelector('meta[name="osmos-analytics"]');
      var value = meta && meta.getAttribute("content");
      // Root-relative and not protocol-relative ("//host/path" is off-origin).
      if (value && value.charAt(0) === "/" && value.charAt(1) !== "/") url = value;
    } catch (e) {}
    return url;
  }

  function send(name) {
    var to = collector();
    if (!to) return;
    var body = JSON.stringify({
      event: name,
      path: location.pathname,
      at: new Date().toISOString()
    });
    // sendBeacon survives the navigation the click is about to cause; fetch
    // without keepalive would be cancelled as the page unloads. Neither carries
    // anything identifying — the event name and which page it happened on.
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon(to, new Blob([body], { type: "application/json" }));
      } else if (window.fetch) {
        fetch(to, {
          method: "POST",
          body: body,
          headers: { "Content-Type": "application/json" },
          keepalive: true
        }).catch(function () {});
      }
    } catch (e) {}
  }

  document.addEventListener("click", function (ev) {
    try {
      // Do Not Track and Global Privacy Control are honoured whatever the
      // collector is. Counting a button press is not worth contradicting the
      // page it is printed on.
      if (navigator.doNotTrack === "1" || navigator.globalPrivacyControl) return;
      var el = ev.target && ev.target.closest && ev.target.closest("[data-osmos-event]");
      if (!el) return;
      var name = el.getAttribute("data-osmos-event");
      if (name) send(name);
    } catch (e) {}
  });
})();
