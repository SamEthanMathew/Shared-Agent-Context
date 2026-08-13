/* Osmos Moment — the interactive cross-agent context handoff.
   ---------------------------------------------------------------------------
   The logo's white axis is the shared project layer. A decision leaves the
   source agent, travels the axis, increments the project revision, and arrives
   at a second agent in a different account and model.

   Colour appears only while knowledge is moving. That is the brand rule, and
   here it is also the argument.

   Honours prefers-reduced-motion by rendering the completed end state with no
   animation — the same information, held still. */
(function () {
  "use strict";

  var root = document.getElementById("osmos-moment");
  if (!root) return;

  var revEl    = document.getElementById("moment-rev");
  var destEl   = document.getElementById("moment-dest");
  var chipEl   = document.getElementById("moment-chip");
  var chipText = document.getElementById("moment-chip-text");
  var statusEl = document.getElementById("moment-status");
  var replayEl = document.getElementById("moment-replay");
  var onBtn    = document.getElementById("moment-on");
  var offBtn   = document.getElementById("moment-off");
  var destCard = root.querySelector('[data-role="dest"]');

  var FLOW = ["--osmos-violet-500", "--osmos-violet-400", "--osmos-indigo-400",
              "--osmos-blue-400", "--osmos-aqua-400"];

  var HANDOFF = 900;   /* matches --t-handoff */
  var timers = [];

  var ASK      = 'Asks: "Build the messages endpoint."';
  var ANSWER   = 'Since this project uses <em>opaque cursor pagination</em>, the endpoint takes a <em>cursor</em> and returns <em>next_cursor</em> — not offset and limit.';
  var GUESSED  = 'Returns <em>offset</em> and <em>limit</em>. Reasonable default, wrong for this project — and nobody notices until review.';

  function reduced() {
    try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
    catch (e) { return false; }
  }

  function clearTimers() {
    timers.forEach(clearTimeout);
    timers = [];
  }
  function later(fn, ms) { timers.push(setTimeout(fn, ms)); }

  function say(msg) { if (statusEl) statusEl.textContent = msg; }

  /* ---- States ----------------------------------------------------------- */

  function reset() {
    clearTimers();
    root.setAttribute("data-phase", "idle");
    root.style.setProperty("--pulse-color", "var(" + FLOW[0] + ")");
    revEl.textContent = "r41";
    revEl.removeAttribute("data-bump");
    destEl.innerHTML = ASK;
    destEl.classList.add("agent__msg--empty");
    destEl.removeAttribute("data-arrived");
    destCard.setAttribute("data-active", "false");
    chipEl.setAttribute("data-visible", "false");
  }

  /* The counter flips rather than fading. It is a counter, and a counter that
     cross-fades reads as a value being corrected instead of advanced.

     It is the only place a revision number appears on the site: here it is
     motion — visible proof that something landed — rather than a concept the
     reader has to learn before they can buy anything. Nothing in the copy
     explains it, and nothing should. */
  function bumpRev(value) {
    revEl.setAttribute("data-bump", "true");
    later(function () { revEl.textContent = value; }, 180);
    later(function () { revEl.removeAttribute("data-bump"); }, 560);
  }

  /* The end state: what the visitor is meant to understand. */
  function settle(withOsmos, animate) {
    revEl.textContent = withOsmos ? "r42" : "r41";
    destEl.innerHTML = withOsmos ? ANSWER : GUESSED;
    destEl.classList.remove("agent__msg--empty");
    if (animate) destEl.setAttribute("data-arrived", "true");
    else destEl.removeAttribute("data-arrived");
    destCard.setAttribute("data-active", withOsmos ? "true" : "false");
    chipEl.setAttribute("data-visible", withOsmos ? "true" : "false");
    if (withOsmos && chipText) chipText.textContent = "Used from Osmos · Sam / ChatGPT";
    root.setAttribute("data-phase", withOsmos ? "done" : "idle");
    say(withOsmos
      ? "Handoff complete — Sam's ChatGPT to Matthew's Claude."
      : "No shared project. The second assistant guessed.");
  }

  function play() {
    var withOsmos = root.getAttribute("data-mode") === "with";
    reset();

    if (!withOsmos) { settle(false, false); return; }

    if (reduced()) { settle(true, false); return; }

    /* A short capture beat before the pulse leaves. Without it the decision
       appears to originate on the axis rather than in the conversation. */
    say("Sam's assistant publishes the decision…");
    root.setAttribute("data-phase", "capture");

    later(function () {
      root.setAttribute("data-phase", "travel");

      /* Traverse violet -> aqua while the pulse crosses the axis. */
      var step = HANDOFF / FLOW.length;
      FLOW.forEach(function (token, i) {
        later(function () {
          root.style.setProperty("--pulse-color", "var(" + token + ")");
        }, i * step);
      });

      later(function () { bumpRev("r42"); say("Recorded in the shared project."); }, HANDOFF * 0.55);
      later(function () { settle(true, true); }, HANDOFF);
    }, 320);
  }

  function setMode(mode) {
    root.setAttribute("data-mode", mode);
    onBtn.setAttribute("aria-pressed", String(mode === "with"));
    offBtn.setAttribute("aria-pressed", String(mode === "without"));
    play();
  }

  /* ---- Wiring ----------------------------------------------------------- */

  replayEl.addEventListener("click", play);
  onBtn.addEventListener("click", function () { setMode("with"); });
  offBtn.addEventListener("click", function () { setMode("without"); });

  reset();
  say("Ready");

  /* Play once when it first scrolls into view; never replay unprompted —
     repeated motion the visitor didn't ask for is noise, not explanation. */
  if ("IntersectionObserver" in window) {
    var seen = false;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !seen) {
          seen = true;
          later(play, 260);
          io.disconnect();
        }
      });
    }, { threshold: 0.4 });
    io.observe(root);
  } else {
    play();
  }
})();
