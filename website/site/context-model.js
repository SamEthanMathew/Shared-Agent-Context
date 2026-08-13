/* Private notes, one shared project.
   ---------------------------------------------------------------------------
   Shows the thing that is hardest to explain in prose: each account reads what
   the project shares plus its OWN private notes, and never the other person's.

   Accuracy note that shapes this component: a private note is never "promoted"
   into the shared project. Publishing and noting privately are separate acts —
   the assistant sends each piece of knowledge to one place or the other, and
   nothing migrates between them afterwards. Mirroring the real data model
   matters more here than a prettier animation would.

   The status line is read aloud by screen readers, so it says what happened in
   the same words the page uses. It deliberately avoids naming the machinery
   underneath — the visitor is deciding whether to trust this, not maintain it. */
(function () {
  "use strict";

  var root = document.getElementById("scope-model");
  if (!root) return;

  var zoneA   = document.getElementById("zone-a");
  var zoneB   = document.getElementById("zone-b");
  var shared  = document.getElementById("zone-shared");
  var status  = document.getElementById("ctx-status");
  var viewA   = document.getElementById("ctx-view-a");
  var viewB   = document.getElementById("ctx-view-b");
  var cardA   = root.querySelector('[data-zone="a"]');
  var cardB   = root.querySelector('[data-zone="b"]');

  /* Queued so repeated clicks stay meaningful rather than repeating one line. */
  var SHARED_QUEUE = [
    { kind: "finding",    text: "Upstream rate limit is 100 req/min per key" },
    { kind: "decision",   text: "Retries use exponential backoff, max 3" },
    { kind: "constraint", text: "No PII in log lines, ever" },
    { kind: "result",     text: "Migration 0007 ran clean on staging" }
  ];
  var PRIVATE_QUEUE = [
    { kind: "note", text: "Ask Matthew why the staging seed differs" },
    { kind: "note", text: "My hunch: the flake is a timezone bug" },
    { kind: "note", text: "Draft reply to the vendor — not ready to share" }
  ];

  var sharedI = 0, privateI = 0;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }

  function makeMem(item, scope, source) {
    var li = el("li", "mem mem--" + scope);
    li.setAttribute("data-new", "true");
    li.appendChild(el("span", "mem__kind", item.kind));
    li.appendChild(document.createTextNode(item.text));
    if (source) li.appendChild(el("span", "mem__src", source));
    return li;
  }

  function say(msg) { if (status) status.textContent = msg; }

  function publishShared() {
    var item = SHARED_QUEUE[sharedI % SHARED_QUEUE.length];
    sharedI++;
    shared.appendChild(makeMem(item, "shared", "Person A"));
    say("Person A published a " + item.kind + " to the shared project. " +
        "Person B's assistant has it from here on, with no message sent.");
  }

  function savePrivate() {
    var item = PRIVATE_QUEUE[privateI % PRIVATE_QUEUE.length];
    privateI++;
    zoneA.appendChild(makeMem(item, "private"));
    say("Saved as one of Person A's private notes. Nothing about the shared " +
        "project changed, and Person B never receives it.");
  }

  function setViewer(who) {
    var current = root.getAttribute("data-viewer");
    var next = current === who ? "none" : who;
    root.setAttribute("data-viewer", next);

    viewA.setAttribute("aria-pressed", String(next === "a"));
    viewB.setAttribute("aria-pressed", String(next === "b"));

    cardA.setAttribute("data-hidden", String(next === "b"));
    cardB.setAttribute("data-hidden", String(next === "a"));
    cardA.setAttribute("data-reading", String(next === "a"));
    cardB.setAttribute("data-reading", String(next === "b"));

    var lockA = cardA.querySelector(".scope__lock");
    var lockB = cardB.querySelector(".scope__lock");
    if (lockA) lockA.hidden = next !== "b";
    if (lockB) lockB.hidden = next !== "a";

    if (next === "a") {
      say("Person A's assistant reads the shared project plus Person A's own notes. " +
          "Person B's private notes never reach it at all.");
    } else if (next === "b") {
      say("Person B's assistant reads the shared project plus Person B's own notes. " +
          "Person A's private notes never reach it at all.");
    } else {
      say("Both accounts read the shared project. Neither can read the other's private notes.");
    }
  }

  function reset() {
    root.setAttribute("data-viewer", "none");
    setViewer("none");
    sharedI = privateI = 0;
    [].slice.call(root.querySelectorAll('.mem[data-new="true"]')).forEach(function (n) {
      n.parentNode.removeChild(n);
    });
    say("Reset. Both accounts read the shared project; neither can read the other's private notes.");
  }

  document.getElementById("ctx-publish").addEventListener("click", publishShared);
  document.getElementById("ctx-private").addEventListener("click", savePrivate);
  document.getElementById("ctx-reset").addEventListener("click", reset);
  viewA.addEventListener("click", function () { setViewer("a"); });
  viewB.addEventListener("click", function () { setViewer("b"); });
})();
