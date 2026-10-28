/* Bails Ledger — UI behaviour: entry dialog, theme, delete confirmation. */
(function () {
  "use strict";

  // ----------------------------- theme ----------------------------------
  var THEME_KEY = "bails-theme";

  function currentTheme() {
    var set = document.documentElement.getAttribute("data-theme");
    if (set) return set;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  var toggle = document.getElementById("themeToggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
      document.dispatchEvent(new CustomEvent("bails:themechange", { detail: { theme: next } }));
    });
  }

  // --------------------------- entry dialog ------------------------------
  var modal = document.getElementById("entryModal");
  if (!modal) return;

  var form = document.getElementById("entryForm");
  var title = document.getElementById("entryModalTitle");
  var submit = document.getElementById("entrySubmit");
  var categorySelect = document.getElementById("e-category");
  var groupIncome = document.getElementById("optIncome");
  var groupExpense = document.getElementById("optExpense");
  var createAction = form.getAttribute("action");

  function field(name) { return form.querySelector('[name="' + name + '"]'); }

  /* Show only the categories that belong to the chosen kind, so an expense can
     never be filed under an income category. */
  function syncCategories(kind, keepValue) {
    var isIncome = kind === "income";
    groupIncome.hidden = !isIncome;
    groupExpense.hidden = isIncome;
    Array.prototype.forEach.call(groupIncome.children, function (o) { o.disabled = !isIncome; });
    Array.prototype.forEach.call(groupExpense.children, function (o) { o.disabled = isIncome; });

    var allowed = Array.prototype.map.call(
      (isIncome ? groupIncome : groupExpense).children, function (o) { return o.value; });
    if (keepValue && allowed.indexOf(keepValue) !== -1) {
      categorySelect.value = keepValue;
    } else if (allowed.indexOf(categorySelect.value) === -1) {
      categorySelect.value = "";
    }
  }

  var watchmanField = document.getElementById("watchmanField");

  function setKind(kind, keepCategory) {
    var radio = form.querySelector('input[name="kind"][value="' + kind + '"]');
    if (radio) radio.checked = true;
    syncCategories(kind, keepCategory);
    submit.classList.toggle("btn--credit", kind === "income");
    submit.classList.toggle("btn--debit", kind === "expense");
    submit.classList.toggle("btn--primary", false);
    // The watchman (petty-cash) tag only applies to expenses.
    if (watchmanField) {
      var isExpense = kind === "expense";
      watchmanField.hidden = !isExpense;
      if (!isExpense) {
        var w = field("watchman_id");
        if (w) w.value = "";
      }
    }
    // On a new entry, keep the heading in step with the chosen type.
    if (form.getAttribute("action") === createAction) {
      title.textContent = kind === "expense" ? "New expense (debit)" : "New income (credit)";
    }
  }

  Array.prototype.forEach.call(form.querySelectorAll('input[name="kind"]'), function (radio) {
    radio.addEventListener("change", function () { setKind(radio.value, null); });
  });

  function open() {
    if (typeof modal.showModal === "function") modal.showModal();
    else modal.setAttribute("open", "");
  }

  function close() {
    if (typeof modal.close === "function") modal.close();
    else modal.removeAttribute("open");
  }

  function resetForCreate(kind) {
    form.setAttribute("action", createAction);
    form.reset();
    title.textContent = kind === "expense" ? "New expense (debit)" : "New income (credit)";
    submit.textContent = "Save entry";
    setKind(kind || "income", null);
    var dateField = field("txn_date");
    if (dateField && !dateField.value) dateField.value = new Date().toISOString().slice(0, 10);
  }

  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-open-entry]");
    if (opener) {
      resetForCreate(opener.getAttribute("data-kind") || "income");
      open();
      var amount = field("amount");
      if (amount) setTimeout(function () { amount.focus(); }, 60);
      return;
    }

    var editor = event.target.closest("[data-edit-entry]");
    if (editor) {
      var data = editor.dataset;
      form.setAttribute("action", "/transactions/" + data.id + "/edit");
      title.textContent = "Edit entry";
      submit.textContent = "Save changes";
      field("txn_date").value = data.date || "";
      field("amount").value = data.amount || "";
      field("description").value = data.description || "";
      field("slot").value = data.slot || "";
      field("party").value = data.party || "";
      field("notes").value = data.notes || "";
      setKind(data.kind || "income", data.category || "");
      var wsel = field("watchman_id");
      if (wsel) wsel.value = (data.kind === "expense" && data.watchman) ? data.watchman : "";
      open();
      return;
    }

    if (event.target.closest("[data-close-entry]")) close();
  });

  // Click on the backdrop (outside the form) closes the dialog.
  modal.addEventListener("click", function (event) {
    if (event.target === modal) close();
  });

  // ------------------------ destructive actions --------------------------
  document.addEventListener("submit", function (event) {
    var form = event.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.getAttribute("data-confirm"))) {
      event.preventDefault();
    }
  });
})();

/* Admin restore-from-backup dialog. Enables the destructive button only once
   the admin types RESTORE; the server re-checks it regardless. */
(function () {
  "use strict";
  var modal = document.getElementById("restoreModal");
  if (!modal) return;

  var confirmInput = document.getElementById("r-confirm");
  var submit = document.getElementById("restoreSubmit");

  function open() { if (modal.showModal) modal.showModal(); else modal.setAttribute("open", ""); }
  function close() { if (modal.close) modal.close(); else modal.removeAttribute("open"); }

  function syncButton() {
    submit.disabled = (confirmInput.value || "").trim().toUpperCase() !== "RESTORE";
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-open-restore]")) {
      var form = document.getElementById("restoreForm");
      if (form) form.reset();
      syncButton();
      open();
      return;
    }
    if (event.target.closest("[data-close-restore]")) close();
  });

  if (confirmInput) confirmInput.addEventListener("input", syncButton);
  modal.addEventListener("click", function (event) { if (event.target === modal) close(); });
})();


/* Ground ledger sellers grid: live remaining + totals as the admin edits. */
(function () {
  "use strict";
  var form = document.getElementById("sellersForm");
  if (!form) return;
  var cur = (document.body.getAttribute("data-currency") || "\u20b9");
  var num = function (v) {
    var n = parseFloat(String(v == null ? "" : v).replace(/[^0-9.\-]/g, ""));
    return isFinite(n) ? n : 0;
  };
  // Indian digit grouping, whole rupees: 1234567 -> 12,34,567
  var inr = function (v) {
    var neg = v < 0, s = String(Math.abs(Math.round(v)));
    if (s.length > 3) {
      var tail = s.slice(-3), head = s.slice(0, -3), g = [];
      while (head.length > 2) { g.unshift(head.slice(-2)); head = head.slice(0, -2); }
      if (head) g.unshift(head);
      s = g.join(",") + "," + tail;
    }
    return (neg ? "-" : "") + cur + s;
  };
  var pct = function (v) {
    var s = (Math.round(v * 100) / 100).toFixed(2);
    return s + "%";
  };

  function recalc() {
    var closingT = 0, paidT = 0, shareT = 0;
    form.querySelectorAll("[data-ground-seller]").forEach(function (row) {
      var closingInput = row.querySelector("[data-ground-closing]");
      var closing = num(closingInput.value);
      var paid = num(closingInput.getAttribute("data-paid"));
      var share = num(row.querySelector("[data-ground-share]").value);
      var remaining = closing - paid;
      var cell = row.querySelector("[data-ground-remaining]");
      cell.textContent = inr(remaining);
      cell.classList.toggle("v-neg", remaining > 0);
      cell.classList.toggle("v-pos", remaining <= 0);
      closingT += closing; paidT += paid; shareT += share;
    });
    var set = function (sel, text) { var el = form.querySelector(sel); if (el) el.textContent = text; };
    set("[data-ground-share-total]", pct(shareT));
    set("[data-ground-closing-total]", inr(closingT));
    set("[data-ground-remaining-total]", inr(closingT - paidT));
  }
  form.addEventListener("input", function (e) {
    if (e.target.matches("[data-ground-closing],[data-ground-share],[data-ground-lease]")) recalc();
  });
})();

/* Ground purchase payment dialog (older sellers+payments ledger, admin-only). */
(function () {
  "use strict";
  var modal = document.getElementById("gpayModal");
  var form = document.getElementById("gpayForm");
  if (!modal || !form) return;
  var title = document.getElementById("gpayModalTitle");
  var createAction = form.getAttribute("action");
  var f = function (n) { return form.querySelector('[name="' + n + '"]'); };
  var open = function () { if (modal.showModal) modal.showModal(); else modal.setAttribute("open", ""); };
  var close = function () { if (modal.close) modal.close(); else modal.removeAttribute("open"); };

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-open-gpay]")) {
      form.setAttribute("action", createAction); form.reset();
      title.textContent = "Record payment";
      var d = f("txn_date"); if (d && !d.value) d.value = new Date().toISOString().slice(0, 10);
      open(); return;
    }
    var ed = event.target.closest("[data-edit-gpay]");
    if (ed) {
      var data = ed.dataset;
      form.setAttribute("action", "/ground/payment/" + data.id + "/edit");
      title.textContent = "Edit payment";
      f("detail").value = data.detail || "";
      f("ex_partner_id").value = data.ex || "";
      f("partner_id").value = data.partner || "";
      f("txn_number").value = data.number || "";
      f("txn_date").value = data.date || "";
      f("amount").value = data.amount || "";
      f("note").value = data.note || "";
      open(); return;
    }
    if (event.target.closest("[data-close-gpay]")) close();
  });
  modal.addEventListener("click", function (event) { if (event.target === modal) close(); });
})();

/* Ground calendar: open the block dialog for a day, disable taken slots. */
(function () {
  "use strict";
  var modal = document.getElementById("blockModal");
  var form = document.getElementById("blockForm");
  if (!modal || !form) return;
  var read = function (id) {
    var n = document.getElementById(id);
    try { return n ? JSON.parse(n.textContent) : []; } catch (e) { return []; }
  };
  var dates = read("calBookings"), slots = read("calSlots");
  var taken = {};
  dates.forEach(function (d, i) { (taken[d] = taken[d] || []).push(slots[i]); });

  var dateInput = document.getElementById("b-date");
  var full = form.querySelector("[data-full-day]");
  var picks = Array.prototype.slice.call(form.querySelectorAll("[data-slot]"));
  var note = document.getElementById("b-taken");

  function sync() {
    var t = taken[dateInput.value] || [];
    var fullTaken = t.indexOf(full.value) >= 0;
    picks.forEach(function (p) {
      p.disabled = fullTaken || t.indexOf(p.value) >= 0 || full.checked;
      if (p.disabled) p.checked = false;
    });
    full.disabled = fullTaken || t.length > 0;
    if (full.disabled) full.checked = false;
    note.textContent = fullTaken ? "This day is already blocked for the full day."
      : (t.length ? "Already blocked: " + t.join(", ") + "." : "");
  }

  function open(day) {
    form.reset();
    dateInput.value = day || new Date().toISOString().slice(0, 10);
    sync();
    if (modal.showModal) modal.showModal(); else modal.setAttribute("open", "");
  }
  function close() { if (modal.close) modal.close(); else modal.removeAttribute("open"); }

  document.addEventListener("click", function (e) {
    var opener = e.target.closest("[data-open-block]");
    if (opener) { open(opener.getAttribute("data-date")); return; }
    if (e.target.closest("[data-close-block]")) close();
  });
  document.addEventListener("keydown", function (e) {
    var cell = e.target.closest && e.target.closest(".cal__day[data-open-block]");
    if (cell && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(cell.getAttribute("data-date")); }
  });
  modal.addEventListener("click", function (e) { if (e.target === modal) close(); });
  dateInput.addEventListener("change", sync);
  full.addEventListener("change", sync);
})();
