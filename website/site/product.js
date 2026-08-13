/* Two product surfaces made touchable: the sharing dials, and the app preview.
   ---------------------------------------------------------------------------
   Accuracy notes that shape both, taken from the real behaviour:

   * The three sharing dials are independent and additive. Nothing is a
     hierarchy — a link grant does not "upgrade" a person grant, and removing
     one does not remove another.
   * Neither the link dial nor the organisation dial can ever grant manage.
     Manage carries the right to re-share, so it stays a per-person decision.
     The UI here therefore offers view/edit only on those two, which is not a
     simplification for the demo — it is the actual constraint.
   * The organisation dial defaults to no access. Creating a group and moving a
     context into it grants nothing until someone sets that dial.
   * "What AI saw" records are private to the person whose agent made the call,
     and report the count of other people's withheld private memories without
     naming them or their contents. */
(function () {
  "use strict";

  /* --- sharing dials ----------------------------------------------------- */

  var dials = document.getElementById("dials");
  if (dials) {
    var state = { people: "invited", link: "none", org: "none" };

    var out = document.getElementById("who-list");
    var note = document.getElementById("who-note");

    function row(name, sub, level) {
      var li = document.createElement("li");
      li.className = "who__row";
      li.setAttribute("data-level", level);

      var main = document.createElement("span");
      main.className = "approw__main";
      var strong = document.createElement("strong");
      strong.style.fontWeight = "600";
      strong.textContent = name;
      main.appendChild(strong);
      if (sub) {
        var s = document.createElement("span");
        s.className = "ctx-card__meta";
        s.textContent = " — " + sub;
        main.appendChild(s);
      }

      var lvl = document.createElement("span");
      lvl.className = "who__level";
      lvl.textContent = level;

      li.appendChild(main);
      li.appendChild(lvl);
      return li;
    }

    function render() {
      out.textContent = "";
      out.appendChild(row("You", "created this context", "owner"));

      if (state.people === "invited" || state.people === "manage") {
        out.appendChild(
          row("Priya", "invited by email", state.people === "manage" ? "manage" : "edit")
        );
      }
      if (state.link !== "none") {
        out.appendChild(row("Anyone with the link", "no invitation needed", state.link));
      }
      if (state.org !== "none") {
        out.appendChild(row("Everyone in Northwind", "your organisation", state.org));
      }

      var lines = [];
      if (state.link === "none" && state.org === "none") {
        lines.push("Restricted: only the people you invited by name.");
      }
      if (state.link !== "none") {
        lines.push(
          "A link can grant view or edit, never manage — passing on the right " +
          "to re-share stays a decision a named person makes."
        );
      }
      if (state.org !== "none") {
        lines.push(
          "Organisation access is off until you set it here, and it can never " +
          "grant manage either. An invitation someone already has outranks it, " +
          "so removing them from the group does not take that away."
        );
      }
      note.textContent = lines.join(" ");
    }

    [].forEach.call(dials.querySelectorAll(".dial__opt"), function (btn) {
      btn.addEventListener("click", function () {
        var dial = btn.getAttribute("data-dial");
        state[dial] = btn.getAttribute("data-value");
        [].forEach.call(
          dials.querySelectorAll('.dial__opt[data-dial="' + dial + '"]'),
          function (sib) {
            sib.setAttribute("aria-pressed", String(sib === btn));
          }
        );
        render();
      });
    });

    render();
  }

  /* --- app preview tabs -------------------------------------------------- */

  var win = document.getElementById("appwin");
  if (!win) return;

  var tabs = [].slice.call(win.querySelectorAll(".apptab"));
  var panels = [].slice.call(win.querySelectorAll(".apppanel"));

  function select(key) {
    tabs.forEach(function (t) {
      t.setAttribute("aria-selected", String(t.getAttribute("data-tab") === key));
      t.tabIndex = t.getAttribute("data-tab") === key ? 0 : -1;
    });
    panels.forEach(function (p) {
      p.hidden = p.getAttribute("data-panel") !== key;
    });
  }

  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () { select(t.getAttribute("data-tab")); });
    /* Arrow keys, because this is a real tablist and screen-reader users will
       expect it to behave like one. */
    t.addEventListener("keydown", function (e) {
      var next = null;
      if (e.key === "ArrowRight") next = tabs[(i + 1) % tabs.length];
      if (e.key === "ArrowLeft") next = tabs[(i - 1 + tabs.length) % tabs.length];
      if (!next) return;
      e.preventDefault();
      select(next.getAttribute("data-tab"));
      next.focus();
    });
  });
})();
