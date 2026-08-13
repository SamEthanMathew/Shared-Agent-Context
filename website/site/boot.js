/* Theme before paint, and the data-js flag the reveal styles depend on.
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
